"""The STM32L4 in the engine: its option bytes, and the ECC map at the end of a flash image
that a finished operation leaves sound and a torn one leaves broken."""
import pytest

from brickproof import adapter as adapters
from brickproof import torn
from brickproof import trace as traces
from brickproof.engine.session import FlashGeometry

BASE = 0x08000000
PAGE = 0x800
FLASH = FlashGeometry(base=BASE, size=8 * PAGE, page=PAGE, write_unit=8, ob_base=0x1FFF7800,
                      option_bytes=bytes(0x28), ecc=True, endurance=10000)
ECC = FLASH.ecc_offset


def image(data=0x00):
    return bytes([data]) * FLASH.size + bytes(0x28) + bytes(FLASH.ecc_size)


def test_the_ecc_map_ends_the_image():
    assert FLASH.ecc_size == FLASH.size // 8
    assert ECC == FLASH.size + 0x28 and FLASH.image_size == ECC + FLASH.ecc_size


def test_finished_operations_leave_the_ecc_sound():
    pre = bytearray(image())
    pre[ECC:ECC + FLASH.ecc_size] = bytes([1]) * FLASH.ecc_size        # everything broken
    ops = [{"index": 0, "kind": "erase", "addr": BASE + PAGE},
           {"index": 1, "kind": "program", "addr": BASE + 3 * PAGE + 8, "value": 0x1122, "size": 8}]
    out = traces.Replay(bytes(pre), ops, FLASH).at(2)
    dw = PAGE // 8
    assert out[ECC + dw:ECC + 2 * dw] == bytes(dw)                     # the erased page
    assert out[ECC + 3 * dw + 1] == 0 and out[ECC + 3 * dw] == 1       # the programmed double word only
    assert out[ECC] == 1


def test_a_torn_program_breaks_its_double_word():
    before = bytes([0xFF]) * FLASH.size + bytes(0x28) + bytes(FLASH.ecc_size)
    op = {"index": 4, "kind": "program", "addr": BASE + 0x10, "value": 0x0123456789ABCDEF, "size": 8}
    states = torn.states(op, before, FLASH)
    assert states
    for s in states:
        assert s.image[ECC + 2] == 1 and sum(s.image[ECC:]) == 1


def test_a_torn_erase_breaks_what_was_not_blank():
    page = bytearray([0xFF]) * PAGE
    page[0:8] = bytes(8)                       # one written double word, the rest blank
    before = bytes(PAGE) + bytes(page) + bytes([0xFF]) * (6 * PAGE) + bytes(0x28) + bytes(FLASH.ecc_size)
    op = {"index": 2, "kind": "erase", "addr": BASE + PAGE}
    states = torn.states(op, before, FLASH)
    assert states
    for s in states:
        broken = [i for i, b in enumerate(s.image[ECC:]) if b]
        assert broken == [PAGE // 8]           # only the double word that had data in it


def test_without_ecc_nothing_is_marked():
    plain = FlashGeometry(base=BASE, size=8 * PAGE, page=PAGE, write_unit=4)
    assert plain.ecc_size == 0 and plain.image_size == plain.size


MINIMAL = """
name: demo
target: fw
platform: {base: stm32l476}
flash: {base: 0x08000000, size: 0x100000, page: 0x800, write_unit: 8}
ram: {size: 0x18000}
firmware:
  - file: app.elf
driver: {file: driver.py}
"""


def load(tmp_path, extra=""):
    p = tmp_path / "adapter.yaml"
    p.write_text(MINIMAL.replace("write_unit: 8}", "write_unit: 8%s}" % extra))
    return adapters.load(str(p)).flash


def words(ob):
    return [int.from_bytes(ob[i:i + 4], "little") for i in range(0, len(ob), 4)]


def test_l476_option_bytes(tmp_path):
    f = load(tmp_path)
    w = words(f.option_bytes)
    assert len(f.option_bytes) == 0x28 and f.ecc and f.ob_base == 0x1FFF7800
    assert all(w[i] ^ w[i + 1] == 0xFFFFFFFF for i in range(0, 10, 2))      # each with its complement
    assert w[0] == 0xFFEFF8AA and w[6] == w[8] == 0xFF00FFFF               # level 0, no areas
    f = load(tmp_path, ", write_protected: [{from: 0x08000000, size: 0x4000}], "
                       "read_protected: true, hardware_watchdog: true")
    w = words(f.option_bytes)
    assert w[0] & 0xFF == 0xBB and not w[0] & (1 << 16)                     # level 1, hardware IWDG
    assert w[6] & 0xFF == 0 and (w[6] >> 16) & 0xFF == 7                    # pages 0 to 7


@pytest.mark.parametrize("extra, message", [
    (", write_protected: [{from: 0x08080000, size: 0x800}]", "bank 2"),
    (", pcrop: [{from: 0x08000000, size: 0x800}]", "pcrop"),
])
def test_l476_option_bytes_refuse_what_is_not_modelled(tmp_path, extra, message):
    with pytest.raises(adapters.AdapterError, match=message):
        load(tmp_path, extra)
