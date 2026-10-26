"""Drive one Renode instance in lock step with BrickProof, so runs are deterministic.

Renode is started with a monitor port. Virtual time only advances when we call
run_for(), and UART input is injected while the machine is paused. That removes
every wall-clock race between the host side and the emulated firmware.

Everything Renode needs is copied into a work folder first and referenced by
relative path, because the monitor breaks on paths with spaces.

Ported from the Three-Tier bootloader's tests/renode/renode_session.py."""
import os
import shutil
import subprocess          # the module the Process part starts Renode with (tests patch its Popen)

# ruff: noqa: F401
# The names other code has always imported from here, wherever they now live
from brickproof.engine.common import (SLOWEST_START, MachineHung, _close_leftovers, _live, _ports_given,
                                      _ports_lock, connect, free_port, hang_limit)
from brickproof.engine.flash_regs import *  # noqa: F403
from brickproof.engine.geometry import EXT_STATUS_BYTES, FlashGeometry
from brickproof.engine.renode.clock import Clock
from brickproof.engine.renode.flash_model import FlashModel
from brickproof.engine.renode.memory import Memory
from brickproof.engine.renode.power import Power
from brickproof.engine.renode.process import PROMPT_RE, Process, _launch_lock


def find_renode():
    """RENODE_PATH, else renode on PATH, else the one `brickproof setup` installed."""
    exe = os.environ.get("RENODE_PATH") or shutil.which("renode")
    if not exe:
        from brickproof import setup
        exe = setup.installed()
    return exe


class RenodeSession(Process, Clock, Memory, FlashModel, Power):
    """One emulated machine.

    workdir     folder that already holds platform.repl and the firmware files
    firmware    list of (relative path, address or None); ELFs load at their own
                addresses, anything else is loaded raw at `address`
    reset_cmds  monitor commands run after every reset (for example a held button)

    Its methods are in engine/renode/, one file per part: process (starting Renode and
    its monitor), clock (emulated time and the UART), memory, flash_model (cuts, the chip
    rules, the trace) and power (resets and power cycles).
    """


class RenodeSerial:
    """pyserial-like view of the emulated UART, so a target's real host tool runs unchanged."""

    def __init__(self, session, timeout=20, step=0.01, longest=0.08):
        self.s = session
        self.timeout = timeout
        self.step = step
        self.longest = longest

    def write(self, data):
        self.s.uart_write(bytes(data))

    def read(self, n):
        # the steps grow while nothing arrives: a prompt answer is read at once, and a
        # device that stays silent does not cost a round trip to the emulator every 10 ms
        waited, step = 0.0, self.step
        while len(self.s.rx) < n and waited < self.timeout:
            step = min(step, self.timeout - waited)
            self.s.run_for(step)
            waited += step
            step = min(step * 2, self.longest)
        out = bytes(self.s.rx[:n])
        del self.s.rx[:n]
        return out

    def sleep(self, seconds):
        """Host tools wait through this, so a wait advances emulated time, not real time."""
        self.s.idle(seconds)

    def close(self):
        pass
