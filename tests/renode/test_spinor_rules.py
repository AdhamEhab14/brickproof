"""The external SPI NOR chip's protection rules (W25Q16JV): /WP and SRP, SRL, volatile
status writes, individual block locks. Commands go straight to the chip through the monitor."""
import re

ADAPTER = "f411-ext.yaml"
CHIP = "sysbus.spi1.extflash"
WREN, RDSR1, RDSR2, RDSR3, WRSR1, WRSR2, WRSR3 = 0x06, 0x05, 0x35, 0x15, 0x01, 0x31, 0x11
VOLATILE, PROGRAM, READ = 0x50, 0x02, 0x03
LOCK, UNLOCK, READ_LOCK, GLOBAL_LOCK, GLOBAL_UNLOCK = 0x36, 0x39, 0x3D, 0x7E, 0x98


def command(chip, *data):
    """One command: chip select low, the bytes, chip select high. Returns what the chip sent
    back for each byte."""
    out = []
    chip.cmd("%s OnGPIO 0 false" % CHIP)
    for b in data:
        reply = chip.cmd("%s Transmit 0x%X" % (CHIP, b))
        out.append(int(re.findall(r"^\s*(0x[0-9A-Fa-f]+|\d+)\s*$", reply, re.M)[-1], 0))
    chip.cmd("%s OnGPIO 0 true" % CHIP)
    return out


def addr(a):
    return [(a >> 16) & 0xFF, (a >> 8) & 0xFF, a & 0xFF]


def status(chip, which=RDSR1):
    return command(chip, which, 0)[1]


def byte_at(chip, a):
    return command(chip, READ, *addr(a), 0)[4]


def fresh(chip, stored=0):
    chip.cmd("%s SetStatus 0x%X" % (CHIP, stored))     # what is stored, and a power-up
    chip.cmd("%s OnGPIO 1 true" % CHIP)                 # /WP high


def write_sr1(chip, value):
    command(chip, WREN)
    command(chip, WRSR1, value)


def test_srp_with_wp_low_refuses_status_writes(chip):
    fresh(chip)
    write_sr1(chip, 0x80)                               # SRP
    assert status(chip) == 0x80
    chip.cmd("%s OnGPIO 1 false" % CHIP)                # /WP low
    write_sr1(chip, 0x9C)
    assert status(chip) == 0x80                         # hardware protected
    chip.cmd("%s OnGPIO 1 true" % CHIP)
    write_sr1(chip, 0x9C)
    assert status(chip) == 0x9C


def test_srl_locks_the_status_until_the_next_power_cycle(chip):
    fresh(chip)
    command(chip, WREN)
    command(chip, WRSR2, 0x01)                          # SRL, with SRP clear
    assert status(chip, RDSR2) & 1
    write_sr1(chip, 0x1C)
    assert status(chip) == 0x00                         # locked
    chip.cmd("%s PowerCycle" % CHIP)
    assert status(chip, RDSR2) & 1 == 0
    write_sr1(chip, 0x1C)
    assert status(chip) == 0x1C


def test_a_volatile_status_write_holds_until_power_is_lost(chip):
    fresh(chip)
    command(chip, VOLATILE)
    command(chip, WRSR1, 0x1C)
    assert status(chip) == 0x1C                         # in force
    stored = int(re.findall(r"^\s*(0x[0-9A-Fa-f]+|\d+)\s*$", chip.cmd("%s GetStatus" % CHIP), re.M)[-1], 0)
    assert stored & 0xFF == 0                           # but not stored
    chip.cmd("%s PowerCycle" % CHIP)
    assert status(chip) == 0x00


def test_with_wps_every_block_is_locked_at_power_up(chip):
    fresh(chip, stored=0x04 << 16)                      # WPS in status register 3
    assert status(chip, RDSR3) & 0x04
    a = 0x20000
    assert command(chip, READ_LOCK, *addr(a), 0)[4] == 1
    before = byte_at(chip, a)
    command(chip, WREN)
    command(chip, PROGRAM, *addr(a), 0x00)
    assert byte_at(chip, a) == before                   # locked: not programmed
    command(chip, WREN)
    command(chip, UNLOCK, *addr(a))
    assert command(chip, READ_LOCK, *addr(a), 0)[4] == 0
    command(chip, WREN)
    command(chip, PROGRAM, *addr(a), 0x00)
    assert byte_at(chip, a) == 0x00
    command(chip, WREN)
    command(chip, LOCK, *addr(a))
    assert command(chip, READ_LOCK, *addr(a), 0)[4] == 1


def test_global_unlock_and_lock(chip):
    fresh(chip, stored=0x04 << 16)
    command(chip, WREN)
    command(chip, GLOBAL_UNLOCK)
    assert command(chip, READ_LOCK, *addr(0x0), 0)[4] == 0
    assert command(chip, READ_LOCK, *addr(0x30000), 0)[4] == 0
    command(chip, WREN)
    command(chip, GLOBAL_LOCK)
    assert command(chip, READ_LOCK, *addr(0x30000), 0)[4] == 1


def test_without_wps_the_block_locks_do_not_matter(chip):
    fresh(chip)                                         # WPS clear, BP clear: nothing protected
    a = 0x21000
    command(chip, WREN)
    command(chip, PROGRAM, *addr(a), 0x5A)
    assert byte_at(chip, a) == 0x5A


def test_a_chip_of_16_mb_or_less_has_no_4_byte_commands(chip):
    fresh(chip)
    a = 0x22000
    command(chip, 0xB7)                                 # enter 4-byte mode: not on this chip
    command(chip, WREN)
    command(chip, PROGRAM, *addr(a), 0x66)
    assert byte_at(chip, a) == 0x66                     # still three address bytes
    assert command(chip, 0x13, 0, *addr(a), 0)[5] == 0  # 13h is not a read here
