"""The I2C EEPROM model's rules (a 24C256: 32 KB, 64-byte pages): a write wraps inside its
page, a read goes on across pages, a word address with no stop is used by the next read,
and each write is an operation a power cut can fall on. Transfers go straight to the
model through the monitor, as the I2C controller would make them."""
import re

from brickproof.engine import session

ADAPTER = "f411-ee.yaml"
EE = "sysbus.i2c1.eeprom"


def write(chip, *data, stop=True):
    chip.cmd("%s Write [%s]" % (EE, ", ".join("0x%X" % b for b in data)))
    if stop:
        chip.cmd("%s FinishTransmission" % EE)


def read(chip, at, n):
    write(chip, at >> 8, at & 0xFF)
    reply = chip.cmd("%s Read %d" % (EE, n))
    return [int(t, 0) for t in re.findall(r"0x[0-9A-Fa-f]+", reply)][-n:]


def test_a_write_wraps_inside_its_page(chip):
    write(chip, 0x01, 0x3E, 0xA1, 0xA2, 0xA3, 0xA4)   # two bytes before the end of page 0x0100
    assert read(chip, 0x013E, 2) == [0xA1, 0xA2]
    assert read(chip, 0x0100, 2) == [0xA3, 0xA4]       # wrapped to the start of the page
    assert read(chip, 0x0140, 1) != [0xA3]             # not into the next page


def test_a_read_goes_on_across_pages(chip):
    write(chip, 0x02, 0x3F, 0x55)
    write(chip, 0x02, 0x40, 0x66)
    assert read(chip, 0x023F, 2) == [0x55, 0x66]


def test_a_word_address_without_a_stop_is_where_the_read_starts(chip):
    write(chip, 0x03, 0x00, 0x77)
    write(chip, 0x03, 0x00, stop=False)                 # a repeated start comes next
    reply = chip.cmd("%s Read 1" % EE)
    assert int(re.findall(r"0x[0-9A-Fa-f]+", reply)[-1], 0) == 0x77


def test_a_write_sets_bits_as_well_as_clearing_them(chip):
    write(chip, 0x04, 0x00, 0x00)
    write(chip, 0x04, 0x00, 0x5A)
    assert read(chip, 0x0400, 1) == [0x5A]


def test_every_write_is_an_operation_and_a_cut_stops_it(chip):
    before = chip.flash_ops()
    write(chip, 0x05, 0x00, 0x11)
    assert chip.flash_ops() == before + 1
    write(chip, 0x05, 0x00, 0x22)
    assert chip.flash_ops() == before + 2
    chip.set_cut(chip.flash_ops())
    write(chip, 0x05, 0x00, 0x33)                       # the power goes before this write
    assert chip.cut_fired()
    assert read(chip, 0x0500, 1) == [0x22]
    write(chip, 0x05, 0x00, 0x44)                       # and nothing after it happens
    assert read(chip, 0x0500, 1) == [0x22]
    chip.set_cut(session.NEVER)
