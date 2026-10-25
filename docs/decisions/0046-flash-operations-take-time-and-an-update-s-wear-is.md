# Flash operations take time, and an update's wear is counted

2026-10-11

**Timing.** Until now an erase or a program took no time at all in the emulator. On the chip
a page erase is 20 to 40 ms and a 128 KB sector erase is one to two seconds, and for all of
it the CPU stands still: it runs from flash, and flash cannot be read while it is being
erased or programmed. Anything that counts time through that (a watchdog, a timeout, a
tick-based retry) sees it on the board and did not see it here.

The flash models now skip that much virtual time when an operation starts (`cpu.SkipTime`,
measured: an erase made to cost 30 ms moved the next operation 30.09 ms later). The CPU
executes nothing in between, which is what the stall is. Skipping costs almost no host time,
unlike a busy loop on BSY, which would call into the Python model hundreds of thousands of
times per erase. BSY therefore never reads as set: by the time the firmware can look, the
operation is over. For code running from RAM that is a simplification (it could do other
work while BSY is set); for the wait loop every such driver has, it is the same thing.

Figures, from the datasheets (read 2026-10-11):
- STM32F103x8/xB, DS5319 table 28: 16-bit program 40 / 52.5 / 70 us (min / typ / max), page
  erase and mass erase 20 to 40 ms. No typical erase time is given; 30 ms is used.
- STM32F411xC/xE: word program 16 us typical, 100 max. Sector erase depends on the sector
  and on PSIZE; at 32 bits: 16 KB 250 / 500 ms, 64 KB 550 / 1100 ms, 128 KB 1 / 2 s
  (typ / max); slower at 16 and 8 bits. Mass erase 4 / 8 s.
- Rewriting the F4 option bytes has no figure. It is taken as one 16 KB erase. A guess.

`flash.timing` in the adapter picks `typical` (the default), `max` (the slowest the datasheet
allows, the one to use when the question is whether a watchdog survives) or `none`.

Checked against the one real measurement there is: the Three-Tier self-update takes "about
2 s" on the Nucleo board. The trace adds up to 2.3 s of flash time with typical figures
(40 erases, 20,480 programs). Same order, slightly high, as expected from a typical erase
time that is a midpoint and not a measurement.

What it found straight away: the F411 demo set PSIZE only when programming, so its first
erase ran at the reset value (8 bits) and took 400 ms where 250 would do. Fixed in the demo.
And adapters had time limits that only held because operations were free: the F411 demo's
`update_time: 0.5` is less than its two sector erases. The limits were raised, and a failed
baseline now says so when the flash operations alone take longer than `update_time`.

What it costs: a run now covers more virtual time, because a recovery that copies 40 KB
really is two seconds long. The Three-Tier adapter asked "are you alive?" once, 1.5 s after
power-up, which was after the recovery when flash was instant and is in the middle of it
now, so every cut in the copy failed in CI. The driver now asks up to four times. To keep
the extra virtual time from turning into round trips to the emulator, the three waits that
polled in fixed 10 to 50 ms steps (for a cut, for a boot banner, for a serial reply) now
double their step while nothing happens. Measured on one Three-Tier cut: 71 `RunFor` calls
for 9.3 virtual seconds. Saving up the 53 us skips of single programs and skipping a
millisecond at a time was tried and made no measurable difference, so it was dropped.

**Wear.** Each run reports the page or sector erased most often in one update, and what that
means against the endurance the datasheet promises (10,000 cycles on both chips). It is a
count from the golden trace, not a model of cells ageing: it tells you that a bootloader
erasing its metadata page six times per update will wear that page out six times sooner.

**Not modelled, still.** Cells do not get slower or weaker with use, and nothing here varies
with temperature or supply voltage.
