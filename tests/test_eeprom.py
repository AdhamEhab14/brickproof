"""An I2C EEPROM next to the flash: where it sits in an image, how a write cut short
looks, what it wears, and the adapter section that describes it."""
import pytest

from brickproof import adapter as adapters
from brickproof import torn
from brickproof import trace as traces
from brickproof.engine.session import EXT_STATUS_BYTES, FlashGeometry

PAGE = 0x400
EE = 0xB0000000
FLASH = FlashGeometry(base=0x08000000, size=0x4000, page=PAGE, endurance=10000,
                      eeprom_base=EE, eeprom_size=0x1000, eeprom_page=64, eeprom_endurance=1000000)


def test_the_eeprom_comes_last_in_the_image():
    assert FLASH.image_size == 0x4000 + 0x1000
    assert traces.locate(EE + 0x45, FLASH) == (0x4000 + 0x45, 64)
    with_ext = FlashGeometry(base=0x08000000, size=0x4000, page=PAGE, ext_base=0xA0000000,
                             ext_size=0x10000, eeprom_base=EE, eeprom_size=0x1000)
    assert with_ext.eeprom_offset == 0x4000 + 0x10000 + EXT_STATUS_BYTES
    assert with_ext.image_size == with_ext.eeprom_offset + 0x1000


def test_replay_writes_eeprom_bytes_whatever_was_there():
    # an EEPROM write is not an AND: 0x00 can become 0x5A
    pre = bytes([0xFF]) * 0x4000 + bytes(0x1000)
    ops = [{"index": 0, "kind": "program", "addr": EE + 8, "value": 0x5A5A, "size": 2}]
    image = traces.Replay(pre, ops, FLASH).at(1)
    assert image[0x4008:0x400A] == b"\x5A\x5A"


def test_a_torn_page_write_is_erased_part_way_or_written_part_way():
    before = bytes([0xFF]) * 0x4000 + bytes([0x11]) * 0x1000
    op = {"index": 3, "kind": "program", "addr": EE + 0x40, "value": 0x0102030405060708, "size": 8}
    new = op["value"].to_bytes(8, "little")
    states = {s.kind: s for s in torn.states(op, before, FLASH)}
    assert set(states) == set(torn.PAGE_KINDS)
    for s in states.values():
        assert s.image[0x4040:0x4048] != new
        assert s.image[:0x4040] == before[:0x4040] and s.image[0x4048:] == before[0x4048:]
    # erasing: only 0 bits of the old value turned to 1
    assert all(b & 0x11 == 0x11 for b in states["page-erasing"].image[0x4040:0x4048])
    assert states["page-erased"].image[0x4040:0x4048] == bytes([0xFF]) * 8
    # writing: from 0xFF, only bits the new value clears are cleared
    got = states["page-writing"].image[0x4040:0x4048]
    assert all(g & n == n for g, n in zip(got, new, strict=True))


def test_flash_shapes_are_not_used_on_the_eeprom():
    before = bytes([0xFF]) * 0x4000 + bytes(0x1000)
    op = {"index": 0, "kind": "program", "addr": EE, "value": 0x5A, "size": 1}
    # a flash program from 0x00 to 0x5A has no bits to clear, so it has no torn shape;
    # an EEPROM write does: the old 0x00 can come back as 0xFF
    kinds = [s.kind for s in torn.states(op, before, FLASH)]
    assert "page-erased" in kinds and set(kinds) <= set(torn.PAGE_KINDS)


def test_eeprom_wear_is_counted_per_page_against_its_own_endurance():
    ops = [{"index": i, "kind": "program", "addr": EE + 0x40 + 4 * i, "value": 0, "size": 4}
           for i in range(3)]
    c = traces.cost(ops, FLASH)
    assert c["most_erased"] == {"addr": EE + 0x40, "erases_per_update": 3}
    assert c["updates_to_wear_out"] == 1000000 // 3


MINIMAL = """
name: demo
target: fw
platform: {base: stm32f411}
flash:
  base: 0x08000000
  size: 0x80000
  sectors: [0x4000, 0x4000, 0x4000, 0x4000, 0x10000, 0x20000, 0x20000, 0x20000]
  write_unit: 4
ram: {size: 0x20000}
firmware:
  - file: app.elf
driver: {file: driver.py}
"""


def load(tmp_path, section):
    p = tmp_path / "adapter.yaml"
    p.write_text(MINIMAL + section)
    return adapters.load(str(p))


def test_the_adapter_section(tmp_path):
    f = load(tmp_path, "external_eeprom: {bus: i2c1, size: 0x8000, page: 64}\n").flash
    assert (f.eeprom_bus, f.eeprom_size, f.eeprom_page, f.eeprom_base) == ("i2c1", 0x8000, 64, 0xB0000000)
    assert (f.eeprom_i2c, f.eeprom_address_bytes, f.eeprom_endurance) == (0x50, 2, 1000000)
    small = load(tmp_path, "external_eeprom: {bus: i2c1, size: 256, page: 8}\n").flash
    assert small.eeprom_address_bytes == 1


@pytest.mark.parametrize("section, message", [
    ("{bus: i2c1, size: 0x7000}", "power of two"),
    ("{bus: i2c1, size: 0x20000}", "64 KB"),
    ("{bus: i2c1, size: 0x8000, page: 48}", "page"),
    ("{bus: i2c1, size: 0x8000, address_bytes: 1}", "address_bytes"),
    ("{bus: i2c1, size: 0x8000, i2c_address: 0x80}", "7-bit"),
    ("{bus: i2c1, size: 0x8000, address: 0x08000000}", "overlaps the internal flash"),
    ("{size: 0x8000}", "bus"),
])
def test_the_adapter_section_is_checked(tmp_path, section, message):
    with pytest.raises(adapters.AdapterError, match=message):
        load(tmp_path, "external_eeprom: %s\n" % section)
