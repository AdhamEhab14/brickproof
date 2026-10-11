"""Run an adapter's cut list: for each cut, start the update from the same flash
image, pull the plug, power back up and ask whether the device recovered."""
import hashlib
import os
import shutil
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field

from brickproof import __version__
from brickproof import oracle as oracles
from brickproof import plan as plans
from brickproof import torn as torns
from brickproof import trace as traces
from brickproof.adapter import Cut
from brickproof.engine import workdir as wd
from brickproof.pool import Pool
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
    computed: bool = False      # powered up from the computed flash state, not cut in the emulator
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
        self._local = threading.local()

    def record(self, ops):
        self.ops = ops
        self._local = threading.local()

    @property
    def replay(self):
        """The golden run replayed to any operation. One per thread: a replay keeps its
        place, and several emulators' threads ask for different places at once."""
        r = getattr(self._local, "replay", None)
        if r is None:
            f = self.flash
            r = self._local.replay = traces.Replay(self.pre, self.ops, f)
        return r

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
                "scenario.check_states: false" % (
                    what, n, addr, got, want[traces.locate(addr, self.flash)[0]]))


def _fault_message(session):
    """Something the firmware did that the emulator lets pass and the chip does not."""
    v = session.violations()
    if v["fault"]:
        return ("bus fault: the firmware touched 0x%08X (PC 0x%08X), which does not exist on "
                "the chip" % v["fault"])
    if v["refused"]:
        return ("flash rule broken: %d program(s) over cells that were not erased, first at "
                "0x%08X. An STM32F1 refuses these (PGERR) and keeps the old value" % v["refused"])
    if v.get("protected"):
        return ("write protection: %d erase or program operation(s) in write-protected flash "
                "were refused, first at 0x%08X. The option bytes protect that page, so the "
                "chip changes nothing there" % v["protected"])
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
    before = traces.value_before(golden.ops, res.op_index, golden.pre, golden.flash)
    # Compared with what was there before, not with the traced value: the two can differ
    # at this instant. An option byte is traced as the chip stores it (the byte and its
    # complement), but until the program is settled the cell holds what was written.
    if session.read_half(res.addr) != before:
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


def _failed(r):
    return not (r.passed or r.skipped)


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
    stats = {"levels": cfg["levels"], "states": 0, "skipped_known": 0, "capped": False}
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
            parents.append(("op-%d" % n, bytes(golden.replay.at(n))))

    for level in range(2, cfg["levels"] + 1):
        traces_ = pool.run(lambda s, d, p: [_recovery_trace(s, d, adapter, p[1])], parents)
        tasks = []
        for (label, image), ops in zip(parents, traces_, strict=True):
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
                tasks.append((parent, m, "%s > op-%d" % (label, m), state, real, None))
                real = False
                if torn_kinds:
                    # the half-done versions of this recovery operation, too
                    for t in torns.states(ops[m], state, flash, torn_kinds, adapter.torn_seed):
                        td = _digest(t.image)
                        if td not in seen:
                            seen.add(td)
                            tasks.append((parent, m, "%s > op-%d %s" % (label, m, t.kind),
                                          t.image, False, t.kind))
            if stats["capped"]:
                break

        def test(session, driver, task, level=level):
            parent, m, name, state, real, torn_kind = task
            r = run_deep(session, driver, adapter, parent, m, name, level, state, real)
            if torn_kind:
                r.torn, r.kind = torn_kind, torn_kind
            return r

        results = pool.run(test, tasks, on_result, _failed if fail_fast else None)
        out.results += results
        stats["states"] += len(results)
        if stats["capped"] or (fail_fast and any(_failed(r) for r in results)):
            return
        by_name = {r.cut: r for r in results}
        parents = [(t[2], t[3]) for t in tasks if t[5] is None and by_name[t[2]].passed]


@dataclass
class Outcome:
    results: list               # CutResult: the baseline first, then each cut
    trace: list                 # the golden run's operations
    plan: object = None         # plan.Plan: what the trace offers and what was chosen
    depth: dict = None          # what the exploration of cuts during recovery covered
    timings: dict = field(default_factory=dict)
    started: str = ""           # when the run began, UTC
    inputs: list = field(default_factory=list)   # the firmware files tested, with their hashes
    jobs: int = 1               # how many emulators shared the work

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
    out = Outcome(results=[baseline], trace=golden.ops, jobs=len(pool))
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
    stop = _failed if fail_fast else None

    # With real_every N, only every Nth planned cut is made in the emulator; the others
    # start from the computed state. The real ones keep checking that those states are right.
    every = max(1, cfg.get("real_every", 1))
    cuts = _past_the_end(_cuts_to_run(adapter, out.plan), len(golden.ops))
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
    return out


def _bring_up(adapter, exe, log, shared=None):
    """One emulator, booted, with the update staged. Returns (session, driver, work folder).
    `shared` is what the first driver exported, so that every worker starts an update
    with exactly the same bytes (a driver may sign its image with a timestamp)."""
    work = tempfile.mkdtemp(prefix="brickproof-")
    try:
        firmware = wd.prepare(work, adapter)
        session = RenodeSession(exe, work, adapter.flash, firmware, uart=adapter.uart,
                                vector_table=adapter.vector_table, mips=adapter.mips,
                                reset_cmds=adapter.reset_cmds, log=log,
                                memory_sizes=wd.memory_sizes(adapter))
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    try:
        session.run_for(adapter.boot_settle)
        driver = adapter.load_driver(session)
        if shared is not None and hasattr(driver, "import_state"):
            driver.import_state(shared)
        else:
            driver.prepare()
        return session, driver, work
    except BaseException:
        session.close()
        shutil.rmtree(work, ignore_errors=True)
        raise


def run(adapter, keep_workdir=False, log=None, on_result=None, fail_fast=False, baseline_only=False,
        on_plan=None, jobs=1):
    """Start Renode (`jobs` of them), stage the update and run the campaign (up to the
    first failure with fail_fast). Returns an Outcome."""
    exe = find_renode()
    if not exe:
        raise RuntimeError("Renode not found: set RENODE_PATH or put renode on PATH")
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    inputs = []
    for path, _addr in adapter.firmware:
        with open(path, "rb") as f:
            inputs.append({"file": os.path.basename(path), "sha256": hashlib.sha256(f.read()).hexdigest()})
    up = []                             # every (session, driver, work folder) that was started
    lock = threading.Lock()
    try:
        t0 = time.time()
        up.append(_bring_up(adapter, exe, log))
        session, driver, _ = up[0]
        shared = driver.export_state() if hasattr(driver, "export_state") else None
        errors = []

        def start_one():
            try:
                w = _bring_up(adapter, exe, log, shared)
                with lock:
                    up.append(w)
            except BaseException as e:      # noqa: B036 - reported from the main thread
                errors.append(e)

        extra = 0 if baseline_only else max(0, jobs - 1)
        threads = [threading.Thread(target=start_one, daemon=True) for _ in range(extra)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            raise errors[0]
        setup = round(time.time() - t0, 1)
        out = campaign(session, driver, adapter, on_result, fail_fast, baseline_only,
                       oracles.build(adapter, driver), on_plan,
                       workers=[(s, d) for s, d, _ in up[1:]])
        out.timings = {"setup_s": setup, "total_s": round(time.time() - t0, 1),
                       "rewound": sum(r.rewound for r in out.results)}
        out.started = started
        out.inputs = inputs
        return out
    finally:
        for s, _d, work in up:
            s.close()
            if keep_workdir:
                print("work folder kept: %s" % work)
            else:
                shutil.rmtree(work, ignore_errors=True)


def as_dict(outcome, adapter):
    """Everything about a run, as plain data. The JSON, JUnit and HTML reports are all
    made from this."""
    return {
        "adapter": adapter.name,
        "adapter_file": getattr(adapter, "path", "") or "adapter.yaml",
        "target": os.path.basename(adapter.target),
        "brickproof": __version__,
        "started": outcome.started,
        "inputs": outcome.inputs,
        "oracle": bool(getattr(adapter, "oracle", None)),
        "passed": outcome.passed,
        "jobs": outcome.jobs,
        "coverage": outcome.plan.as_dict() if outcome.plan else None,
        "depth": outcome.depth,
        "timings": outcome.timings,
        "cuts": [asdict(r) for r in outcome.results],
    }
