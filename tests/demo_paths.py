"""Where the demo's files are: its adapters in one folder per chip, its firmware in another."""
import glob
import os

DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "examples", "demo_ab_bootloader")
FIRMWARE = os.path.join(DEMO, "firmware")
CHIPS = ("f103", "f411", "l476", "nrf52", "h563")


def chip_of(name):
    """The folder a demo build is in: f411-bug-no_erase is in f411/, bug-no_erase in f103/."""
    for chip in CHIPS[1:]:
        if name == chip or name.startswith(chip + "-"):
            return chip
    return "f103"


def demo_adapter(name):
    return os.path.join(DEMO, chip_of(name), name + ".yaml")


def all_demo_adapters():
    return sorted(p for p in glob.glob(os.path.join(DEMO, "*", "*.yaml"))
                  if os.path.basename(p)[0] != "_")
