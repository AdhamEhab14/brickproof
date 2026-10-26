"""Power cut during the update, in the emulator or powered up from the computed state,
and torn erases and programs; and the random soak over all of them."""
import random
import time

from brickproof import torn as torns
from brickproof.adapter import Cut
from brickproof.engine.session import CUT_ERASE, MachineHung
from brickproof.campaign.judge import _failed, _fault_message, _hang_confirmed, _rewind_program, _verdict
from brickproof.campaign.results import BASELINE, CutResult, KIND_NAMES, SelfCheckFailed


@_hang_confirmed
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
            sent = getattr(session, "uart_sent", 0)
            driver.start_update()
            golden.link_bytes = getattr(session, "uart_sent", 0) - sent
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
        if res.op_index >= len(golden.ops):
            # the golden run ended before this operation: the update did more this time
            raise SelfCheckFailed("cut %s: fired at operation %d, but the uninterrupted update "
                                  "has only %d, so the update is not the same from one run to "
                                  "the next" % (cut.name, res.op_index, len(golden.ops)))
        op = golden.ops[res.op_index]
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
        _verdict(session, driver, adapter, res, golden.oracle, res.op_index)
        return res
    except MachineHung:
        res.hung = True
        # a locked-up CPU leaves Renode unusable; start a fresh one for the next cut
        res.message = ("the device locked up (emulated CPU stopped making progress)"
                       if res.fired or res.baseline else "the emulator hung before the cut fired")
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


@_hang_confirmed
def run_torn(session, driver, adapter, state, golden):
    """Boot the device from one torn state and judge it. Nothing is cut here: the
    state is the golden run replayed to just before an operation, with that operation
    left half done."""
    res = CutResult(cut="op-%d %s" % (state.op_index, state.kind), fired=True, kind=state.kind,
                    addr=state.addr, op_index=state.op_index, torn=state.kind)
    t0 = time.time()
    try:
        session.restore_flash(state.image)
        _verdict(session, driver, adapter, res, golden.oracle, state.op_index)
        return res
    except MachineHung:
        res.hung = True
        res.message = "the device locked up (emulated CPU stopped making progress)"
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


@_hang_confirmed
def run_computed(session, driver, adapter, cut, golden):
    """A clean cut without running the update up to it: power the device up from the
    flash the golden run predicts just before that operation. It is the same test,
    because only flash survives a power cut, and every cut that IS made in the emulator
    checks that prediction byte for byte."""
    op = golden.ops[cut.at_op]
    res = CutResult(cut=cut.name, fired=True, kind=op["kind"], addr=op["addr"], op_index=cut.at_op,
                    computed=True)
    t0 = time.time()
    try:
        session.restore_flash(bytes(golden.replay.at(cut.at_op)))
        _verdict(session, driver, adapter, res, golden.oracle, cut.at_op)
        return res
    except MachineHung:
        res.hung = True
        res.message = "the device locked up (emulated CPU stopped making progress)"
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


def soak(pool, adapter, golden, out, on_result=None):
    """Random tests until a deadline or the first failure: a clean cut before a random
    operation (powered up from the computed state), or that operation left half done in a
    random torn shape. Seeded, so the same seed draws the same tests."""
    seconds, seed = adapter.soak
    rng = random.Random("soak/%s" % seed)
    kinds = list(getattr(adapter, "torn", None) or torns.KINDS)
    deadline = time.time() + seconds
    n_ops = len(golden.ops)

    def one(session, driver, task):
        n, kind = task
        if kind is None:
            return run_computed(session, driver, adapter, Cut(name="soak op-%d" % n, at_op=n), golden)
        before = bytes(golden.replay.at(n))
        states = torns.states(golden.ops[n], before, adapter.flash, (kind,), adapter.torn_seed)
        if not states:              # that shape does not apply here: a clean cut instead
            return run_computed(session, driver, adapter, Cut(name="soak op-%d" % n, at_op=n), golden)
        res = run_torn(session, driver, adapter, states[0], golden)
        res.cut = "soak " + res.cut
        return res

    while time.time() < deadline and n_ops:
        tasks = [(rng.randrange(n_ops), rng.choice(kinds) if rng.random() < 0.4 else None)
                 for _ in range(len(pool))]
        results = pool.run(one, tasks, on_result, _failed)
        out.results += results
        if any(_failed(r) for r in results):
            return
