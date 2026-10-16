"""STM32L476 flash rules (RM0351): double-word programs and their errors (SIZERR, PGAERR,
PROGERR, PGSERR), page erase in either bank, and ECC: a read of a double word whose ECC
does not match sets ECCD and raises an NMI. Stores and reads have to be the CPU's own for
the model to see them, so those run a few instructions from RAM."""
import struct

from brickproof.engine import session as sessions

ADAPTER = "l476.yaml"
FLASH = 0x40022000
KEYR, SR, CR, ECCR = FLASH + 0x08, FLASH + 0x10, FLASH + 0x14, FLASH + 0x18
OPCOUNT, REFUSED, ECC_READS, ECC_AT = FLASH + 0x100, FLASH + 0x12C, FLASH + 0x158, FLASH + 0x15C
PG, PER, BKER, STRT = 1, 2, 1 << 11, 1 << 16
SIZERR, PGAERR, PROGERR, PGSERR = 0x40, 0x20, 0x08, 0x80
FREE = 0x08060000                       # page 192: erased in the demo image
BANK2 = 0x08080000
STR_R1_R0, STR_R2_R0_4, STRH_R1_R0, LDR_R2_R0 = 0x6001, 0x6042, 0x8001, 0x6802
LOOP = (0xBF00, 0xE7FD)                 # nop and back: a single `b .` keeps Renode from moving on
CODE = 0x20010000
_next = [CODE]


def run(chip, code, **regs):
    at = _next[0]
    _next[0] += 0x100
    words = b"".join(struct.pack("<H", h) for h in code) + b"\0\0"
    chip.cmd_batch(["sysbus WriteDoubleWord 0x%X 0x%X" % (at + i, struct.unpack_from("<I", words, i)[0])
                    for i in range(0, len(words) - 2, 4)]
                   + ["sysbus.cpu SetRegisterUnsafe %d 0x%X" % (int(r[1:]), v) for r, v in regs.items()]
                   + ["sysbus.cpu PC 0x%X" % at])
    chip.run_for(0.001)


def fresh(chip):
    chip.restore_flash(chip.factory)
    chip.power_cycle(settle=0.05)
    chip.cmd_batch(["sysbus WriteDoubleWord 0x%X 0x45670123" % KEYR,
                    "sysbus WriteDoubleWord 0x%X 0xCDEF89AB" % KEYR,
                    "sysbus WriteDoubleWord 0x%X 0xC3FB" % SR])


def program(chip, addr, low, high):
    chip.write_word(CR, PG)
    run(chip, [STR_R1_R0, STR_R2_R0_4, *LOOP], r0=addr, r1=low, r2=high)
    chip.write_word(CR, 0)


def test_a_double_word_is_two_stores_and_one_operation(chip):
    fresh(chip)
    before = chip.read_word(OPCOUNT)
    program(chip, FREE, 0x11111111, 0x22222222)
    assert (chip.read_word(FREE), chip.read_word(FREE + 4)) == (0x11111111, 0x22222222)
    assert chip.read_word(OPCOUNT) == before + 1


def test_the_program_errors(chip):
    fresh(chip)
    chip.write_word(CR, PG)
    run(chip, [STRH_R1_R0, *LOOP], r0=FREE, r1=0x1234)            # not 32 bits wide
    assert chip.read_word(SR) & SIZERR and chip.read_word(FREE) == 0xFFFFFFFF
    run(chip, [STR_R1_R0, *LOOP], r0=FREE + 0x10, r1=0)             # an error still set
    assert chip.read_word(SR) & PGSERR
    chip.write_word(SR, 0xC3FB)
    run(chip, [STR_R1_R0, *LOOP], r0=FREE + 4, r1=0)                # first word off the boundary
    assert chip.read_word(SR) & PGAERR
    chip.write_word(SR, 0xC3FB)
    chip.write_word(CR, 0)
    program(chip, FREE + 0x20, 0x0F0F0F0F, 0)
    program(chip, FREE + 0x20, 0x0F0F0000, 0)                       # not erased
    assert chip.read_word(SR) & PROGERR and chip.read_word(FREE + 0x20) == 0x0F0F0F0F
    chip.write_word(SR, 0xC3FB)
    program(chip, FREE + 0x20, 0, 0)                                # all zeros: allowed
    assert chip.read_word(FREE + 0x20) == 0 and not chip.read_word(SR) & 0xFF


def test_a_page_erase_in_either_bank(chip):
    fresh(chip)
    program(chip, FREE, 0, 0)
    program(chip, BANK2 + 0x800, 0, 0)
    chip.write_word(CR, PER | ((FREE - 0x08000000) // 0x800) << 3)
    chip.write_word(CR, chip.read_word(CR) | STRT)
    assert chip.read_word(FREE) == 0xFFFFFFFF
    assert chip.read_word(BANK2 + 0x800) == 0
    chip.write_word(CR, PER | BKER | (1 << 3))                      # bank 2, page 1
    chip.write_word(CR, chip.read_word(CR) | STRT)
    assert chip.read_word(BANK2 + 0x800) == 0xFFFFFFFF


def test_a_read_of_a_broken_double_word_is_an_ecc_error(chip):
    f = chip.adapter.flash
    image = bytearray(chip.factory)
    at = FREE + 0x40 - f.base
    image[at:at + 8] = bytes([0x5A] * 4 + [0] * 4)
    image[f.ecc_offset + at // 8] = 1                               # its ECC is wrong
    chip.restore_flash(bytes(image))
    chip.power_cycle(settle=0.05)
    assert chip.read_word(FLASH + sessions.REG_ECC_BROKEN) == 1
    run(chip, [LDR_R2_R0, *LOOP], r0=FREE + 0x44)
    assert chip.read_word(ECC_READS) == 1 and chip.read_word(ECC_AT) == FREE + 0x44
    eccr = chip.read_word(ECCR)
    assert eccr >> 31 and eccr & 0x7FFFF == FREE + 0x44 - f.base   # ECCD, and where
    chip.write_word(ECCR, 1 << 31)                                   # write 1 to clear
    assert not chip.read_word(ECCR) >> 31
    # an erase makes the double word sound again
    chip.write_word(KEYR, 0x45670123)
    chip.write_word(KEYR, 0xCDEF89AB)
    chip.write_word(CR, PER | (at // 0x800) << 3)
    chip.write_word(CR, chip.read_word(CR) | STRT)
    assert chip.read_word(FLASH + sessions.REG_ECC_BROKEN) == 0
