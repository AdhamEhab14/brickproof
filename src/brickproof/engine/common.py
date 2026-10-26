"""What both emulator backends share: the lock-up a run can end in, how long to wait
before calling it one, TCP ports for the emulators, and closing any left running."""
import atexit
import socket
import threading
import time
import weakref

# Every session that has a Renode process. If the interpreter exits without them
# being closed (an exception in a user's script, Ctrl-C), they are closed here:
# a leftover renode.exe keeps eating CPU and slows every later run.
_live = weakref.WeakSet()


@atexit.register
def _close_leftovers():
    for session in list(_live):
        session.close()


class MachineHung(RuntimeError):
    """Emulated time stopped advancing: the firmware locked up (for example a fault
    while fetching the fault vector). On silicon that is a dead device too."""


SLOWEST_START = 6.0     # assume a slow machine until this one has been measured


def hang_limit(seconds, slowest):
    """Wall-clock seconds to wait for `seconds` of emulated time before deciding the
    emulated CPU is stuck (on Renode a locked-up core means RunFor never returns).

    Fifty times the slowest this machine has been seen to run, and never under 30 s.
    Too short calls a slow but healthy device dead, which is a false failure; too long
    only costs time on a device that really is dead. Renode does not run at an even
    pace: in a long run of byte-wide flash programs (MCUboot on the F411, about 390,000
    of them) a healthy emulator was measured taking 27 times its usual time for a second
    of emulated time, at random places, more often in a second run in the same process.
    Twenty times, and a fixed ceiling, called that a lock-up. The worst of that (a slice
    of 450 to 565 s where 20 s is usual) was Renode's clock missing a wake-up, which the
    flash models now prevent (wake_clock); the runner also repeats a hung run before it
    calls the device locked up."""
    return max(30.0, 50 * seconds * slowest)


_ports_lock = threading.Lock()


_ports_given = set()


def free_port():
    """A TCP port nothing is listening on, and that this process has not handed out
    before. The system only promises the first; with several sessions starting at
    once, two of them were given the same port."""
    with _ports_lock:
        for _ in range(200):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            s.close()
            if port not in _ports_given:
                _ports_given.add(port)
                return port
    raise RuntimeError("could not find a free TCP port")


def connect(port, wait):
    end = time.time() + wait
    while True:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=5)
        except OSError:
            if time.time() > end:
                raise
            time.sleep(0.2)
