# Changelog

## Unreleased

**External flash chips over 16 MB.** `external_flash.size` goes up to 64 MB. A chip over
16 MB has 4-byte addresses as on a W25Q256JV: 4-byte mode (B7h/E9h, ADP at power-up), the
4-byte commands, the extended address register, and its BP3-BP0 protection table.

**The nRF52's UICR, partial erase and ACL.** The UICR is part of the flash image: stores into
it are programs, ERASEUICR erases it and ERASEALL erases it with the code area, and
`read_protected` (APPROTECT) and `flash.uicr` set it as shipped. ERASEPAGEPARTIAL erases a
page once its steps add up to tERASEPAGE, leaving it part way until then. The ACL blocks
writes, erases and reads in its regions until reset, and a blocked access fails the run.

**An I2C EEPROM.** `external_eeprom` adds a 24-series EEPROM on an I2C controller. Its page
writes are operations a cut can fall on, with torn states of their own (part way through
the chip's erase or its write) and wear per page. The F411 demo keeps its rollback floor there in `f411-ee`, and
`f411-ee-bug-no_invalidate` rewrites a record without clearing its old magic first: every
clean cut passes it, and only the torn writes catch it.

**OpenBLT adapter.** `adapters/openblt_f103` runs OpenBLT's Nucleo-F103RB demo, reprogrammed
over the UART with its XCP protocol, and documents what it found there, and what the
maintainer's fix (r1326) still leaves: 4 cuts inside the boot block after its checksum.

**wolfBoot adapter.** `adapters/wolfboot_f411` runs wolfBoot's Black Pill example and its test
application, and documents what it found there. `adapter-custom-trailer.yaml` runs the fix
proposed in wolfBoot PR #940 (trailers in sectors of their own): 44 cuts, all recovered.

**Block protection in the external flash chip.** The status register's BP, TB, SEC and CMP bits
protect part of the chip as on a Winbond W25Q; an erase or program there is ignored by the chip
and fails the run. The status registers are part of the flash image, and
`external_flash.status` sets them as the device ships.

**MCUboot adapter.** `adapters/mcuboot` builds MCUboot and a test app for the Black Pill
(swap using scratch, 57 cuts) or the nRF52840 DK (swap using move, 156 cuts) and runs its
update; no failure on either.

**A third chip family: the nRF52840.** Its flash controller (NVMC) is modelled: 4 KB pages,
whole aligned 32-bit words, at most two writes to a word between erases (a third, or a
narrower store, fails the run), and the CPU stalls for the datasheet's times. BrickProof
writes out Renode's nRF52840 platform itself, so a run does not download anything.

**The demo on the nRF52840.** `brickproof demo nrf52` (98 cuts, every flash state) and nine
more builds: CONFIG held at Wen over a run of words, and eight with a known bug, including a
new one, `nwrite` (a third write to a word without an erase).

**The external flash chip's own protection.** As on a W25Q16JV: the /WP pin
(`external_flash.wp`) with SRP refuses status writes, SRL locks the status registers until the
next power cycle (or for good with SRP), 50h makes a status write volatile, and with WPS
(status register 3, now part of the chip's saved state) protection goes by individual block
locks (36h/39h/3Dh, 7Eh/98h), all set at power-up. A device power cycle power-cycles the chip.

**STM32F4: PGAERR, PCROP and read protection level 2.** A program whose data does not fit in
one 16-byte flash row is refused with PGAERR. `flash.pcrop` makes sectors proprietary code
(SPRMOD): they run, but cannot be erased, programmed or read as data, and such a read fails
the run. `read_protected: 2` is level 2, after which the option bytes cannot change.

**STM32F1 option bytes checked as the chip checks them.** At reset each option byte is
compared with its complement; where they do not match, FLASH_OBR's OPTERR is set and the
byte loads as 0xFF (so a damaged RDP byte means read protection, a damaged WRP byte none).
The flash models' chip rules now have tests that run in Renode (`tests/renode`, skipped
without Renode) and a CI job, `model-rules`.

**Adapters from a Zephyr build.** `brickproof adapter-from-zephyr <MCUboot build folder>
--images <folder>` writes an MCUboot adapter from the build's devicetree and Kconfig. For the
Black Pill and the nRF52840 DK it gives the same adapter as the hand-written ones, and the
generated nRF52840 adapter runs with the same result.

**Soak runs.** `--soak MINUTES --seed N`: after the baseline, random clean cuts and torn
states (powered up from the computed state) until the time is up or one fails, each with its
reproduce and export commands. A soak on the demo's `resume_copy` bug finds it within 10
tests; 3 minutes on the correct build, 1,038 tests, find nothing.

**SARIF output.** `--sarif FILE` writes each failure as a SARIF 2.1.0 result (its kind as the
rule, the adapter file as the location, the reproduce and export commands in the message).
The GitHub Action takes `sarif: "true"` and uploads it to code scanning.

**Power cuts many times in a row.** `--depth N` for any N, and `--depth exhaustive` (or
`scenario.depth: exhaustive`): cut during each recovery until a level brings no new flash
state, or `max_states` is reached. The report says how deep it went.

**Worn pages.** `flash.worn: {from, size}` marks a range whose programs report success but
leave bit 0 of each cell as it was, on all three chip models. The demo with its Slot A worn
fails even with no cut (it does not read back what it copied, and the old image is gone),
and the output says why.

**Bit errors at rest.** `scenario.bit_errors` flips seeded random bits in the flash the update
left (each image the oracle accepts, or named regions) and powers up: the CPU must not run
inside the damaged region, nor sit in a fault handler. The demo on all three chips and
MCUboot on both boards never run a damaged image; the demo's `trust_header` bug runs it.

**A broken link.** `scenario.link_cuts` breaks the host's UART link at points spread
over the bytes of its session (the device keeps its power), waits, and lets the host run
the update again; the usual verdict follows. OpenBLT (a full XCP session) and the
Three-Tier bootloader (its UPDATE_FBL frame) recover at all 10 points each.

**Bad update content.** `scenario.content_faults` stages damaged versions of the update
(truncated, a bit flipped in each named region, erased, or images made elsewhere) and the
bootloader must refuse each one and keep the image named by `keep` running, judged by the
oracle. The demo (all three chips, and the external-flash build) and MCUboot on both
boards refuse every one; the demo's `trust_header` bug accepts 6 of 7.

**Flash storage libraries.** A built-in `storage` driver for key-value stores and file
systems: the firmware runs a fixed workload over the UART, the driver learns which flash
operations each step spans, and after a cut checks that the store mounts, holds every value
a finished step left, returns nothing half-written, and takes and keeps a new write.
`adapters/zephyr_storage` runs it on Zephyr's NVS, ZMS, settings on FCB and littlefs on the
nRF52840 DK, from prebuilt firmware. NVS and littlefs recovered at every distinct flash
state; ZMS loses the next write after a cut inside a value (zephyrproject-rtos/zephyr#121747);
settings on FCB can return a half-written value (reported as #122446) or erase its newest
settings after a cut in a sector header (added to #121749).
A driver can now be told which update operation each result was cut at (`judging()`).

**MCUboot and the nRF52840 in CI.** `adapters/mcuboot/prebuilt` holds MCUboot and the test
app built for both boards, so the adapters run with no Zephyr workspace. CI runs both
(`mcuboot (f411)`, `mcuboot (nrf52840)`) and the nRF52840 demo builds.

**A failing state on a real board.** `brickproof export adapter.yaml --cut N [--torn KIND]`
writes the flash a cut leaves (the same bytes the run started the emulator from), the
option bytes and an external chip in files of their own, and the programming commands. Each
failure in the HTML and JUnit reports has its export command next to its reproduce command.

**The torn-write kit in the repository.** `hardware/torn_f103` is the firmware that measured
torn writes on a Nucleo-F103RB, with both runs' results; `tools/torn_fit.py` turns a run into
the numbers `torn.py` uses, and a test checks they still match.

**Torn erases measured on a real chip.** On an STM32F103 an erase stopped by a reset leaves
single bits still 0, scattered over the page and the same cells each time: 4.5% of the old
0 bits at once, 0.35% a little later, none after 50 us. `erase-early` and `erase-late` are
those two shapes; the guessed shapes stay as harder cases. A program was never seen torn.

**A slow emulator is not a dead device.** The hang limit is now 50 times the slowest pace seen,
with no fixed ceiling, and the wait for a cut learns the pace too. Renode was measured running
27 times slower than usual for stretches of a long update.

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
