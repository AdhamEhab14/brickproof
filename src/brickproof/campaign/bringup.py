"""Starting the emulators a campaign runs on, and running it: the entry point behind
`brickproof run`."""
import hashlib
import os
import shutil
import tempfile
import threading
import time

from brickproof import oracle as oracles
from brickproof.engine import workdir as wd
from brickproof.engine.m33mu import M33muSession, find_m33mu
from brickproof.engine.session import RenodeSession, find_renode
from brickproof.campaign.core import campaign


def find_emulator(adapter):
    """The executable of the emulator this adapter's chip runs on."""
    if adapter.emulator == "m33mu":
        exe = find_m33mu()
        if not exe:
            raise RuntimeError("m33mu not found: set M33MU_PATH or put m33mu on PATH "
                               "(%s is emulated by m33mu, https://github.com/danielinux/m33mu)"
                               % adapter.platform)
        return exe
    exe = find_renode()
    if not exe:
        raise RuntimeError("Renode not found: set RENODE_PATH or put renode on PATH")
    return exe


def start_session(adapter, exe, log=None):
    """One emulator with the firmware loaded, not yet run: (session, work folder). The
    caller closes the session and removes the folder."""
    work = tempfile.mkdtemp(prefix="brickproof-")
    try:
        firmware = wd.prepare(work, adapter)
        if adapter.emulator == "m33mu":
            session = M33muSession(exe, work, adapter.flash, firmware, cpu=adapter.platform,
                                   uart=adapter.uart, optbytes=adapter.optbytes,
                                   vector_table=adapter.vector_table, log=log)
        else:
            session = RenodeSession(exe, work, adapter.flash, firmware, uart=adapter.uart,
                                    vector_table=adapter.vector_table, mips=adapter.mips,
                                    reset_cmds=adapter.reset_cmds, log=log,
                                    ram=wd.MEMORIES[adapter.platform]["ram"][0],
                                    memory_sizes=wd.memory_sizes(adapter))
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return session, work


def _bring_up(adapter, exe, log, shared=None):
    """One emulator, booted, with the update staged. Returns (session, driver, work folder).
    `shared` is what the first driver exported, so that every worker starts an update
    with exactly the same bytes (a driver may sign its image with a timestamp)."""
    session, work = start_session(adapter, exe, log)
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
    """Start the emulator (`jobs` of them), stage the update and run the campaign (up
    to the first failure with fail_fast). Returns an Outcome."""
    exe = find_emulator(adapter)
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
