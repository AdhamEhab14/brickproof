# Low-power modes (plan item 4)

2026-10-16

Renode takes every WFI as a light sleep: any interrupt ends it, and RAM is intact. On the
chip, WFI with SLEEPDEEP is Stop or Standby, and Standby loses RAM and ends in a reset. Both
ways the plain emulator is wrong for an update: firmware that pauses in Standby either sleeps
for ever (nothing wakes it: a false failure) or wakes with RAM it should have lost (a false
pass).

**STM32F1 and F4** (RM0008 and RM0383, PWR): a Python model at 0x40007000 (`stm32_pwr.py`,
the same address on both) with CR (LPDS, PDDS, CWUF, CSBF) and CSR (WUF, SBF, EWUP). It sees
the core enter WFI through Renode's WFI hook. SLEEPDEEP and PDDS: Standby, RAM zeroed, the
core stopped, and a wake WAKE_AFTER_US later through a reset with SBF and WUF set. SLEEPDEEP
alone: Stop, the SysTick held until the core leaves WFI (other timers keep counting in the
emulator, which they do not on the chip: a known gap). nRST_STDBY / nRST_STOP cleared in the
USER option byte (F1 bits 2 and 1, F4 bits 7 and 6): entering the mode resets at once, RAM
kept. SBF, WUF and PWR's CR live in the state memory, because the reset that ends Standby
reruns the model's script; CR is cleared by every reset and SBF by a power cycle, as a
power-on reset does, which also cancels a wake still to come. The hook is set up the first
time firmware touches PWR, which entering Standby or Stop always does.

**The wake** cannot come from what started it on the board (an RTC alarm, the WKUP pin, a
button), none of which a power-fail test drives, so the adapter says when:
`low_power.wake_after`, 0.5 s unless given.

**nRF52** (Product Specification, POWER): SYSTEMOFF powers the chip off, RAM is lost (RAM
retention not modelled), and a wake comes back through a reset. Renode's NRF_CLOCK owns that
register block, so this is a bus watchpoint on SYSTEMOFF (`nrf52_power.py`, included once
when the machine is made). RESETREAS is not modelled.

**Checked:** tests/renode/test_pwr_rules.py (Standby loses RAM and wakes with SBF set,
nRST_STDBY cleared turns it into a reset with RAM kept, a power cycle clears SBF) and the
nRF52 rule test for System OFF. The demo pauses an install once in Standby right after Slot A
is erased (`STANDBY_PAUSE`, F1 and F411) and asks SBF whether it already has; every cut and
torn state recovers. `BUG_STANDBY_RAM` keeps that in a RAM variable start-up leaves alone, so
every wake pauses again: it fails at the baseline. The same bug build without the PWR model
also fails, but because nothing ever wakes the core, and so would the correct build: the
model is what lets the correct one pass.
