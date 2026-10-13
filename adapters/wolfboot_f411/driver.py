"""Driver for wolfBoot's swap update, with wolfBoot's own test application.

The new image is staged the way wolfBoot's library leaves it after
wolfBoot_update_trigger(): the signed image at the start of the UPDATE partition, and
at the very end of that partition the trailer, the magic "BOOT" with the state byte
IMG_STATE_UPDATING in front of it. On the next boot wolfBoot swaps the partitions.

The test application says which version it is right after start-up: a '*' and the
version as four bytes, most significant first. An even version also confirms itself
(wolfBoot_success). A version that has not confirmed is swapped back on the next boot.
"""
import os
import re

from brickproof.drivers.staged_slot import StagedSlot

MAGIC_TRAIL = b"BOOT"
IMG_STATE_UPDATING = 0x70


class WolfBootSwap(StagedSlot):
    def __init__(self, session, adapter):
        opt = dict(adapter.driver_options)
        self.partition_size = opt["partition_size"]
        adapter.driver_options = dict(
            slot=opt["update_partition"], image=opt["image"],
            alive=r"\*\x00\x00\x00[\x01\x02]", boot_timeout=opt.get("boot_timeout", 30))
        StagedSlot.__init__(self, session, adapter)
        adapter.driver_options = opt
        # the whole UPDATE partition as the trigger leaves it
        with open(os.path.join(session.workdir, self.image), "rb") as f:
            image = f.read()
        blank = self.partition_size - len(image) - 5
        staged = image + b"\xFF" * blank + bytes([IMG_STATE_UPDATING]) + MAGIC_TRAIL
        with open(os.path.join(session.workdir, self.image), "wb") as f:
            f.write(staged)
        self.version_re = re.compile(r"\*\x00\x00\x00([\x01\x02])")

    def check_recovered(self):
        seen = self.version_re.findall(self.s.uart_text())
        return (True, "") if seen else (False, "the application never said its version")


def make_driver(session, adapter):
    return WolfBootSwap(session, adapter)
