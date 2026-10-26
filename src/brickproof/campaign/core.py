"""A whole campaign on emulators that are already up: the baseline, the plan, and every
kind of test the adapter asks for, shared over the pool."""

from brickproof import plan as plans
from brickproof import torn as torns
from brickproof.adapter import Cut
from brickproof.pool import Pool
from brickproof.campaign.cuts import run_computed, run_cut, run_torn, soak
from brickproof.campaign.depth import explore
from brickproof.campaign.faults import bit_errors, content_faults, link_cuts
from brickproof.campaign.golden import Golden
from brickproof.campaign.judge import _failed
from brickproof.campaign.results import CutResult, Outcome


def auto_real_every(operations):
    """real_every for an update of this many operations. A short one has every planned cut
    made in the emulator. On a long one (MCUboot on an F411 programs byte by byte: hundreds
    of thousands of operations) most are powered up from the computed flash state instead,
    which is the same test, and the cuts still made in the emulator keep checking that the
    computed states are right."""
    if operations <= 2000:
        return 1
    return 4 if operations <= 50000 else 10


def _cuts_to_run(adapter, plan):
    """The adapter's own cuts, then the planned ones it does not already list."""
    cuts = list(adapter.cuts)
    if getattr(adapter, "plan", None):
        listed = {c.at_op for c in cuts if c.at_op is not None and c.group is None}
        cuts += [Cut(name="op-%d" % n, at_op=n) for n in plan.cuts if n not in listed]
    return cuts


def _past_the_end(cuts, operations):
    """Replace the cuts of an at_ops range that lie past the end of the update with one
    'skipped' result per range. The golden run has counted the operations, so there is
    no need to arm each of those cuts and wait for it not to fire."""
    out, ended = [], set()
    for cut in cuts:
        if cut.group is not None and cut.at_op is not None and cut.at_op >= operations:
            if cut.group not in ended:
                ended.add(cut.group)
                out.append(CutResult(cut=cut.name, skipped=True,
                                     message="the update has fewer operations"))
            continue
        out.append(cut)
    return out


def campaign(session, driver, adapter, on_result=None, fail_fast=False, baseline_only=False,
             oracle=None, on_plan=None, workers=()):
    """The baseline, then every cut, on a machine that is already up with the update
    staged. `workers` are further (session, driver) pairs to share the cuts with.
    Returns an Outcome.

    Kept apart from run() so the logic can be tested against a simulated device."""
    pool = Pool([(session, driver), *workers])
    pre = session.dump_flash()
    # If the update does not work when nothing interrupts it, no cut result means
    # anything, so that is checked first and a failure ends the run.
    golden = Golden(adapter, pre, oracle)
    baseline = run_cut(session, driver, adapter, None, golden)
    out = Outcome(results=[baseline], trace=golden.ops, jobs=len(pool), pre=bytes(pre))
    if on_result:
        on_result(baseline)
    if not baseline.passed:
        return out
    cfg = getattr(adapter, "plan", None) or {}
    out.plan = plans.make(golden.ops, pre, adapter.flash,
                          **{k: v for k, v in cfg.items() if k != "real_every"})
    if on_plan:
        on_plan(out.plan)
    if baseline_only:
        return out
    if getattr(adapter, "soak", None):
        soak(pool, adapter, golden, out, on_result)
        return out
    stop = _failed if fail_fast else None

    # With real_every N, only every Nth planned cut is made in the emulator; the others
    # start from the computed state. The real ones keep checking that those states are right.
    every = cfg.get("real_every", 1)
    if every == "auto":
        every = auto_real_every(len(golden.ops))
    every = max(1, every)
    cuts = _past_the_end(_cuts_to_run(adapter, out.plan), len(golden.ops))
    # A long campaign can be split over several machines: shard k of n takes every nth
    # cut. The cuts are the same list in the same order everywhere, so the shards
    # together make exactly the whole campaign.
    if getattr(adapter, "shard", None):
        k, n = adapter.shard
        out.shard = {"index": k, "of": n, "all_cuts": len(cuts)}
        cuts = cuts[k - 1::n]
        out.shard["cuts"] = len(cuts)
    planned = [c for c in cuts if isinstance(c, Cut) and c.at_op is not None and c.expect is None]
    real = {id(c) for c in planned[::every]} | {id(c) for c in planned[-1:]}
    computable = {id(c) for c in planned} - real

    def clean_cut(s, d, cut):
        if isinstance(cut, CutResult):
            return cut
        if every > 1 and id(cut) in computable:
            return run_computed(s, d, adapter, cut, golden)
        return run_cut(s, d, adapter, cut, golden)

    out.results += pool.run(clean_cut, cuts, on_result, stop)
    if fail_fast and any(_failed(r) for r in out.results):
        return out

    # Torn states come after the clean cuts, at the same operations: the half-done
    # versions of each operation a clean cut was made in front of.
    kinds = getattr(adapter, "torn", None)
    if kinds:
        def torn_at(s, d, n):
            before = bytes(golden.replay.at(n))
            return [run_torn(s, d, adapter, state, golden)
                    for state in torns.states(golden.ops[n], before, adapter.flash, kinds,
                                              adapter.torn_seed)]

        ops = sorted({r.op_index for r in out.results[1:] if r.fired and r.op_index < len(golden.ops)})
        out.results += pool.run(torn_at, ops, on_result, stop)
        if fail_fast and any(_failed(r) for r in out.results):
            return out

    if getattr(adapter, "depth", None):
        explore(pool, adapter, golden, out, on_result, fail_fast)
        if fail_fast and any(_failed(r) for r in out.results):
            return out

    # content faults are not cuts: in a sharded campaign the first shard makes them
    shard = getattr(adapter, "shard", None)
    if getattr(adapter, "content_faults", None) and golden.oracle and (not shard or shard[0] == 1):
        content_faults(pool, adapter, driver, golden, out, on_result, fail_fast)
        if fail_fast and any(_failed(r) for r in out.results):
            return out
    if getattr(adapter, "link_cuts", None) and (not shard or shard[0] == 1):
        link_cuts(pool, adapter, golden, out, on_result, fail_fast)
        if fail_fast and any(_failed(r) for r in out.results):
            return out
    if getattr(adapter, "bit_errors", None) and golden.oracle and (not shard or shard[0] == 1):
        bit_errors(pool, adapter, golden, out, on_result, fail_fast)
    return out
