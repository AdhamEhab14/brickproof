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
    START_TRIES = 1
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


def test_the_hang_limit_has_a_floor_and_follows_the_machine():
    assert S.hang_limit(0.05, S.SLOWEST_START) == 30.0, "never under 30 s"
    assert S.hang_limit(0.3, 1.0) == 30.0
    assert S.hang_limit(1.5, 6.0) == 450.0, "50x the slowest seen"
    # a healthy slice measured at 27x the usual pace must not count as a lock-up
    usual = 21.0                                    # wall s per emulated s, MCUboot on the F411
    assert S.hang_limit(0.16, usual) > 27 * usual * 0.16
    assert S.hang_limit(1.0, usual) > 27 * usual * 1.0, "no fixed ceiling cuts it short"
    assert S.hang_limit(6.0, 2.0) == 600.0
    slow, fast = S.hang_limit(2.0, 8.0), S.hang_limit(2.0, 2.0)
    assert slow > fast, "a slower machine gets more time"


def test_a_failed_start_is_tried_again(tmp_path):
    class Flaky(RenodeSession):
        QUIT_WAIT = 0.5
        tries = 0

        def _bring_up(self):
            Flaky.tries += 1
            self.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                         stdin=subprocess.PIPE)
            if Flaky.tries == 1:
                raise RuntimeError("Renode rejected something")

    s = Flaky("unused", str(tmp_path), FLASH, [])
    assert Flaky.tries == 2 and s.proc.poll() is None
    s.close()
