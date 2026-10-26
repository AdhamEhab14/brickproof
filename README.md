# BrickProof

Pull the plug on your firmware update, in an emulator, at every point where it matters, and
check that the device still comes back.

BrickProof runs your firmware in an emulator ([Renode](https://renode.io), or
[m33mu](https://github.com/danielinux/m33mu) for the chips Renode does not have), cuts power during an update,
powers the device back up, and checks that it recovered: an approved image is installed, it is
really running, the update was not lost, and an older image cannot sneak back in. It tells you
which cuts brick the device, and how to reproduce each one.

It came out of the power-cut tests of
[Three-Tier-STM32-Secure-Bootloader](https://github.com/AdhamEhab14/Three-Tier-STM32-Secure-Bootloader),
where it found three real bugs. That bootloader's fixed release has since been cut at every one
of the 12,109 distinct flash states of its self-update, with no failure. Supported chips: STM32F1,
STM32F4 (F411), STM32L4 (L476) and Nordic nRF52840 on Renode, STM32H5 (H563) on m33mu.

Run on bootloaders that are not ours, it found:

- **OpenBLT** (STM32F1): a cut near the end of a programming session can leave a program
  that the bootloader starts although it is not completely written. Confirmed on a real
  Nucleo-F103RB. Details and the adapter: [adapters/openblt_f103](adapters/openblt_f103).
- **wolfBoot** (STM32F411): with partitions of one sector, as in its own Black Pill example,
  the last step of an update erases the bootloader itself. Confirmed in wolfBoot's own
  simulator: [wolfSSL/wolfBoot#937](https://github.com/wolfSSL/wolfBoot/issues/937). Details
  and the adapter: [adapters/wolfboot_f411](adapters/wolfboot_f411).

It also ran on **MCUboot**, on two boards with three upgrade modes: the STM32F411 Black Pill
(one-sector slots, swap with scratch, 57 cuts; overwrite only, 14 cuts, 31 torn states and
12 second cuts during recovery) and the nRF52840 DK (swap with move, 156 cuts). No failure
on either.
[adapters/mcuboot](adapters/mcuboot).

And on **wolfBoot** on an STM32H563 with TrustZone, emulated by m33mu (its `stm32h5-tz` config,
swap update): 171 cuts, 403 torn states and 323 second cuts during recovery, no failure.
[adapters/wolfboot_h563](adapters/wolfboot_h563). Every target and what it found:
[adapters/README.md](adapters/README.md).

## Quick start

You need Python 3.10+. No toolchain, no board, no firmware of your own: a demo comes with the
package, and `brickproof setup` downloads the emulator ([Renode](https://renode.io) 1.17, checked
against its published SHA-256) for Windows or Linux.

```bash
pip install brickproof-fw
brickproof setup
brickproof demo
```

The demo is a small A/B bootloader updating its app from v1 to v2. BrickProof checks that the
update works when nothing interrupts it, then cuts power at every flash state the update goes
through and checks that the device comes back each time. Now run a build with a known bug,
which BrickProof should catch:

```bash
brickproof demo self_lock --fail-fast
```

`brickproof demo --list` shows all of them, on five chips. [Getting started](docs/getting-started.md)
walks through the demo, its bug builds and installing the emulator yourself.

## Testing your own firmware

Go to the folder with your built firmware and run:

```bash
brickproof init
brickproof run brickproof.yaml --full
```

`init` asks a few questions, boots your firmware once to find out the rest, and writes an
adapter with a comment on every line. `run --full` does everything in one go and ends with
PASS or FAIL and an HTML report. [Testing your own firmware](docs/guide/testing-your-firmware.md)
has the details, and [what a run covers](docs/guide/what-a-run-covers.md) says what is tested.

## In CI

```yaml
- uses: AdhamEhab14/brickproof@v0.3.0
  with:
    adapter: test/brickproof.yaml
    args: --torn --depth 2 -j 3
```

The job fails if any cut does not recover, and the reports are uploaded as an artifact. A
Docker image is there too: [results, a real board, and CI](docs/guide/results-and-ci.md).

## Documentation

| | |
|---|---|
| [docs/](docs/README.md) | everything below, in one index |
| [Getting started](docs/getting-started.md) | install, the demo and its bug builds |
| [Testing your own firmware](docs/guide/testing-your-firmware.md) | `init`, `check`, `run`, the three kinds of update |
| Five steps for: [MCUboot](docs/guide/mcuboot.md), [a staged image](docs/guide/staged-update.md), [over the UART](docs/guide/uart-protocol.md), [a storage library](docs/guide/storage-library.md) | the guide for your kind of update |
| [What a run covers](docs/guide/what-a-run-covers.md) | every kind of test a run makes |
| [Results, a real board, and CI](docs/guide/results-and-ci.md) | reports, exporting a cut's flash, the Action, Docker |
| [The adapter file](docs/reference/adapter.md), [options](docs/reference/cli.md), [limits](docs/reference/limits.md) | reference |
| [Targets](adapters/README.md) | the real firmware it has run on, and what it found |
| [How it is built](docs/architecture.md), [decisions](docs/decisions/README.md), [features](docs/features.md) | for working on BrickProof |

## Licence

Apache-2.0, see [LICENSE](LICENSE).
