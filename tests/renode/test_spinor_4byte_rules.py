"""A SPI NOR chip over 16 MB (the W25Q256JV kind): 4-byte address mode, the 4-byte commands,
the extended address register, ADP at power-up and that chip's BP3-BP0 protection table.
The f411-ext demo with its chip made 32 MB; commands go straight to the chip."""
import re

CHIP = "sysbus.spi1.extflash"
WREN, RDSR1, RDSR3, WRSR1, WRSR3, READ, PROGRAM = 0x06, 0x05, 0x15, 0x01, 0x11, 0x03, 0x02


def command(chip, *data):
    """One command: chip select low, the bytes, chip select high (as in test_spinor_rules)."""
    out = []
    chip.cmd("%s OnGPIO 0 false" % CHIP)
    for b in data:
        reply = chip.cmd("%s Transmit 0x%X" % (CHIP, b))
        out.append(int(re.findall(r"^\s*(0x[0-9A-Fa-f]+|\d+)\s*$", reply, re.M)[-1], 0))
    chip.cmd("%s OnGPIO 0 true" % CHIP)
    return out


def status(chip, which=RDSR1):
    return command(chip, which, 0)[1]


ADAPTER = "f411-ext.yaml"
SIZE = 0x2000000


def ADJUST(ad):
    ad.flash.ext_size = SIZE


ENTER_4B, EXIT_4B, WREAR, RDEAR = 0xB7, 0xE9, 0xC5, 0xC8
READ4, PROGRAM4, ERASE4 = 0x13, 0x12, 0x21


def a4(a):
    return [(a >> 24) & 0xFF, (a >> 16) & 0xFF, (a >> 8) & 0xFF, a & 0xFF]


def a3(a):
    return [(a >> 16) & 0xFF, (a >> 8) & 0xFF, a & 0xFF]


def fresh(chip, stored=0):
    chip.cmd("%s SetStatus 0x%X" % (CHIP, stored))
    chip.cmd("%s OnGPIO 1 true" % CHIP)


def program4(chip, a, value):
    command(chip, WREN)
    command(chip, PROGRAM4, *a4(a), value)


def read4(chip, a):
    return command(chip, READ4, *a4(a), 0)[5]


def test_the_4_byte_commands_reach_above_16_mb(chip):
    fresh(chip)
    assert status(chip, RDSR3) & 1 == 0                 # 3-byte mode at power-up
    program4(chip, 0x01800010, 0x5A)
    assert read4(chip, 0x01800010) == 0x5A
    command(chip, WREN)
    command(chip, ERASE4, *a4(0x01800000))
    assert read4(chip, 0x01800010) == 0xFF


def test_4_byte_mode_makes_every_command_take_four_address_bytes(chip):
    fresh(chip)
    command(chip, ENTER_4B)
    assert status(chip, RDSR3) & 1                      # ADS
    command(chip, WREN)
    command(chip, PROGRAM, *a4(0x01900020), 0x33)
    assert command(chip, READ, *a4(0x01900020), 0)[5] == 0x33
    command(chip, EXIT_4B)
    assert status(chip, RDSR3) & 1 == 0
    assert read4(chip, 0x01900020) == 0x33


def test_the_extended_address_register_gives_the_top_byte_in_3_byte_mode(chip):
    fresh(chip)
    program4(chip, 0x01A00030, 0x44)
    command(chip, WREN)
    command(chip, WREAR, 0x01)
    assert command(chip, RDEAR, 0)[1] == 0x01
    assert command(chip, READ, *a3(0xA00030), 0)[4] == 0x44
    chip.cmd("%s PowerCycle" % CHIP)                    # the register is volatile
    assert command(chip, RDEAR, 0)[1] == 0x00


def test_adp_sets_4_byte_mode_at_power_up(chip):
    fresh(chip)
    command(chip, WREN)
    command(chip, WRSR3, 0x02)                          # ADP
    chip.cmd("%s PowerCycle" % CHIP)
    assert status(chip, RDSR3) & 0x03 == 0x03           # ADP stored, ADS set
    fresh(chip)


def test_the_bp3_bp0_table(chip):
    fresh(chip, stored=0x04)                            # BP = 1, TB = 0: the top 64 KB
    program4(chip, SIZE - 0x1000, 0x00)
    assert read4(chip, SIZE - 0x1000) == 0xFF           # protected
    program4(chip, SIZE - 0x20000, 0x00)
    assert read4(chip, SIZE - 0x20000) == 0x00          # the block below is not
    fresh(chip, stored=0x44)                            # TB: the bottom 64 KB instead
    program4(chip, 0x8000, 0x00)
    assert read4(chip, 0x8000) == 0xFF
    program4(chip, 0x20000, 0x00)
    assert read4(chip, 0x20000) == 0x00
    fresh(chip, stored=0x28)                            # BP = 10: all of it
    program4(chip, 0x01000000, 0x00)
    assert read4(chip, 0x01000000) == 0xFF
    fresh(chip)


def test_status_writes_still_work(chip):
    fresh(chip)
    command(chip, WREN)
    command(chip, WRSR1, 0x3C)
    assert status(chip) == 0x3C
    fresh(chip)
