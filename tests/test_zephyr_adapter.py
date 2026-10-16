"""Adapters written from a Zephyr build match the ones written by hand."""
import os

import pytest

from brickproof import adapter as adapters
from brickproof import cli, zephyr_adapter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


@pytest.mark.parametrize("board", ["f411", "nrf52840"])
def test_the_generated_adapter_matches_the_hand_written_one(board, tmp_path):
    build = os.path.join(HERE, "fixtures", "zephyr", board)
    images = os.path.join(ROOT, "adapters", "mcuboot", "prebuilt", board)
    out = str(tmp_path / "adapter.yaml")
    assert cli.main(["adapter-from-zephyr", build, "--images", images, "-o", out]) == 0
    made = adapters.load(out)
    hand = adapters.load(os.path.join(ROOT, "adapters", "mcuboot", board + ".yaml"))
    for attr in ("platform", "uart", "ram_size", "hse", "update_time", "cut_limit", "plan"):
        assert getattr(made, attr) == getattr(hand, attr), attr
    for attr in ("base", "size", "page", "sectors", "write_unit"):
        assert getattr(made.flash, attr) == getattr(hand.flash, attr), attr
    assert [(os.path.basename(f), a) for f, a in made.firmware] == \
        [(os.path.basename(f), a) for f, a in hand.firmware]
    assert made.driver_builtin == hand.driver_builtin == "staged_slot"
    for key in ("slot", "image", "alive", "expect", "boot_timeout"):
        assert made.driver_options[key] == hand.driver_options[key], key
    assert made.oracle["accept"] == hand.oracle["accept"]
    assert {n: (os.path.basename(f), a) for n, (f, a) in made.oracle["images"].items()} == \
        {n: (os.path.basename(f), a) for n, (f, a) in hand.oracle["images"].items()}


def test_the_upgrade_mode_comes_from_mcuboot_s_kconfig():
    f411 = zephyr_adapter.describe(os.path.join(HERE, "fixtures", "zephyr", "f411"))
    nrf = zephyr_adapter.describe(os.path.join(HERE, "fixtures", "zephyr", "nrf52840"))
    assert f411["mode"] == "swap-scratch" and nrf["mode"] == "swap-move"
    assert f411["hse"] == 25000000 and nrf["hse"] is None


def test_an_unknown_chip_is_refused(tmp_path):
    (tmp_path / "zephyr").mkdir()
    (tmp_path / "zephyr" / "zephyr.dts").write_text("/dts-v1/;\n/ {\n};\n")
    (tmp_path / "zephyr" / ".config").write_text('CONFIG_SOC="esp32"\n')
    with pytest.raises(ValueError, match="CONFIG_SOC=esp32"):
        zephyr_adapter.describe(str(tmp_path))
