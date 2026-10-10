"""A session must never leave its emulator process behind, however it ends.

A stand-in process plays Renode here (a Python that just waits), so these run
without an emulator.
"""
import subprocess
import sys

import pytest

from brickproof.engine import session as S
from brickproof.engine.session import FlashGeometry, RenodeSession

FLASH = FlashGeometry(base=0x08000000, size=0x1000, page=0x400)


class Standin(RenodeSession):
    """Starts a process that never opens a monitor port, so start-up fails."""
    STARTUP_WAIT = 0.5
    QUIT_WAIT = 0.5
    started = None

    def _bring_up(self):
        self.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                     stdin=subprocess.PIPE)
        Standin.started = self.proc
        self.mon = S.connect(S.free_port(), self.STARTUP_WAIT)     # nobody is listening


def test_a_failed_start_up_does_not_leak_the_process(tmp_path):
    with pytest.raises(OSError):
        Standin("unused", str(tmp_path), FLASH, [])
    assert Standin.started.poll() is not None, "the stand-in emulator is still running"


def test_close_is_safe_twice_and_before_anything_started():
    s = RenodeSession.__new__(RenodeSession)        # nothing brought up at all
    s.close()
    s.close()


def test_sessions_left_open_are_closed_at_exit(tmp_path):
    class Running(RenodeSession):
        QUIT_WAIT = 0.5

        def _bring_up(self):
            self.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                         stdin=subprocess.PIPE)

    s = Running("unused", str(tmp_path), FLASH, [])
    proc = s.proc
    assert s in S._live and proc.poll() is None
    S._close_leftovers()                            # what atexit runs
    assert proc.poll() is not None and s not in S._live
