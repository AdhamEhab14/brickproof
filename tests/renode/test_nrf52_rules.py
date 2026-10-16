"""nRF52840 NVMC rules beyond the code area's words: the UICR (programs, ERASEUICR, ERASEALL),
partial erase (ERASEPAGEPARTIAL) and the ACL. Stores and reads have to be the CPU's own for
the model to see them, so those run a few instructions from RAM."""
import struct

from brickproof import trace as traces

ADAPTER = "nrf52.yaml"
NVMC = 0x4001E000
CONFIG, ERASEPAGE, ERASEALL = NVMC + 0x504, NVMC + 0x508, NVMC + 0x50C
ERASEUICR, PARTIAL, PARTIALCFG = NVMC + 0x514, NVMC + 0x518, NVMC + 0x51C
ACL0 = NVMC + 0x800
OPCOUNT, PROTECTED, READS = NVMC + 0x100, NVMC + 0x148, NVMC + 0x150
REN, WEN, EEN = 0, 1, 2
UICR = 0x10001000
PAGE = 0x1000
CODE = 0x20030000
STR_R1_R0, LDR_R2_R0 = 0x6001, 0x6802
# the code ends spinning in nop + branch back. A single `b .` is a loop Renode stops
# translating, and the CPU then never takes a new PC from the monitor.
LOOP = (0xBF00, 0xE7FD)
_next_code = [CODE]


def run(chip, code, **regs):
    """Put `code` (Thumb halfwords) in fresh RAM and run it from there for a moment."""
    at = _next_code[0]
    _next_code[0] += 0x100
    words = b"".join(struct.pack("<H", h) for h in code) + b"\0\0"
    chip.cmd_batch(["sysbus WriteDoubleWord 0x%X 0x%X" % (at + i, struct.unpack_from("<I", words, i)[0])
                    for i in range(0, len(words) - 2, 4)]
                   + ["sysbus.cpu SetRegisterUnsafe %d 0x%X" % (int(r[1:]), v) for r, v in regs.items()]
                   + ["sysbus.cpu PC 0x%X" % at])
    chip.run_for(0.001)


def store(chip, addr, value):
    run(chip, [STR_R1_R0, *LOOP], r0=addr, r1=value)


def fresh(chip):
    """The device as shipped, after a reset (the ACL is cleared by one)."""
    chip.restore_flash(chip.factory)
    chip.power_cycle(settle=0.05)


def config(chip, wen):
    chip.write_word(CONFIG, wen)


def test_uicr_words_are_programmed_and_erased(chip):
    fresh(chip)
    config(chip, WEN)
    before = chip.read_word(OPCOUNT)
    store(chip, UICR + 0x080, 0x12345678)          # CUSTOMER[0]
    assert chip.read_word(UICR + 0x080) == 0x12345678
    assert chip.read_word(OPCOUNT) == before + 1
    store(chip, UICR + 0x080, 0xFFFFFFFF)          # cannot set bits back
    assert chip.read_word(UICR + 0x080) == 0x12345678
    config(chip, EEN)
    chip.write_word(ERASEUICR, 1)
    assert chip.read_word(UICR + 0x080) == 0xFFFFFFFF
    config(chip, REN)
    # and the UICR is in the flash image, after the code area
    f = chip.adapter.flash
    assert chip.dump_flash()[f.size + 0x080:f.size + 0x084] == b"\xFF" * 4


def test_eraseall_erases_the_uicr_too(chip):
    fresh(chip)
    config(chip, WEN)
    store(chip, UICR + 0x304, 5)                    # REGOUT0
    config(chip, EEN)
    chip.write_word(ERASEALL, 1)
    config(chip, REN)
    assert chip.read_word(UICR + 0x304) == 0xFFFFFFFF
    assert chip.read_word(0x0) == 0xFFFFFFFF


def test_partial_erases_match_the_trace_and_add_up_to_a_page_erase(chip):
    fresh(chip)
    page = bytes(chip.read_bytes(0x0, PAGE))       # the bootloader's first page: mostly not 0xFF
    config(chip, EEN)
    chip.write_word(PARTIALCFG, 10)
    for step in range(1, 9):
        chip.write_word(PARTIAL, 0x0)
        if step in (1, 4, 8):
            assert bytes(chip.read_bytes(0x0, PAGE)) == traces.partially_erased(page, 10000 * step)
    assert bytes(chip.read_bytes(0x0, PAGE)) != b"\xFF" * PAGE      # 80 ms: not yet
    chip.write_word(PARTIAL, 0x0)
    assert bytes(chip.read_bytes(0x0, PAGE)) == b"\xFF" * PAGE      # 90 ms
    config(chip, REN)


def test_an_acl_region_blocks_writes_and_erases(chip):
    fresh(chip)
    target = 0xF0000
    chip.write_word(ACL0 + 0x0, target)
    chip.write_word(ACL0 + 0x4, PAGE)
    chip.write_word(ACL0 + 0x8, 2)                  # WRITE disabled
    chip.write_word(ACL0 + 0x8, 0)                  # written once: this changes nothing
    assert chip.read_word(ACL0 + 0x8) == 2
    config(chip, WEN)
    store(chip, target, 0)
    assert chip.read_word(target) == 0xFFFFFFFF
    assert chip.read_word(PROTECTED) == 1
    store(chip, target + PAGE, 0)                   # the next page is not in the region
    assert chip.read_word(target + PAGE) == 0
    config(chip, EEN)
    chip.write_word(ERASEPAGE, target + PAGE)
    assert chip.read_word(target + PAGE) == 0xFFFFFFFF
    chip.write_word(ACL0 + 0x10, target + PAGE)     # region 1 over the next page
    chip.write_word(ACL0 + 0x14, PAGE)
    chip.write_word(ACL0 + 0x18, 2)
    config(chip, WEN)
    store(chip, target + PAGE, 0)
    config(chip, EEN)
    chip.write_word(ERASEPAGE, target + PAGE)
    assert chip.read_word(target + PAGE) == 0xFFFFFFFF    # the store was blocked
    assert chip.read_word(PROTECTED) == 3                  # and so was the erase
    config(chip, REN)


def test_an_acl_region_without_read_permission_reports_reads(chip):
    fresh(chip)
    chip.write_word(ACL0 + 0x0, 0x10000)
    chip.write_word(ACL0 + 0x4, PAGE)
    chip.write_word(ACL0 + 0x8, 4)                  # READ disabled
    run(chip, [LDR_R2_R0, *LOOP], r0=0x10010)
    assert chip.read_word(READS) == 1
    assert chip.read_word(READS + 4) == 0x10010
    fresh(chip)                                     # a reset clears the ACL
    assert chip.read_word(ACL0 + 0x8) == 0


def test_system_off_loses_ram_and_wakes_through_a_reset(chip):
    fresh(chip)
    chip.write_word(0x2003F000, 0x12345678)                    # something in RAM
    store(chip, 0x40000500, 1)                                  # SYSTEMOFF
    assert chip.read_word(0x2003F000) == 0                      # RAM lost power
    assert "True" in chip.cmd("sysbus.cpu IsHalted")            # off
    chip.run_for(chip.adapter.wake_after + 0.1)
    assert "False" in chip.cmd("sysbus.cpu IsHalted")           # woken, through a reset
