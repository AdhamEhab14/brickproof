"""Driver for the Three-Tier secure bootloader's FBL self-update.

It uses the bootloader's own host tools (host/bl_host.py, host/sign_tool.py) from the
target repo, signed with the published TEST keys, so the firmware sees exactly the
bytes the real host would send.

The update: a new FBL is staged in Slot B, UPDATE_FBL hands over to a RAM-resident
SBL that erases the 40 KB FBL region and copies Slot B over it. If power fails, the
Boot Manager is expected to redo the copy on the next boot.
"""
import os
import struct
import subprocess
import sys

from brickproof.engine.session import RenodeSerial

FBL_BASE = 0x08004000
SLOT_B = 0x08015000
FBL_PAGES = 40


class ThreeTierFblUpdate:
    def __init__(self, session, adapter):
        self.s = session
        self.opt = adapter.driver_options
        root = adapter.target
        keys = os.path.join(root, "tests", "keys")
        if not os.path.exists(os.path.join(keys, "bl_private.bin")):
            subprocess.check_call([sys.executable, os.path.join(keys, "make_test_keys.py")])
        os.environ["BL_KEYS_DIR"] = keys          # read by sign_tool at import
        sys.path.insert(0, os.path.join(root, "host"))
        import bl_host
        import sign_tool
        self.bl, self.sign_tool = bl_host, sign_tool
        self.fbl_bin = os.path.join(root, self.opt.get("fbl_bin", "build-test/fbl.bin"))
        self.hdr = None
        with open(self.fbl_bin, "rb") as f:
            self.old_fbl = f.read()
        self.new_fbl = self.old_fbl + b"\xC3" * 16     # differs from the old one, still boots

    def _ser(self, timeout):
        self.s.rx.clear()
        return RenodeSerial(self.s, timeout=timeout)

    def prepare(self):
        """Sign a new FBL (the current one plus padding, so it differs but still boots)
        and stage it in Slot B. Runs once; every cut starts from the flash after this."""
        path = os.path.join(self.s.workdir, "fbl_new.bin")
        with open(path, "wb") as f:
            f.write(self.new_fbl)
        self.sign_tool.sign(path, self.opt.get("version", "2.1.0"), "fbl", False)
        self.hdr = open(path + ".hdr", "rb").read()

        ser = self._ser(5)
        ok, p = self.bl.transact(ser, self.bl.CMD_ERASE, struct.pack("<IB", SLOT_B, FBL_PAGES))
        if not self.bl.ok_reply(ok, p):
            raise RuntimeError("erase of Slot B failed")
        self.s.load_binary("fbl_new.bin", SLOT_B)

    def start_update(self):
        self._ser(5).write(self.bl.build_frame(self.bl.CMD_UPDATE_FBL, self.hdr))

    def alive(self):
        """The bootloader answers a version request."""
        ok, _ = self.bl.transact(self._ser(2), self.bl.CMD_GET_VER)
        return bool(ok)

    def oracle_images(self):
        """What may be in the FBL region: the FBL it shipped with, or the update."""
        return {"old_fbl": (self.old_fbl, FBL_BASE), "new_fbl": (self.new_fbl, FBL_BASE)}

    def check_recovered(self):
        """Nothing more to ask the firmware. Which FBL is installed, and whether it is
        really running, is the oracle's call: before the SBL starts the old one is the
        right answer, after it only the new one can be."""
        return True, ""


def make_driver(session, adapter):
    return ThreeTierFblUpdate(session, adapter)
