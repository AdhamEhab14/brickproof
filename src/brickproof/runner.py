"""Run an adapter's cut list: for each cut, start the update from the same flash
image, pull the plug, power back up and ask whether the device recovered."""
import hashlib
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field

from brickproof import oracle as oracles
from brickproof import plan as plans
from brickproof import torn as torns
from brickproof import trace as traces
from brickproof.adapter import Cut
from brickproof.engine import workdir as wd
from brickproof.engine.session import CUT_ERASE, MachineHung, RenodeSession, find_renode

KIND_NAMES = {0: "none", 1: "erase", 2: "program"}
BASELINE = "baseline (no cut)"


@dataclass
class CutResult:
    cut: str
    fired: bool = False
    kind: str = "none"
    addr: int = 0
    op_index: int = None        # which operation of the update was cut (0 = first)
    alive: bool = False
    recovered: bool = False
    passed: bool = False
    skipped: bool = False       # an at_ops range ran past the end of the update
    baseline: bool = False      # the uninterrupted update, run before any cut
    rewound: bool = False       # a program cut whose halfword had landed and was put back
    image: str = None           # the approved image the oracle found installed
    torn: str = None            # set for a torn state: which shape (see torn.py)
    depth: int = 1              # 2 = a second cut, during the recovery from a first one
    message: str = ""
    seconds: float = 0.0


class SelfCheckFailed(RuntimeError):
    """The emulated flash is not what the golden run says it should be. Either the
    tool is wrong or the update is not the same from one run to the next; both mean
    the results cannot be trusted, so the run stops (exit code 3)."""


class Golden:
    """The uninterrupted update: its operations, and the flash they predict at each one."""

    def __init__(self, adapter, pre, oracle=None):
        self.oracle = oracle
        self.flash = adapter.flash
        self.pre = pre
        self.check = adapter.check_states
        self.ops = []
        self.replay = None

    def record(self, ops):
        f = self.flash
        self.ops = ops
        self.replay = traces.Replay(self.pre, ops, f.base, f.page)

    def verify(self, session, n, what):
        """Compare the whole real flash with the replay just before operation n."""
        if not self.check:
            return
        want = self.replay.at(n)
        addr = session.flash_mismatch(bytes(want))
        if addr is not None:
            got = session.read_bytes(addr, 1)[0]
            raise SelfCheckFailed(
                "%s: flash differs from the golden run replayed to op %d, first at 0x%08X "
                "(is 0x%02X, expected 0x%02X). If the update is not deterministic, set "
                "scenario.check_states: false" % (what, n, addr, got, want[addr - self.flash.base]))


def _fault_message(session):
    """Something the firmware did that the emulator lets pass and the chip does not."""
    v = session.violations()
    if v["fault"]:
        return ("bus fault: the firmware touched 0x%08X (PC 0x%08X), which does not exist on "
                "the chip" % v["fault"])
    if v["refused"]:
        return ("flash rule broken: %d program(s) over cells that were not erased, first at "
                "0x%08X. An STM32F1 refuses these (PGERR) and keeps the old value" % v["refused"])
    if v["stray"]:
        return ("flash changed at 0x%08X with no flash operation behind it (a store with PG "
                "clear or the controller locked). The chip ignores such a write" % v["stray"])
    return None


def _rewind_program(session, golden, res):
    """Make a program cut land exactly before its halfword.

    The model stops the CPU when PG is set, but Renode finishes the instruction block
    it is in, and that block usually holds the store too. Left alone, "cut at op N"
    would mean "after op N", and the state right after an erase, with nothing
    programmed yet, would never be tested. If the halfword did land, put back what
    was there before it."""
    op = golden.ops[res.op_index]
    if "value" not in op:
        return                                             # it wrote what was already there
    f = golden.flash
    before = traces.value_before(golden.ops, res.op_index, golden.pre, f.base, f.page)
    if before != op["value"] and session.read_half(res.addr) == op["value"]:
        session.write_half(res.addr, before)
        res.rewound = True


def _verdict(session, driver, adapter, res, oracle):
    """Power up and judge. Three voices, and any one of them can fail the run: what
    the chip would not have allowed, the oracle (from outside the firmware), and the
    driver (the firmware's own signs of life). A power cycle clears the fault latch,
    so it is read before each one."""
    session.power_cycle(settle=adapter.boot_settle)     # RAM gone, flash as it was left
    res.alive = bool(driver.alive())
    fault = _fault_message(session)
    if fault:
        res.alive = False
        res.message = fault
        return
    if not res.alive:
        res.message = "the device did not come back"
        return
    if oracle:
        v = oracle.judge(session)
        res.image = v.image
        if not v.ok:
            res.message = v.message
            return
    res.recovered, msg = driver.check_recovered()
    fault = _fault_message(session)
    if fault:
        res.recovered = False
        msg = fault
    elif res.recovered and oracle:
        # the driver's checks may have poked the device (a rollback probe stages an
        # older image and reboots), so look once more at what it ended up as
        v = oracle.judge(session)
        res.image = v.image
        if not v.ok:
            res.recovered = False
            msg = "after the driver's checks: " + v.message
    res.message = msg or ""
    res.passed = res.recovered


def run_cut(session, driver, adapter, cut, golden):
    """One cut, or with cut=None the baseline: the same update left to finish.
    The baseline records the golden run; cuts use it to say where they landed and to
    check the flash they left behind."""
    res = CutResult(cut=cut.name if cut else BASELINE, baseline=cut is None)
    t0 = time.time()
    try:
        # every run starts from the same image, right after the update was staged.
        # A target that updates during boot must be armed before it runs at all.
        session.restore_flash(golden.pre)
        on_boot = getattr(driver, "update_on_boot", False)
        session.power_cycle(settle=0 if on_boot else adapter.boot_settle)
        base = session.flash_ops()
        if cut is None:
            session.trace_start()
            driver.start_update()
            session.run_for(adapter.update_time)
            golden.record(session.trace_stop())
            res.op_index = len(golden.ops)                 # here: how many operations it has
            # what the firmware did wrong comes first: a stray write also makes flash
            # differ from the replay, and that must not be reported as the tool's fault
            res.message = _fault_message(session) or ""
            if not res.message:
                golden.verify(session, len(golden.ops), "after the uninterrupted update")
                _verdict(session, driver, adapter, res, golden.oracle)
            return res

        if cut.on_erase is not None:
            session.set_cut_on_erase(cut.on_erase)
        else:
            session.set_cut(base + cut.at_op)
        driver.start_update()
        if not session.run_until_cut(adapter.cut_limit):
            fault = _fault_message(session)
            if fault:
                res.message = fault
            elif cut.group is not None:
                res.skipped = True
                res.message = "the update has fewer operations"
            else:
                res.message = "the cut never fired within %.0f s of virtual time" % adapter.cut_limit
            return res
        res.fired = True
        kind, addr, ops = session.cut_status()
        res.kind, res.addr = KIND_NAMES.get(kind, str(kind)), addr
        res.op_index = ops - base
        op = golden.ops[res.op_index] if res.op_index < len(golden.ops) else None
        if op and op["kind"] == res.kind == "program":
            res.addr = op["addr"]                          # the model never sees it; the golden run did
            _rewind_program(session, golden, res)
        if res.kind == "program":
            session.flash_resync()                         # the cut-short program is over
        if op:
            golden.verify(session, res.op_index, "cut %s" % cut.name)
        if cut.expect and (kind, addr if kind == CUT_ERASE else 0) != cut.expect:
            res.addr = addr
            res.message = "cut landed on %s 0x%08X, expected %s 0x%08X" % (
                res.kind, addr, KIND_NAMES[cut.expect[0]], cut.expect[1])
            return res
        _verdict(session, driver, adapter, res, golden.oracle)
        return res
    except MachineHung:
        # a locked-up CPU leaves Renode unusable; start a fresh one for the next cut
        res.message = ("the device locked up (emulated CPU stopped making progress)"
                       if res.fired or res.baseline else "the emulator hung before the cut fired")
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


def run_torn(session, driver, adapter, state, golden):
    """Boot the device from one torn state and judge it. Nothing is cut here: the
    state is the golden run replayed to just before an operation, with that operation
    left half done."""
    res = CutResult(cut="op-%d %s" % (state.op_index, state.kind), fired=True, kind=state.kind,
                    addr=state.addr, op_index=state.op_index, torn=state.kind)
    t0 = time.time()
    try:
        session.restore_flash(state.image)
        _verdict(session, driver, adapter, res, golden.oracle)
        return res
    except MachineHung:
        res.message = "the device locked up (emulated CPU stopped making progress)"
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


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


def run_deep(session, driver, adapter, parent, m, name, level, state, real):
    """A cut during recovery: `parent` is the recovery (its starting flash and its traced
    operations), `m` the operation of it to cut before, `state` the flash that leaves.

    With real=True the cut is made in the emulator and the computed state is checked
    against it. Otherwise the device is powered up from the computed state directly,
    which is the same test (only flash survives a power cut) and much cheaper."""
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
        _verdict(session, driver, adapter, res, parent.oracle)
        return res
    except MachineHung:
        res.message = "the device locked up (emulated CPU stopped making progress)"
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


def explore(session, driver, adapter, golden, out, on_result=None, fail_fast=False):
    """Cuts during recovery, level by level.

    A state a cut left behind is powered up and its recovery traced. Cuts are planned
    over that trace like over an update, and each gives a flash state. One already
    tested is skipped: the same flash is the same test. Each new one is powered up and
    judged, and becomes a parent for the next level."""
    cfg = adapter.depth
    flash = adapter.flash
    plan_cfg = {k: cfg[k] for k in ("mode", "per_phase", "small")}
    stats = {"levels": cfg["levels"], "states": 0, "skipped_known": 0, "capped": False}
    out.depth = stats
    clean = {r.op_index: r for r in out.results[1:] if r.fired and not r.torn and r.depth == 1}
    seen = {_digest(golden.pre)}
    for n in sorted(clean):
        seen.add(_digest(golden.replay.at(n)))
    parents = []
    for n in plans.make(golden.ops, golden.pre, flash, **plan_cfg).cuts:
        if n in clean and clean[n].passed:
            parents.append(("op-%d" % n, bytes(golden.replay.at(n))))
    for level in range(2, cfg["levels"] + 1):
        found = []
        for label, image in parents:
            ops = _recovery_trace(session, driver, adapter, image)
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
                if stats["states"] >= cfg["max_states"]:
                    stats["capped"] = True
                    return
                r = run_deep(session, driver, adapter, parent, m, "%s > op-%d" % (label, m),
                             level, state, real)
                real = False
                stats["states"] += 1
                out.results.append(r)
                if on_result:
                    on_result(r)
                if r.passed:
                    found.append((r.cut, state))
                elif fail_fast:
                    return
        parents = found


@dataclass
class Outcome:
    results: list               # CutResult: the baseline first, then each cut
    trace: list                 # the golden run's operations
    plan: object = None         # plan.Plan: what the trace offers and what was chosen
    depth: dict = None          # what the exploration of cuts during recovery covered
    timings: dict = field(default_factory=dict)

    @property
    def passed(self):
        return all(r.passed or r.skipped for r in self.results) and any(r.passed for r in self.results)


def _cuts_to_run(adapter, plan):
    """The adapter's own cuts, then the planned ones it does not already list."""
    cuts = list(adapter.cuts)
    if getattr(adapter, "plan", None):
        listed = {c.at_op for c in cuts if c.at_op is not None and c.group is None}
        cuts += [Cut(name="op-%d" % n, at_op=n) for n in plan.cuts if n not in listed]
    return cuts


def campaign(session, driver, adapter, on_result=None, fail_fast=False, baseline_only=False,
             oracle=None, on_plan=None):
    """The baseline, then every cut, on a machine that is already up with the update
    staged. Returns an Outcome.

    Kept apart from run() so the logic can be tested against a simulated device."""
    pre = session.dump_flash()
    # If the update does not work when nothing interrupts it, no cut result means
    # anything, so that is checked first and a failure ends the run.
    golden = Golden(adapter, pre, oracle)
    baseline = run_cut(session, driver, adapter, None, golden)
    out = Outcome(results=[baseline], trace=golden.ops)
    if on_result:
        on_result(out.results[0])
    if not out.results[0].passed:
        return out
    cfg = getattr(adapter, "plan", None) or {}
    out.plan = plans.make(golden.ops, pre, adapter.flash, **cfg)
    if on_plan:
        on_plan(out.plan)
    ended = set()                   # range groups that already ran off the end
    for cut in [] if baseline_only else _cuts_to_run(adapter, out.plan):
        if cut.group in ended:
            continue
        r = run_cut(session, driver, adapter, cut, golden)
        if r.skipped:
            ended.add(cut.group)    # op counts are deterministic: later ones won't fire either
        out.results.append(r)
        if on_result:
            on_result(r)
        if fail_fast and not (r.passed or r.skipped):
            return out
    # Torn states come after the clean cuts, at the same operations: the half-done
    # versions of each operation a clean cut was made in front of.
    kinds = getattr(adapter, "torn", None)
    ops = sorted({r.op_index for r in out.results[1:] if r.fired and r.op_index < len(golden.ops)})
    for n in ops if kinds and not baseline_only else []:
        before = bytes(golden.replay.at(n))
        for state in torns.states(golden.ops[n], before, adapter.flash, kinds, adapter.torn_seed):
            r = run_torn(session, driver, adapter, state, golden)
            out.results.append(r)
            if on_result:
                on_result(r)
            if fail_fast and not r.passed:
                return out
    if getattr(adapter, "depth", None) and not baseline_only:
        explore(session, driver, adapter, golden, out, on_result, fail_fast)
    return out


def run(adapter, keep_workdir=False, log=None, on_result=None, fail_fast=False, baseline_only=False,
        on_plan=None):
    """Start Renode, stage the update and run the campaign (up to the first failure
    with fail_fast). Returns an Outcome."""
    exe = find_renode()
    if not exe:
        raise RuntimeError("Renode not found: set RENODE_PATH or put renode on PATH")
    work = tempfile.mkdtemp(prefix="brickproof-")
    session = None
    try:
        firmware = wd.prepare(work, adapter)
        t0 = time.time()
        session = RenodeSession(exe, work, adapter.flash, firmware, uart=adapter.uart,
                                vector_table=adapter.vector_table, mips=adapter.mips,
                                reset_cmds=adapter.reset_cmds, log=log,
                                memory_sizes=wd.memory_sizes(adapter))
        session.run_for(adapter.boot_settle)
        driver = adapter.load_driver(session)
        driver.prepare()
        setup = round(time.time() - t0, 1)
        out = campaign(session, driver, adapter, on_result, fail_fast, baseline_only,
                       oracles.build(adapter, driver), on_plan)
        out.timings = {"setup_s": setup, "total_s": round(time.time() - t0, 1),
                       "rewound": sum(r.rewound for r in out.results)}
        return out
    finally:
        if session:
            session.close()
        if keep_workdir:
            print("work folder kept: %s" % work)
        else:
            shutil.rmtree(work, ignore_errors=True)


def as_dict(outcome, adapter):
    return {
        "adapter": adapter.name,
        "target": os.path.basename(adapter.target),
        "passed": outcome.passed,
        "coverage": outcome.plan.as_dict() if outcome.plan else None,
        "depth": outcome.depth,
        "timings": outcome.timings,
        "cuts": [asdict(r) for r in outcome.results],
    }
