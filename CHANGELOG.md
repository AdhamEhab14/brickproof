# Changelog

## Unreleased

**OpenBLT adapter.** `adapters/openblt_f103` runs OpenBLT's Nucleo-F103RB demo, reprogrammed
over the UART with its XCP protocol, and documents what it found there.

**wolfBoot adapter.** `adapters/wolfboot_f411` runs wolfBoot's Black Pill example and its test
application, and documents what it found there.

**Block protection in the external flash chip.** The status register's BP, TB, SEC and CMP bits
protect part of the chip as on a Winbond W25Q; an erase or program there is ignored by the chip
and fails the run. The status registers are part of the flash image, and
`external_flash.status` sets them as the device ships.

## 0.2.0

What changed after BrickProof was run on bootloaders that are not ours (wolfBoot and
OpenBLT). Everything here is something those runs showed was missing.

**External flash.** An SPI NOR flash chip beside the microcontroller (25-series commands,
single-line mode), set with `external_flash` in the adapter. Its page programs and erases are
counted, cut, torn and traced together with those of the internal flash, in the order they
really happen. Demo: `brickproof demo f411-ext`.

**Closer to the chip**
- Flash is also at address 0, where an STM32 that boots from it mirrors it. Firmware that
  programs through that address used to write nowhere.
- Timers and the SysTick count with the clock the firmware configures (source, PLL,
  prescalers). `clock: {hse: ...}` gives the board's crystal. The STM32F411 gets an RCC model
  of ours in place of Renode's.
- `pins: {PC13: high}` holds an input at a level, for buttons and straps that firmware reads
  at start-up.

**Judging**
- The oracle accepts approved images side by side at different addresses, a bootloader and
  the program it starts. A bootloader that reprograms in place can now be judged: after a cut
  the bootloader must be intact and running.

**Running**
- A locked-up device is reported after about a second of waiting, not after the allowance
  for the whole update.

## 0.1.0

First release.

**What it does.** Runs a firmware update in the Renode emulator, cuts power during it, powers
the device back up, and checks that it recovered.

**Where it cuts**
- A golden run traces every flash operation of the update (`brickproof trace`).
- Cuts are placed only at distinct flash states: after a power loss only flash is left, so two
  cuts that leave the same flash are the same test. `plan: every` cuts all of them,
  `plan: phases` samples long phases and says so in the report.
- Each cut lands exactly before its operation, and the emulated flash is compared byte for
  byte with what the golden run predicts for that point.
- Torn operations (`--torn`): an erase or a program left half done, in shapes that follow what
  flash cells do.
- Cuts during recovery (`--depth 2`): a second power loss while the device recovers from the first.
- Several emulators side by side (`--jobs`), with results that do not depend on how many.

**How it judges**
- An oracle outside the firmware: the installed bytes must be exactly an approved image, and
  the CPU must be running inside it, not in a fault handler.
- The chip's rules, which a plain emulator does not have: real RAM and flash sizes, a bus fault
  for memory that is not there, erase before program, stores ignored unless programming
  mode is on, write protection, option bytes
  (including the mass erase when read protection is removed), how long erases and
  programs take, during which the CPU stands still, a hardware watchdog set in the option
  bytes, and a proper reboot after a reset the firmware or a watchdog causes.
- The firmware's own signs of life, through the adapter's driver.

**What you get**
- JSON, JUnit and HTML reports; the HTML one lists each failure with a command that reproduces
  it, the firmware hashes, and where the evidence fits in UN R156 and the EU Cyber Resilience Act.
- A bundled demo (`brickproof demo`): a small A/B bootloader and a dozen builds with a known bug,
  each of which a run catches. The same demo builds for the STM32F411 (`brickproof demo f411`).
- What the update costs the flash: time spent erasing and programming, and the most-erased
  page or sector against the datasheet's endurance.
- A GitHub Action and a Docker image.

**Supported chips.** STM32F1 (pages, halfword programming) and STM32F411 (sectors, byte to
double-word programming, option bytes through OPTCR).

**Not modelled yet.** Torn-operation shapes are a model until compared with real hardware.
Flash timing uses datasheet figures, not measurements. Low-power modes.
