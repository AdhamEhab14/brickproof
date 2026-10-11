# Changelog

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
  for memory that is not there, erase before program, write protection, option bytes
  (including the mass erase when read protection is removed).
- The firmware's own signs of life, through the adapter's driver.

**What you get**
- JSON, JUnit and HTML reports; the HTML one lists each failure with a command that reproduces
  it, the firmware hashes, and where the evidence fits in UN R156 and the EU Cyber Resilience Act.
- A bundled demo (`brickproof demo`): a small A/B bootloader and ten builds with a known bug,
  each of which a run catches.
- A GitHub Action and a Docker image.

**Supported chips.** STM32F1.

**Not modelled yet.** Torn-operation shapes are a model until compared with real hardware.
The USER and Data option bytes have no effect. Flash timing and wear.
