import os
import textwrap

import pytest

from brickproof import adapter as adapters

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THREE_TIER = os.path.join(REPO, "adapters", "three_tier_f103", "adapter.yaml")

MINIMAL = """
name: demo
target: fw
platform: {base: stm32f103}
flash: {base: 0x08000000, size: 0x10000, page: 0x400}
firmware:
  - file: app.elf
driver: {file: driver.py}
scenario:
  cuts:
"""


def write(tmp_path, cuts="", **replace):
    text = MINIMAL
    for k, v in replace.items():
        text = text.replace(k, v)
    p = tmp_path / "adapter.yaml"
    p.write_text(text + textwrap.indent(textwrap.dedent(cuts), "    "))
    return str(p)


def test_three_tier_adapter_loads():
    ad = adapters.load(THREE_TIER)
    assert ad.flash.page == 0x400 and ad.flash.size == 0x20000
    assert ad.cuts[0].on_erase == 0x08004000
    assert ad.cuts[0].expect == (1, 0x08004000)
    assert all(c.expect == (2, 0) for c in ad.cuts if c.at_op is not None)
    assert ad.firmware[0][0].endswith(os.path.join("build-test", "boot_manager.elf"))


def test_target_override_moves_firmware_paths(tmp_path):
    ad = adapters.load(THREE_TIER, target=str(tmp_path))
    assert ad.firmware[1][0] == os.path.join(str(tmp_path), "build-test", "fbl.elf")


def test_cut_names_default_from_their_position(tmp_path):
    ad = adapters.load(write(tmp_path, "- on_erase: 0x08004000\n- at_op: 12\n"))
    assert [c.name for c in ad.cuts] == ["erase-0x08004000", "op-12"]


@pytest.mark.parametrize("cut", ["- {}\n", "- {on_erase: 0x08004000, at_op: 3}\n"])
def test_a_cut_needs_exactly_one_position(tmp_path, cut):
    with pytest.raises(adapters.AdapterError, match="exactly one"):
        adapters.load(write(tmp_path, cut))


def test_unknown_platform_is_rejected(tmp_path):
    with pytest.raises(adapters.AdapterError, match="unknown"):
        adapters.load(write(tmp_path, **{"stm32f103": "nrf52840"}))


def test_raw_binary_needs_an_address(tmp_path):
    with pytest.raises(adapters.AdapterError, match="addr"):
        adapters.load(write(tmp_path, **{"app.elf": "app.bin"}))


def test_flash_size_must_be_whole_pages(tmp_path):
    with pytest.raises(adapters.AdapterError, match="whole number"):
        adapters.load(write(tmp_path, **{"0x10000": "0x10100"}))
