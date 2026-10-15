"""Driver for wolfBoot's swap update on the STM32H563, with the test application wolfBoot's
own emulator CI runs (test-app/emu-test-apps).

The new image is staged the way wolfBoot's library leaves it after
wolfBoot_update_trigger(): the signed image at the start of the UPDATE partition, and at
the very end of that partition the trailer, the magic "BOOT" with the state byte
IMG_STATE_UPDATING in front of it. On the next boot wolfBoot swaps the partitions.

The application prints "get_version=N" right after start-up. Version 4 also confirms
itself (wolfBoot_nsc_success) and stops; a version that has not confirmed is swapped
back on the next boot.
"""
import os
import re

from brickproof.drivers.staged_slot import StagedSlot

MAGIC_TRAIL = b"BOOT"
IMG_STATE_UPDATING = 0x70
VERSION = re.compile(r"get_version=([14])\b")


class WolfBootSwap(StagedSlot):
    def __init__(self, session, adapter):
        opt = dict(adapter.driver_options)
        self.partition_size = opt["partition_size"]
        adapter.driver_options = dict(
            slot=opt["update_partition"], image=opt["image"],
            alive=VERSION.pattern, boot_timeout=opt.get("boot_timeout", 10))
        StagedSlot.__init__(self, session, adapter)
        adapter.driver_options = opt
        # the whole UPDATE partition as the trigger leaves it
        with open(os.path.join(session.workdir, self.image), "rb") as f:
            image = f.read()
        blank = self.partition_size - len(image) - 5
        staged = image + b"\xFF" * blank + bytes([IMG_STATE_UPDATING]) + MAGIC_TRAIL
        with open(os.path.join(session.workdir, self.image), "wb") as f:
            f.write(staged)

    def check_recovered(self):
        seen = VERSION.findall(self.s.uart_text())
        return (True, "") if seen else (False, "the application never said its version")


def make_driver(session, adapter):
    return WolfBootSwap(session, adapter)
