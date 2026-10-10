"""A simulated device with the same interface as RenodeSession, for testing the
runner's logic without an emulator.

Its "firmware" is the simplest overwrite updater: a marker halfword says an update
is pending; on boot, if it is set, erase the slot, copy the new image in, clear the
marker. Because the marker is cleared last, a cut anywhere just means the next boot
does it all again. Options break it in known ways, to check the runner notices.
"""
from brickproof.engine.session import CUT_ERASE, CUT_PROGRAM, NEVER, FlashGeometry, MachineHung

BASE = 0x08000000
PAGE = 0x400
SLOT = BASE + PAGE              # one page that holds the running image
MARKER = BASE + 3 * PAGE        # nonzero-and-not-erased here = an update is pending
STAGED = BASE + 2 * PAGE        # the new image waits here
NEW_IMAGE = bytes(range(1, 17))                 # 8 halfwords
OLD_IMAGE = bytes([0xA0 + i for i in range(16)])


def staged_flash():
    """Flash with the old image running and an update staged."""
    f = bytearray(b"\xFF" * (4 * PAGE))
    f[PAGE:PAGE + 16] = OLD_IMAGE
    f[2 * PAGE:2 * PAGE + 16] = NEW_IMAGE
    f[3 * PAGE:3 * PAGE + 2] = b"\x55\xAA"
    return bytes(f)


class FakeDevice:
    """lands_after   a program cut stops after its halfword is written, like Renode
    no_recovery     after a cut the firmware forgets the pending update (a brick)
    fault_at        bus fault when the update reaches this operation
    hang_on_boot    the CPU locks up on the boot after a cut
    nondeterministic  the second and later runs write a different halfword
    """

    def __init__(self, lands_after=True, no_recovery=False, fault_at=None, hang_on_boot=False,
                 nondeterministic=False, refuse=False, stray=False):
        self.flash = FlashGeometry(base=BASE, size=4 * PAGE, page=PAGE)
        self.mem = bytearray(staged_flash())
        self.opt = dict(lands_after=lands_after, no_recovery=no_recovery, fault_at=fault_at,
                        hang_on_boot=hang_on_boot, nondeterministic=nondeterministic,
                        refuse=refuse, stray=stray)
        self.opcount = 0
        self.cutpoint = NEVER
        self.cut_page = NEVER
        self.cut = None                 # (kind, addr) once fired
        self.halted = False
        self.fault = None
        self.refused = None
        self.stray = None
        self.tracing = False
        self.trace = []
        self.runs = 0                   # how many updates were started
        self.restarts = 0
        self.was_cut = False
        self.boot_pending = False

    # ---- the firmware ------------------------------------------------------

    def _half(self, addr):
        o = addr - BASE
        return self.mem[o] | (self.mem[o + 1] << 8)

    def _put(self, addr, value):
        o = addr - BASE
        self.mem[o], self.mem[o + 1] = value & 0xFF, value >> 8

    def _update_ops(self):
        ops = [("erase", SLOT)]
        for i in range(0, len(NEW_IMAGE), 2):
            ops.append(("program", SLOT + i, NEW_IMAGE[i] | (NEW_IMAGE[i + 1] << 8)))
        ops.append(("program", MARKER, 0))
        if self.opt["nondeterministic"] and self.runs > 1:
            ops[1] = ("program", SLOT, 0x7777)
        return ops

    def _boot(self):
        """Run from reset until the update is done, a cut fires, or something breaks."""
        self.boot_pending = False
        if self.opt["hang_on_boot"] and self.was_cut:
            raise MachineHung("fake lock-up")
        pending = self._half(MARKER) not in (0x0000, 0xFFFF)
        if not pending or (self.opt["no_recovery"] and self.was_cut):
            return
        self.runs += 1
        for op in self._update_ops():
            kind, addr = op[0], op[1]
            if self.opt["fault_at"] == self.opcount:
                self.fault = (0x20005000, 0x08000100)
                self.halted = True
                return
            erase_hit = kind == "erase" and addr == self.cut_page
            if (self.opcount == self.cutpoint or erase_hit) and not self.cut:
                self.cut = (CUT_ERASE, addr) if kind == "erase" else (CUT_PROGRAM, 0)
                if kind == "program" and self.opt["lands_after"]:
                    self._put(addr, op[2])
                self.halted = self.was_cut = True
                return
            self.opcount += 1
            if kind == "erase":
                self.mem[addr - BASE:addr - BASE + PAGE] = b"\xFF" * PAGE
            else:
                self._put(addr, op[2])
            if self.tracing:
                entry = {"index": len(self.trace), "kind": kind, "addr": addr}
                if kind == "program":
                    entry["value"] = op[2]
                self.trace.append(entry)
        if self.opt["refuse"]:
            self.refused = (2, SLOT + 4)
        if self.opt["stray"]:
            self.stray = SLOT + 8

    # ---- the RenodeSession interface the runner uses -------------------------

    def dump_flash(self):
        return bytes(self.mem)

    def restore_flash(self, data):
        self.mem[:] = data
        self.was_cut = False
        self.refused = self.stray = None

    def power_cycle(self, settle=0):
        self.halted = False
        self.cut = None
        self.opcount = 0
        self.cutpoint = self.cut_page = NEVER
        self.fault = None
        self.boot_pending = True
        if settle:
            self.run_for(settle)

    def run_for(self, seconds):
        if self.boot_pending and not self.halted:
            self._boot()

    def flash_ops(self):
        return self.opcount

    def set_cut(self, opcount):
        self.cutpoint, self.cut = opcount, None

    def set_cut_on_erase(self, page):
        self.cut_page, self.cut = page, None

    def run_until_cut(self, limit, step=0.01):
        self.run_for(step)
        return self.cut is not None

    def cut_status(self):
        return (self.cut or (0, 0)) + (self.opcount,)

    def trace_start(self):
        self.tracing, self.trace = True, []

    def trace_stop(self):
        self.tracing = False
        return list(self.trace)

    def violations(self):
        return {"fault": self.fault, "refused": self.refused, "stray": self.stray}

    def flash_resync(self):
        pass

    def flash_mismatch(self, expected):
        for i, (a, b) in enumerate(zip(self.mem, expected, strict=True)):
            if a != b:
                return BASE + i
        return None

    def read_half(self, addr):
        return self._half(addr)

    def write_half(self, addr, value):
        self._put(addr, value)

    def read_bytes(self, addr, n):
        return bytes(self.mem[addr - BASE:addr - BASE + n])

    def restart(self):
        self.restarts += 1
        self.halted = False
        self.boot_pending = False
        self.opt["hang_on_boot"] = False        # a fresh emulator


class FakeDriver:
    update_on_boot = True

    def __init__(self, device):
        self.d = device

    def start_update(self):
        pass

    def alive(self):
        self.d.run_for(0.1)
        slot = self.d.read_bytes(SLOT, 16)
        return not self.d.halted and slot in (OLD_IMAGE, NEW_IMAGE)

    def check_recovered(self):
        if self.d.read_bytes(SLOT, 16) != NEW_IMAGE:
            return False, "running, but not the new image"
        return True, ""
