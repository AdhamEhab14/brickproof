# Targets

Real firmware BrickProof has been run on, one folder each. The demo bootloader and its bug
builds are in [examples/demo_ab_bootloader](../examples/demo_ab_bootloader).

| Target | Chip, emulator | The update | Firmware from | In CI | What it found |
|---|---|---|---|---|---|
| [three_tier_f103](three_tier_f103) | STM32F103, Renode | FBL self-update over a UART protocol | built from source (v2.0.0) | `e2e` | three bugs, fixed in v2.0.0; v2.0.0 survives every one of its 12,109 states |
| [mcuboot](mcuboot) | STM32F411 and nRF52840, Renode | MCUboot swap-scratch, overwrite-only, swap-move | `prebuilt/` | scenarios `mcuboot-*` | no failure |
| [zephyr_storage](zephyr_storage) | nRF52840, Renode | Zephyr NVS, littlefs, ZMS, settings on FCB under a write workload | `prebuilt/` | scenarios `storage-*` | ZMS and settings on FCB lose data after a cut (zephyrproject-rtos/zephyr#121747, #122446, #121749) |
| [openblt_f103](openblt_f103) | STM32F103, Renode | OpenBLT programming session over XCP | you build it from its repository | no | a cut near the end of a session can leave a program that starts half written |
| [wolfboot_f411](wolfboot_f411) | STM32F411, Renode | wolfBoot swap with one-sector partitions | you build it from its repository | no | the final erase wipes the bootloader (wolfSSL/wolfBoot#937) |
| [wolfboot_h563](wolfboot_h563) | STM32H563 with TrustZone, m33mu | wolfBoot swap | you build it from its repository | no | no failure |

## What a target folder holds

| File | When |
|---|---|
| `README.md` | always: what is updated and what a cut must leave, **Running it** (how to get the firmware and the command), **What it found** |
| one or more adapter YAML files | always: see [docs/reference/adapter.md](../docs/reference/adapter.md) |
| `driver.py` | when the update is started by a host over a protocol |
| `build.py`, `app/` | when the firmware under test is built here (a test app, a workload) |
| `prebuilt/` | when CI runs the target from committed files: the binaries, a `README.md` saying how they were built (commits, compiler, date) and a `SHA256SUMS` that `tests/test_prebuilt.py` checks |

A target CI runs gets a line in [tests/scenarios.yaml](../tests/scenarios.yaml) (or, like
the Three-Tier bootloader, a job that builds it first), and then its results are part of the
parity check.
