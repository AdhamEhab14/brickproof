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
ram: {size: 0x5000}
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
    assert ad.cuts == [] and ad.plan == {"mode": "phases", "per_phase": 4}
    assert ad.oracle["accept"] == ["old_fbl", "new_fbl"] and ad.oracle["images"] == {}
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


DEMO = os.path.join(REPO, "examples", "demo_ab_bootloader")


def test_at_ops_expands_to_one_cut_per_operation(tmp_path):
    ad = adapters.load(write(tmp_path, "- at_ops: {from: 3, to: 9, step: 3}\n"))
    assert [(c.name, c.at_op, c.group) for c in ad.cuts] == [("op-3", 3, 0), ("op-6", 6, 0), ("op-9", 9, 0)]


@pytest.mark.parametrize("rng", ["{from: 5, to: 2}", "{from: 0}", "{from: 0, to: 4, step: 0}"])
def test_bad_ranges_are_rejected(tmp_path, rng):
    with pytest.raises(adapters.AdapterError, match="at_ops"):
        adapters.load(write(tmp_path, "- at_ops: %s\n" % rng))


def test_driver_needs_exactly_one_of_file_or_builtin(tmp_path):
    with pytest.raises(adapters.AdapterError, match="exactly one of file or builtin"):
        adapters.load(write(tmp_path, **{"{file: driver.py}": "{file: d.py, builtin: staged_slot}"}))


def test_demo_uses_the_builtin_driver():
    ad = adapters.load(os.path.join(DEMO, "adapter.yaml"))
    assert ad.driver_builtin == "staged_slot" and ad.driver_file is None
    assert ad.target == DEMO
    assert all(os.path.exists(f) for f, _ in ad.firmware), "prebuilt files are committed"


@pytest.mark.parametrize("bug", ["consume_first", "trust_header", "naive_floor", "pop_after_switch",
                                 "no_erase", "no_unlock", "resume_copy"])
def test_bug_variants_extend_the_demo(bug):
    base = adapters.load(os.path.join(DEMO, "adapter.yaml"))
    ad = adapters.load(os.path.join(DEMO, "bug-%s.yaml" % bug))
    assert ad.firmware[0][0].endswith("bootloader_bug_%s.elf" % bug)
    assert ad.driver_options == base.driver_options      # merged from the parent
    assert ad.plan == base.plan == {"mode": "every"}


def test_extends_merges_mappings_and_replaces_lists(tmp_path):
    (tmp_path / "base.yaml").write_text(MINIMAL + "    - at_op: 1\n")
    child = tmp_path / "child.yaml"
    child.write_text("extends: base.yaml\nname: child\nflash: {page: 0x800}\n"
                     "scenario: {cuts: [{at_op: 7}]}\n")
    ad = adapters.load(str(child))
    assert ad.name == "child"
    assert ad.flash.page == 0x800 and ad.flash.size == 0x10000
    assert [c.at_op for c in ad.cuts] == [7]


def test_ram_size_is_required(tmp_path):
    with pytest.raises(adapters.AdapterError, match="ram"):
        adapters.load(write(tmp_path, **{"ram: {size: 0x5000}\n": ""}))
