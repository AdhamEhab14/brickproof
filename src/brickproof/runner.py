"""Run an adapter's cut list: for each cut, start the update from the same flash
image, pull the plug, power back up and ask whether the device recovered."""
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass

from brickproof import trace as traces
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
    message: str = ""
    seconds: float = 0.0


class SelfCheckFailed(RuntimeError):
    """The emulated flash is not what the golden run says it should be. Either the
    tool is wrong or the update is not the same from one run to the next; both mean
    the results cannot be trusted, so the run stops (exit code 3)."""


class Golden:
    """The uninterrupted update: its operations, and the flash they predict at each one."""

    def __init__(self, adapter, pre):
        self.flash = adapter.flash
        self.pre = pre
        self.check = adapter.check_states
        self.ops = []
        self.replay = None
        self.pages = []

    def record(self, ops):
        f = self.flash
        self.ops = ops
        self.replay = traces.Replay(self.pre, ops, f.base, f.page)
        self.pages = traces.touched_pages(ops, f.page, f.base, f.size)

    def verify(self, session, n, what):
        """Compare real flash with the replay just before operation n, on every page
        the update touches."""
        if not self.check:
            return
        want = self.replay.at(n)
        for page in self.pages:
            off = page - self.flash.base
            got = session.read_bytes(page, self.flash.page)
            if got != want[off:off + self.flash.page]:
                i = next(i for i in range(self.flash.page) if got[i] != want[off + i])
                raise SelfCheckFailed(
                    "%s: flash differs from the golden run replayed to op %d, first at 0x%08X "
                    "(is 0x%02X, expected 0x%02X). If the update is not deterministic, set "
                    "scenario.check_states: false" % (what, n, page + i, got[i], want[off + i]))


def run_until_cut(session, limit, step=0.01):
    waited = 0.0
    while waited < limit:
        session.run_for(step)
        waited += step
        if session.cut_fired():
            return True
    return False


def _fault_message(session):
    fault = session.bus_fault()
    if not fault:
        return None
    return ("bus fault: the firmware touched 0x%08X (PC 0x%08X), which does not exist on the chip"
            % fault)


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


def _verdict(session, driver, adapter, res):
    """Power up and judge. A reset clears the fault latch, so it is read before each one."""
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
    res.recovered, msg = driver.check_recovered()
    fault = _fault_message(session)
    if fault:
        res.recovered = False
        msg = fault
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
            golden.verify(session, len(golden.ops), "after the uninterrupted update")
            res.message = _fault_message(session) or ""
            if not res.message:
                _verdict(session, driver, adapter, res)
            return res

        if cut.on_erase is not None:
            session.set_cut_on_erase(cut.on_erase)
        else:
            session.set_cut(base + cut.at_op)
        driver.start_update()
        if not run_until_cut(session, adapter.cut_limit):
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
        kind, addr = session.cut_info()
        res.kind, res.addr = KIND_NAMES.get(kind, str(kind)), addr
        res.op_index = session.flash_ops() - base
        op = golden.ops[res.op_index] if res.op_index < len(golden.ops) else None
        if op and op["kind"] == res.kind == "program":
            res.addr = op["addr"]                          # the model never sees it; the golden run did
            _rewind_program(session, golden, res)
        if op:
            golden.verify(session, res.op_index, "cut %s" % cut.name)
        if cut.expect and (kind, addr if kind == CUT_ERASE else 0) != cut.expect:
            res.addr = addr
            res.message = "cut landed on %s 0x%08X, expected %s 0x%08X" % (
                res.kind, addr, KIND_NAMES[cut.expect[0]], cut.expect[1])
            return res
        _verdict(session, driver, adapter, res)
        return res
    except MachineHung:
        # a locked-up CPU leaves Renode unusable; start a fresh one for the next cut
        res.message = ("the device locked up (emulated CPU stopped making progress)"
                       if res.fired or res.baseline else "the emulator hung before the cut fired")
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


def run(adapter, keep_workdir=False, log=None, on_result=None, fail_fast=False, baseline_only=False):
    """Run the baseline, then every cut of `adapter` (or up to the first failure with
    fail_fast). Returns (list of CutResult, timings dict, golden-run trace)."""
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

        # If the update does not work when nothing interrupts it, no cut result means
        # anything, so that is checked first and a failure ends the run.
        golden = Golden(adapter, pre)
        results = [run_cut(session, driver, adapter, None, golden)]
        if on_result:
            on_result(results[0])
        ended = set()                   # range groups that already ran off the end
        for cut in adapter.cuts if results[0].passed and not baseline_only else []:
            if cut.group in ended:
                continue
            r = run_cut(session, driver, adapter, cut, golden)
            if r.skipped:
                ended.add(cut.group)    # op counts are deterministic: later ones won't fire either
            results.append(r)
            if on_result:
                on_result(r)
            if fail_fast and not (r.passed or r.skipped):
                break
        timings["total_s"] = round(time.time() - t0, 1)
        timings["rewound"] = sum(r.rewound for r in results)
        return results, timings, golden.ops
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
