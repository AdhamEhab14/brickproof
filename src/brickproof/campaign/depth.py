"""A second cut (and more) while the device recovers from the first."""
import hashlib
import time

from brickproof import plan as plans
from brickproof import torn as torns
from brickproof.engine.session import MachineHung
from brickproof.campaign.golden import Golden
from brickproof.campaign.judge import _failed, _hang_confirmed, _rewind_program, _verdict
from brickproof.campaign.results import CutResult, SelfCheckFailed


def _digest(image):
    return hashlib.sha1(bytes(image)).digest()


def _recovery_trace(session, driver, adapter, image):
    """What the device does to flash when it is powered up from `image` and left alone."""
    session.restore_flash(image)
    session.power_cycle(settle=0)
    session.trace_start()
    if adapter.boot_settle:
        session.run_for(adapter.boot_settle)
    driver.alive()                              # lets time pass until the device is up
    if adapter.boot_settle:
        session.run_for(adapter.boot_settle)    # and a little more, for what it does right after
    return session.trace_stop()


@_hang_confirmed
def run_deep(session, driver, adapter, parent, m, name, level, state, real, root):
    """A cut during recovery: `parent` is the recovery (its starting flash and its traced
    operations), `m` the operation of it to cut before, `state` the flash that leaves.

    With real=True the cut is made in the emulator and the computed state is checked
    against it. Otherwise the device is powered up from the computed state directly,
    which is the same test (only flash survives a power cut) and much cheaper. `root` is
    the operation of the update the first cut fell before."""
    op = parent.ops[m]
    res = CutResult(cut=name, fired=True, kind=op["kind"], addr=op["addr"], op_index=m, depth=level)
    t0 = time.time()
    try:
        if real:
            session.restore_flash(parent.pre)
            session.power_cycle(settle=0)
            session.set_cut(m)
            if not session.run_until_cut(adapter.cut_limit):
                raise SelfCheckFailed("%s: the recovery did not reach operation %d when run a "
                                      "second time, so it is not deterministic" % (name, m))
            if op["kind"] == "program":
                _rewind_program(session, parent, res)
                session.flash_resync()
            parent.verify(session, m, "recovery cut %s" % name)
        else:
            session.restore_flash(state)
        _verdict(session, driver, adapter, res, parent.oracle, root)
        return res
    except MachineHung:
        res.hung = True
        res.message = "the device locked up (emulated CPU stopped making progress)"
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)

def explore(pool, adapter, golden, out, on_result=None, fail_fast=False):
    """Cuts during recovery, level by level.

    A state a cut left behind is powered up and its recovery traced. Cuts are planned
    over that trace like over an update, and each gives a flash state. One already
    tested is skipped: the same flash is the same test. Each new one is powered up and
    judged, and becomes a parent for the next level.

    Each level is three steps, so that the outcome does not depend on how many
    emulators share the work: trace every parent's recovery (in parallel), decide in
    parent order which states are new (one thread), then test those (in parallel)."""
    cfg = adapter.depth
    flash = adapter.flash
    plan_cfg = {k: cfg[k] for k in ("mode", "per_phase", "small")}
    torn_kinds = getattr(adapter, "torn", None) if cfg.get("torn") else None
    stats = {"levels": cfg["levels"], "states": 0, "skipped_known": 0, "capped": False,
             "deepest": 1}
    out.depth = stats
    clean = {r.op_index: r for r in out.results[1:] if r.fired and not r.torn and r.depth == 1}
    seen = {_digest(golden.pre)}
    for n in sorted(clean):
        seen.add(_digest(golden.replay.at(n)))
    # Which first-cut states to go deeper from: the depth plan's pick of a planned
    # run, or simply the cuts that were asked for when there is no plan.
    wanted = sorted(clean)
    if getattr(adapter, "plan", None):
        wanted = plans.make(golden.ops, golden.pre, flash, **plan_cfg).cuts
    parents = []
    for n in wanted:
        if n in clean and clean[n].passed:
            parents.append(("op-%d" % n, bytes(golden.replay.at(n)), n))

    for level in range(2, cfg["levels"] + 1):
        if not parents:
            break                               # nothing new left to cut during
        stats["deepest"] = level
        traces_ = pool.run(lambda s, d, p: [_recovery_trace(s, d, adapter, p[1])], parents)
        tasks = []
        for (label, image, root), ops in zip(parents, traces_, strict=True):
            if not ops:
                continue                        # this recovery writes nothing: nothing to cut
            parent = Golden(adapter, image, golden.oracle)
            parent.record(ops)
            real = True                         # the first new cut of each recovery is made for real
            for m in plans.make(ops, image, flash, **plan_cfg).cuts:
                state = bytes(parent.replay.at(m))
                d = _digest(state)
                if d in seen:
                    stats["skipped_known"] += 1
                    continue
                seen.add(d)
                if stats["states"] + len(tasks) >= cfg["max_states"]:
                    stats["capped"] = True
                    break
                tasks.append((parent, m, "%s > op-%d" % (label, m), state, real, None, root))
                real = False
                if torn_kinds:
                    # the half-done versions of this recovery operation, too
                    for t in torns.states(ops[m], state, flash, torn_kinds, adapter.torn_seed):
                        td = _digest(t.image)
                        if td not in seen:
                            seen.add(td)
                            tasks.append((parent, m, "%s > op-%d %s" % (label, m, t.kind),
                                          t.image, False, t.kind, root))
            if stats["capped"]:
                break

        def test(session, driver, task, level=level):
            parent, m, name, state, real, torn_kind, root = task
            r = run_deep(session, driver, adapter, parent, m, name, level, state, real, root)
            if torn_kind:
                r.torn, r.kind = torn_kind, torn_kind
            return r

        results = pool.run(test, tasks, on_result, _failed if fail_fast else None)
        out.results += results
        stats["states"] += len(results)
        if stats["capped"] or (fail_fast and any(_failed(r) for r in results)):
            return
        by_name = {r.cut: r for r in results}
        parents = [(t[2], t[3], t[6]) for t in tasks if t[5] is None and by_name[t[2]].passed]
