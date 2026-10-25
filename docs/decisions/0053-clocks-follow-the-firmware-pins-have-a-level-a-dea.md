# Clocks follow the firmware, pins have a level, a dead device is noticed

2026-10-12

Three gaps the outside bootloaders showed, closed.

**Clocks.** Renode gives each timer a fixed input clock (10 MHz in its STM32 files) and its
RCC models do not tell anyone what the firmware configured. OpenBLT keeps time with TIM1
and a prescaler for the 72 MHz it sets up, so its 500 ms took 3.6 s. Both chips now have an
RCC model of ours that works the tree out from the registers (source, PLL, AHB and APB
prescalers, and the doubling of a timer clock on a divided bus) and sets the frequency of
the timers and the SysTick whenever the firmware changes it. The F411 gets a new model in
place of Renode's; the F103 had ours already, without the tree. The board adds one number,
`clock.hse`. Checked: OpenBLT passes with no clock line in its adapter, and wolfBoot's test
application, which runs a PLL from a 25 MHz crystal and a TIM2 interrupt, behaves as before.
UART baud rates are not derived from this: Renode passes bytes whatever the divisor says.

**Pins.** `pins: {PC13: high}` holds an input at a level after every reset. It does not model
pull-ups or a floating pin; it lets the adapter say what the board does.

**A dead device.** A locked-up core never returns from a run, and the allowance before the
engine gives up grows with the length of the run. One 30-second wait for an update meant up
to ten minutes before "locked up" was reported. Long waits are now made in one-second
slices, so the same verdict comes after one slice's allowance.
