"""Run an adapter's cut list: for each cut, start the update from the same flash
image, pull the plug, power back up and ask whether the device recovered."""
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass

from brickproof.engine import workdir as wd
from brickproof.engine.session import CUT_ERASE, MachineHung, RenodeSession, find_renode

KIND_NAMES = {0: "none", 1: "erase", 2: "program"}


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
    message: str = ""
    seconds: float = 0.0


def run_until_cut(session, limit, step=0.01):
    waited = 0.0
    while waited < limit:
        session.run_for(step)
        waited += step
        if session.cut_fired():
            return True
    return False


def run_cut(session, driver, adapter, cut, pre):
    res = CutResult(cut=cut.name)
    t0 = time.time()
    try:
        # every cut starts from the same image, right after the update was staged.
        # A target that updates during boot must be armed before it runs at all.
        session.restore_flash(pre)
        on_boot = getattr(driver, "update_on_boot", False)
        session.power_cycle(settle=0 if on_boot else adapter.boot_settle)
        base = session.flash_ops()
        if cut.on_erase is not None:
            session.set_cut_on_erase(cut.on_erase)
        else:
            session.set_cut(base + cut.at_op)
        driver.start_update()
        if not run_until_cut(session, adapter.cut_limit):
            if cut.group is not None:
                res.skipped = True
                res.message = "the update has fewer operations"
            else:
                res.message = "the cut never fired within %.0f s of virtual time" % adapter.cut_limit
            return res
        res.fired = True
        kind, addr = session.cut_info()
        res.kind, res.addr = KIND_NAMES.get(kind, str(kind)), addr
        res.op_index = session.flash_ops() - base
        if cut.expect and (kind, addr if kind == CUT_ERASE else 0) != cut.expect:
            res.message = "cut landed on %s 0x%08X, expected %s 0x%08X" % (
                res.kind, addr, KIND_NAMES[cut.expect[0]], cut.expect[1])
            return res

        session.power_cycle(settle=adapter.boot_settle)     # RAM gone, flash as the cut left it
        res.alive = bool(driver.alive())
        if not res.alive:
            res.message = "the device did not come back"
            return res
        res.recovered, msg = driver.check_recovered()
        res.message = msg or ""
        res.passed = res.recovered
        return res
    except MachineHung:
        # a locked-up CPU leaves Renode unusable; start a fresh one for the next cut
        res.message = ("the device locked up (emulated CPU stopped making progress)" if res.fired
                       else "the emulator hung before the cut fired")
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


def run(adapter, keep_workdir=False, log=None, on_result=None, fail_fast=False):
    """Run every cut of `adapter` (or up to the first failure with fail_fast).
    Returns (list of CutResult, timings dict)."""
    exe = find_renode()
    if not exe:
        raise RuntimeError("Renode not found: set RENODE_PATH or put renode on PATH")
    work = tempfile.mkdtemp(prefix="brickproof-")
    session = None
    timings = {}
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
        pre = session.dump_flash()
        timings["setup_s"] = round(time.time() - t0, 1)

        results = []
        ended = set()                   # range groups that already ran off the end
        for cut in adapter.cuts:
            if cut.group in ended:
                continue
            r = run_cut(session, driver, adapter, cut, pre)
            if r.skipped:
                ended.add(cut.group)    # op counts are deterministic: later ones won't fire either
            results.append(r)
            if on_result:
                on_result(r)
            if fail_fast and not (r.passed or r.skipped):
                break
        timings["total_s"] = round(time.time() - t0, 1)
        return results, timings
    finally:
        if session:
            session.close()
        if keep_workdir:
            print("work folder kept: %s" % work)
        else:
            shutil.rmtree(work, ignore_errors=True)


def as_dict(results, timings, adapter):
    return {
        "adapter": adapter.name,
        "target": os.path.basename(adapter.target),
        "passed": all(r.passed or r.skipped for r in results) and any(r.passed for r in results),
        "timings": timings,
        "cuts": [asdict(r) for r in results],
    }
