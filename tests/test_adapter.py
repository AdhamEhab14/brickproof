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
        adapters.load(write(tmp_path, **{"stm32f103": "esp32"}))


NRF = {"stm32f103": "nrf52840",
       "base: 0x08000000, size: 0x10000, page: 0x400": "base: 0x0, size: 0x100000, page: 0x1000",
       "size: 0x5000": "size: 0x40000"}


def test_an_nrf52840_has_4kb_pages_words_and_its_uicr_for_option_bytes(tmp_path):
    f = adapters.load(write(tmp_path, **NRF)).flash
    assert (f.model, f.controller, f.page, f.write_unit) == ("nrf52_flash.py", 0x4001E000, 0x1000, 4)
    # the UICR comes after the code area in an image, erased as shipped, and ERASEALL wipes it
    assert f.ob_base == 0x10001000 and f.option_bytes == bytes([0xFF]) * 0x400
    assert f.image_size == 0x100000 + 0x400 and f.mass_erase_ob


def test_nrf52840_uicr_words_and_approtect(tmp_path):
    uicr = {"page: 0x1000}": "page: 0x1000, read_protected: true, uicr: {0x304: 5}}"}
    f = adapters.load(write(tmp_path, **dict(NRF, **uicr))).flash
    assert f.option_bytes[0x208:0x20C] == bytes([0x00, 0xFF, 0xFF, 0xFF])     # APPROTECT enabled
    assert f.option_bytes[0x304:0x308] == bytes([5, 0, 0, 0])                 # REGOUT0 3.3 V
    bad = {"page: 0x1000}": "page: 0x1000, uicr: {0x302: 5}}"}
    with pytest.raises(adapters.AdapterError, match="word offset"):
        adapters.load(write(tmp_path, **dict(NRF, **bad)))
    with pytest.raises(adapters.AdapterError, match="nRF52"):
        adapters.load(write(tmp_path, **{"page: 0x400}": "page: 0x400, uicr: {0x304: 5}}"}))


def test_an_nrf52840_has_no_stm32_option_bytes_to_protect_with(tmp_path):
    protect = {"page: 0x1000}": "page: 0x1000, write_protected: [{from: 0x0, size: 0x1000}]}"}
    p = write(tmp_path, **dict(NRF, **protect))
    with pytest.raises(adapters.AdapterError, match="STM32 option bytes"):
        adapters.load(p)


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
                                 "no_erase", "no_unlock", "resume_copy",
                                 "retry_limit", "self_lock"])
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


# ---- option bytes and write protection ------------------------------------------

def option_bytes(tmp_path, flash_extra=""):
    text = MINIMAL.replace("flash: {base: 0x08000000, size: 0x10000, page: 0x400}",
                           "flash: {base: 0x08000000, size: 0x20000, page: 0x400%s}" % flash_extra)
    p = tmp_path / "adapter.yaml"
    p.write_text(text)
    return adapters.load(str(p)).flash


def test_option_bytes_default_to_an_unprotected_chip(tmp_path):
    f = option_bytes(tmp_path)
    assert f.ob_base == 0x1FFFF800 and f.ob_size == 16 and f.image_size == 0x20000 + 16
    assert f.option_bytes == bytes([0xA5, 0x5A, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00,
                                    0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00])


def test_write_protected_ranges_clear_their_wrp_bits(tmp_path):
    f = option_bytes(tmp_path, ", write_protected: [{from: 0x08000000, size: 0x2000}, "
                               "{from: 0x08008000, size: 0x1000}]")
    wrp = f.option_bytes[8] | f.option_bytes[10] << 8 | f.option_bytes[12] << 16 | f.option_bytes[14] << 24
    assert wrp == 0xFFFFFFFF & ~0b11 & ~(1 << 8)
    for i in range(0, 16, 2):
        assert f.option_bytes[i] ^ f.option_bytes[i + 1] == 0xFF, "each byte has its complement"


def test_read_protection_changes_the_rdp_byte(tmp_path):
    assert option_bytes(tmp_path, ", read_protected: true").option_bytes[0] != 0xA5


@pytest.mark.parametrize("ranges,text", [
    ("[{from: 0x08000400, size: 0x1000}]", "units of 0x1000"),
    ("[{from: 0x08000000, size: 0x0800}]", "units of 0x1000"),
    ("[{from: 0x08020000, size: 0x1000}]", "outside the flash"),
    ("[{from: 0x08000000}]", "size"),
])
def test_bad_write_protection_is_rejected(tmp_path, ranges, text):
    with pytest.raises(adapters.AdapterError, match=text):
        option_bytes(tmp_path, ", write_protected: %s" % ranges)


def test_the_demo_ships_with_its_bootloader_locked_and_one_variant_unlocked():
    wrp0 = adapters.load(os.path.join(DEMO, "adapter.yaml")).flash.option_bytes[8]
    assert wrp0 == 0xFC
    unlocked = adapters.load(os.path.join(DEMO, "bug-self_lock.yaml")).flash.option_bytes[8]
    assert unlocked == 0xFF


# ---- a chip that erases by sector (STM32F411) ---------------------------------

F411 = """
name: demo
target: fw
platform: {base: stm32f411}
flash: {base: 0x08000000, size: 0x80000, sectors: SECTORSEXTRA}
ram: {size: 0x20000}
firmware:
  - file: app.elf
driver: {file: driver.py}
"""
F411_SECTORS = "[0x4000, 0x4000, 0x4000, 0x4000, 0x10000, 0x20000, 0x20000, 0x20000]"


def f411(tmp_path, extra="", text=F411):
    p = tmp_path / "adapter.yaml"
    p.write_text(text.replace("SECTORS", F411_SECTORS).replace("EXTRA", extra))
    return adapters.load(str(p)).flash


def test_sectors_become_offsets_and_the_chip_sets_the_rest(tmp_path):
    f = f411(tmp_path)
    assert f.page is None and f.sectors[4] == (0x10000, 0x10000) and len(f.sectors) == 8
    assert f.unit_at(0x08044000) == (0x08040000, 0x20000)
    assert (f.controller, f.model, f.write_unit) == (0x40023C00, "stm32f4_flash.py", 4)
    assert f.ob_base == 0x1FFFC000


def test_f4_option_bytes_are_as_the_chip_shows_them(tmp_path):
    ob = f411(tmp_path).option_bytes
    # a fresh chip: RDP level 0 and the factory USER bits, nothing protected
    assert ob == bytes.fromhex("efaa1055ffffffff" "ffff0000ffffffff")
    locked = f411(tmp_path, ", write_protected: [{from: 0x08000000, size: 0x4000}, "
                            "{from: 0x08020000, size: 0x40000}]").option_bytes
    nwrp = locked[8] | locked[9] << 8
    assert nwrp == 0xFFFF & ~(1 << 0 | 1 << 5 | 1 << 6)
    assert (locked[10] | locked[11] << 8) == ~nwrp & 0xFFFF, "followed by its complement"
    assert f411(tmp_path, ", read_protected: true").option_bytes[1] != 0xAA


@pytest.mark.parametrize("extra, message", [
    (", write_protected: [{from: 0x08000000, size: 0x2000}]", "whole sectors"),
    (", write_protected: [{from: 0x08002000, size: 0x2000}]", "whole sectors"),
    (", write_protected: [{from: 0x08060000, size: 0x40000}]", "outside the flash"),
    (", page: 0x400", "exactly one of page"),
])
def test_bad_f4_flash_settings_are_rejected(tmp_path, extra, message):
    with pytest.raises(adapters.AdapterError, match=message):
        f411(tmp_path, extra)


def test_sectors_must_add_up_and_fit_the_chip(tmp_path):
    with pytest.raises(adapters.AdapterError, match="add up"):
        f411(tmp_path, text=F411.replace("SECTORS", "[0x4000, 0x4000]"))
    with pytest.raises(adapters.AdapterError, match="by sector"):
        f411(tmp_path, text=F411.replace("sectors: SECTORS", "page: 0x400"))
    with pytest.raises(adapters.AdapterError, match="by page"):
        f411(tmp_path, text=F411.replace("stm32f411", "stm32f103").replace("ram: {size: 0x20000}",
                                                                           "ram: {size: 0x5000}"))


def test_the_f411_demo_and_its_bug_builds_load():
    names = [n for n in os.listdir(DEMO) if n.startswith("f411") and n.endswith(".yaml")]
    assert len(names) == 18
    for n in names:
        ad = adapters.load(os.path.join(DEMO, n))
        assert ad.platform == "stm32f411" and ad.flash.sectors
        for path, _ in ad.firmware:
            assert os.path.exists(path), path


def test_flash_timing_is_typical_unless_the_adapter_says_otherwise(tmp_path):
    assert f411(tmp_path).timing == 1 and f411(tmp_path).endurance == 10000
    assert f411(tmp_path, ", timing: max").timing == 2
    assert f411(tmp_path, ", timing: none").timing == 0
    with pytest.raises(adapters.AdapterError, match="flash.timing"):
        f411(tmp_path, ", timing: fast")


def test_a_hardware_watchdog_clears_wdg_sw_in_the_user_byte(tmp_path):
    f1 = option_bytes(tmp_path, ", hardware_watchdog: true").option_bytes
    assert f1[2] == 0xFE and f1[3] == 0x01, "USER with bit 0 cleared, then its complement"
    assert option_bytes(tmp_path).option_bytes[2] == 0xFF
    f4 = f411(tmp_path, ", hardware_watchdog: true").option_bytes
    assert f4[0] == 0xCF and f4[2] == 0x30, "USER with bit 5 cleared, then its complement"
    assert f411(tmp_path).option_bytes[0] == 0xEF


def test_the_watchdog_demos_ship_with_a_hardware_watchdog():
    demos = (("watchdog.yaml", 0x01), ("f411-watchdog.yaml", 0x20), ("f411-bug-watchdog.yaml", 0x20))
    for name, bit in demos:
        ad = adapters.load(os.path.join(DEMO, name))
        user = ad.flash.option_bytes[2 if bit == 1 else 0]
        assert not user & bit, name


def test_pins_become_levels_held_after_every_reset(tmp_path):
    p = tmp_path / "adapter.yaml"
    p.write_text(MINIMAL + "pins: {PC13: high, pa0: low}\nreset: [\"cpu Step\"]\n")
    ad = adapters.load(str(p))
    assert ad.reset_cmds == ["gpioPortC OnGPIO 13 true", "gpioPortA OnGPIO 0 false", "cpu Step"]


@pytest.mark.parametrize("pins", ["{X13: high}", "{PC16: high}", "{PC13: up}", "{C13: low}"])
def test_bad_pins_are_rejected(tmp_path, pins):
    p = tmp_path / "adapter.yaml"
    p.write_text(MINIMAL + "pins: %s\n" % pins)
    with pytest.raises(adapters.AdapterError, match="pins"):
        adapters.load(str(p))


def test_the_crystal_is_8_mhz_unless_the_adapter_says_otherwise(tmp_path):
    p = tmp_path / "adapter.yaml"
    p.write_text(MINIMAL)
    assert adapters.load(str(p)).hse == 8000000
    p.write_text(MINIMAL + "clock: {hse: 25000000}\n")
    assert adapters.load(str(p)).hse == 25000000


def test_an_external_flash_chip_becomes_part_of_the_image(tmp_path):
    p = tmp_path / "adapter.yaml"
    p.write_text(MINIMAL + "external_flash: {bus: spi1, cs: pa4, size: 0x100000}\n")
    f = adapters.load(str(p)).flash
    assert (f.ext_bus, f.ext_cs, f.ext_size, f.ext_base) == ("spi1", "PA4", 0x100000, 0xA0000000)
    assert f.external(0xA0000000) and f.external(0xA00FFFFF) and not f.external(0xA0100000)
    # then its three status registers, which survive a power cut like the flash does
    assert f.image_size == f.size + f.ob_size + 0x100000 + 3
    assert f.ext_status == 0
    p.write_text(MINIMAL)
    assert not adapters.load(str(p)).flash.external(0xA0000000)
    assert adapters.load(str(p)).flash.image_size == f.size + f.ob_size


def test_an_external_chip_can_ship_with_its_block_protection_set(tmp_path):
    p = tmp_path / "adapter.yaml"
    p.write_text(MINIMAL + "external_flash: {bus: spi1, cs: PA4, size: 0x100000, status: 0x24}\n")
    assert adapters.load(str(p)).flash.ext_status == 0x24
    p.write_text(MINIMAL + "external_flash: {bus: spi1, cs: PA4, size: 0x100000, status: 0x1000000}\n")
    with pytest.raises(adapters.AdapterError, match="status register 1"):
        adapters.load(str(p))
    p.write_text(MINIMAL + "external_flash: {bus: spi1, cs: PA4, size: 0x100000, wp: PA3}\n")
    assert adapters.load(str(p)).flash.ext_wp == "PA3"
    p.write_text(MINIMAL + "external_flash: {bus: spi1, cs: PA4, size: 0x100000, wp: PA4}\n")
    with pytest.raises(adapters.AdapterError, match="same pin"):
        adapters.load(str(p))


@pytest.mark.parametrize("ext, message", [
    ("{bus: spi1, cs: A4, size: 0x100000}", "pin name"),
    ("{bus: spi1, cs: PA4, size: 0x100001}", "multiple of 4 KB"),
    ("{bus: spi1, cs: PA4, size: 0x8000000}", "up to 64 MB"),
    ("{bus: spi1, cs: PA4, size: 0x1000, address: 0x08000000}", "overlaps"),
    ("{cs: PA4, size: 0x1000}", "missing 'bus'"),
])
def test_bad_external_flash_settings_are_rejected(tmp_path, ext, message):
    p = tmp_path / "adapter.yaml"
    p.write_text(MINIMAL + "external_flash: %s\n" % ext)
    with pytest.raises(adapters.AdapterError, match=message):
        adapters.load(str(p))
