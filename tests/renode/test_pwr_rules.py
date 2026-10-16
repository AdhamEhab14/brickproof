"""STM32 low-power modes (models/stm32_pwr.py), on the F1 demo: Standby loses RAM and wakes
through a reset with SBF set; with nRST_STDBY cleared, entering Standby resets at once and RAM
is kept. The WFI has to be the core's own, so the tests run a few instructions from RAM."""
import struct

ADAPTER = "adapter.yaml"
PWR_CR, PWR_CSR, SCB_SCR = 0x40007000, 0x40007004, 0xE000ED10
PDDS, SLEEPDEEP, SBF = 2, 4, 2
SENTINEL = 0x20004F00
STR_R1_R0, STR_R3_R2, WFI = 0x6001, 0x6013, 0xBF30
LOOP = (0xBF00, 0xE7FD)
_next = [0x20003000]


def run(chip, code, **regs):
    at = _next[0]
    _next[0] += 0x40
    words = b"".join(struct.pack("<H", h) for h in code) + b"\0\0"
    chip.cmd_batch(["sysbus WriteDoubleWord 0x%X 0x%X" % (at + i, struct.unpack_from("<I", words, i)[0])
                    for i in range(0, len(words) - 2, 4)]
                   + ["sysbus.cpu SetRegisterUnsafe %d 0x%X" % (int(r[1:]), v) for r, v in regs.items()]
                   + ["sysbus.cpu PC 0x%X" % at])
    chip.run_for(0.001)


def boot(chip, user=0xFF):
    f = chip.adapter.flash
    image = bytearray(chip.factory)
    image[f.size + 2:f.size + 4] = bytes([user, user ^ 0xFF])     # USER and its complement
    chip.restore_flash(bytes(image))
    chip.power_cycle(settle=0.05)
    chip.write_word(SENTINEL, 0x12345678)


def standby(chip):
    run(chip, [STR_R1_R0, STR_R3_R2, WFI, *LOOP], r0=PWR_CR, r1=PDDS, r2=SCB_SCR, r3=SLEEPDEEP)


def halted(chip):
    return "True" in chip.cmd("sysbus.cpu IsHalted")


def test_standby_loses_ram_and_wakes_through_a_reset(chip):
    boot(chip)
    standby(chip)
    assert chip.read_word(SENTINEL) == 0 and halted(chip)
    chip.run_for(chip.adapter.wake_after + 0.1)
    assert not halted(chip)
    assert chip.read_word(PWR_CSR) & SBF                       # it came from Standby


def test_with_nrst_stdby_cleared_standby_is_a_reset(chip):
    boot(chip, user=0xFB)                                      # nRST_STDBY (bit 2) cleared
    standby(chip)
    chip.run_for(0.05)
    assert chip.read_word(SENTINEL) == 0x12345678              # a reset keeps RAM
    assert not halted(chip) and not chip.read_word(PWR_CSR) & SBF


def test_a_power_cycle_clears_sbf(chip):
    boot(chip)
    standby(chip)
    chip.run_for(chip.adapter.wake_after + 0.1)
    assert chip.read_word(PWR_CSR) & SBF
    chip.power_cycle(settle=0.05)
    assert not chip.read_word(PWR_CSR) & SBF
