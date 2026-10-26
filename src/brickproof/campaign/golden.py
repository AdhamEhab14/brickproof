"""The uninterrupted update, recorded once: its operations, and the flash they predict
at each point, which every cut is checked against."""
import threading

from brickproof import trace as traces
from brickproof.campaign.results import SelfCheckFailed


class Golden:
    """The uninterrupted update: its operations, and the flash they predict at each one."""

    def __init__(self, adapter, pre, oracle=None):
        self.oracle = oracle
        self.flash = adapter.flash
        self.pre = pre
        self.check = adapter.check_states
        self.ops = []
        self.link_bytes = 0         # bytes the host sends during the uninterrupted update
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
