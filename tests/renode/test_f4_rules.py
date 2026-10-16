"""STM32F411 flash rules (RM0383): PGAERR, PCROP, RDP level 2. A store or a read has to be
the CPU's own for the model to see it, so the tests run a few instructions from RAM."""
import struct

ADAPTER = "f411.yaml"
FLASH = 0x40023C00
KEYR, OPTKEYR, SR, CR, OPTCR = FLASH + 0x04, FLASH + 0x08, FLASH + 0x0C, FLASH + 0x10, FLASH + 0x14
REFUSED, PROTECTED, PCROP_READS, PCROP_AT = FLASH + 0x12C, FLASH + 0x148, FLASH + 0x150, FLASH + 0x154
OB_BASE = 0x1FFFC000
SECTOR7 = 0x08060000            # 128 KB, erased in the demo image
CODE = 0x20010000               # RAM where the test instructions go
STR_R1_R0, LDR_R2_R0, LOOP = 0x6001, 0x6802, 0xE7FE


def halfword(half):
    return struct.pack("<HH", half, ~half & 0xFFFF) + b"\xFF" * 4


def option_bytes(rdp=0xAA, nwrp=0xFFF, sprmod=False):
    user = 0xEF
    return halfword((rdp << 8) | user) + halfword(0x7000 | (0 if sprmod else 0x8000) | nwrp)


def boot_with(chip, ob, patch=None):
    f = chip.adapter.flash
    image = bytearray(chip.factory)
    image[f.size:f.size + 16] = ob
    for addr, data in (patch or {}).items():
        image[addr - f.base:addr - f.base + len(data)] = data
    chip.restore_flash(bytes(image))
    chip.power_cycle(settle=0.05)


_next_code = [CODE]


def run(chip, code, **regs):
    """Put `code` (Thumb halfwords) in RAM and run it from there for a moment. Each call
    uses fresh RAM: Renode keeps running its translation of what was at an address."""
    at = _next_code[0]
    _next_code[0] += 0x100
    words = b"".join(struct.pack("<H", h) for h in code) + b"\0\0"
    chip.cmd_batch(["sysbus WriteDoubleWord 0x%X 0x%X" % (at + i, struct.unpack_from("<I", words, i)[0])
                    for i in range(0, len(words) - 2, 4)]
                   + ["sysbus.cpu SetRegisterUnsafe %d 0x%X" % (int(r[1:]), v) for r, v in regs.items()]
                   + ["sysbus.cpu PC 0x%X" % at])
    chip.run_for(0.001)


def unlock(chip, psize_bits=2):
    chip.cmd_batch(["sysbus WriteDoubleWord 0x%X 0x45670123" % KEYR,
                    "sysbus WriteDoubleWord 0x%X 0xCDEF89AB" % KEYR,
                    "sysbus WriteDoubleWord 0x%X 0x%X" % (CR, 1 | (psize_bits << 8))])   # PG, PSIZE


def test_a_word_inside_one_row_is_programmed(chip):
    boot_with(chip, option_bytes())
    unlock(chip)
    run(chip, [STR_R1_R0, LOOP], r0=SECTOR7 + 0x8, r1=0x12345678)
    assert chip.read_word(SECTOR7 + 0x8) == 0x12345678
    assert chip.read_word(SR) & 0x60 == 0 and chip.read_word(REFUSED) == 0


def test_a_word_across_a_16_byte_row_is_refused_with_pgaerr(chip):
    boot_with(chip, option_bytes())
    unlock(chip)
    run(chip, [STR_R1_R0, LOOP], r0=SECTOR7 + 0xE, r1=0x12345678)
    assert chip.read_word(SR) & 0x20                    # PGAERR
    assert chip.read_word(REFUSED) == 1
    assert chip.read_bytes(SECTOR7 + 0xC, 8) == b"\xFF" * 8


def test_proprietary_code_runs_but_cannot_be_read_as_data(chip):
    # sector 7 proprietary code, holding a loop to run
    boot_with(chip, option_bytes(nwrp=1 << 7, sprmod=True), {SECTOR7: struct.pack("<H", LOOP)})
    run(chip, [LDR_R2_R0, LOOP], r0=SECTOR7 + 0x100)
    reads = chip.read_word(PCROP_READS)
    assert reads >= 1 and chip.read_word(PCROP_AT) == SECTOR7 + 0x100
    assert chip.read_word(SR) & 0x100                   # RDERR
    chip.cmd("sysbus.cpu PC 0x%X" % SECTOR7)            # running it is fine: no more reads
    chip.run_for(0.001)
    assert chip.read_word(PCROP_READS) == reads and chip.pc() == SECTOR7


def test_proprietary_code_cannot_be_erased(chip):
    boot_with(chip, option_bytes(nwrp=1 << 7, sprmod=True), {SECTOR7: b"\x00" * 4})
    chip.cmd_batch(["sysbus WriteDoubleWord 0x%X 0x45670123" % KEYR,
                    "sysbus WriteDoubleWord 0x%X 0xCDEF89AB" % KEYR,
                    "sysbus WriteDoubleWord 0x%X 0x%X" % (CR, 2 | (7 << 3) | (2 << 8)),
                    "sysbus WriteDoubleWord 0x%X 0x%X" % (CR, 2 | (7 << 3) | (2 << 8) | (1 << 16))])
    assert chip.read_word(PROTECTED) == 1 and chip.read_word(SECTOR7) == 0


def test_without_sprmod_a_set_nwrp_bit_means_writable(chip):
    boot_with(chip, option_bytes(nwrp=0xFFF))
    unlock(chip)
    run(chip, [LDR_R2_R0, STR_R1_R0, LOOP], r0=SECTOR7 + 0x20, r1=0)
    assert chip.read_word(PCROP_READS) == 0 and chip.read_word(SECTOR7 + 0x20) == 0


def test_level_2_option_bytes_cannot_change(chip):
    boot_with(chip, option_bytes(rdp=0xCC))
    before = chip.read_bytes(OB_BASE, 16)
    optcr = chip.read_word(OPTCR)
    assert (optcr >> 8) & 0xFF == 0xCC
    chip.cmd_batch(["sysbus WriteDoubleWord 0x%X 0x08192A3B" % OPTKEYR,
                    "sysbus WriteDoubleWord 0x%X 0x4C5D6E7F" % OPTKEYR,
                    "sysbus WriteDoubleWord 0x%X 0x%X" % (OPTCR, (optcr & ~0xFF03) | (0xAA << 8)),
                    "sysbus WriteDoubleWord 0x%X 0x%X" % (OPTCR, (optcr & ~0xFF03) | (0xAA << 8) | 2)])
    assert chip.read_bytes(OB_BASE, 16) == before
