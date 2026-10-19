# MCUboot

[MCUboot](https://github.com/mcu-tools/mcuboot), built with Zephyr, on two boards, each with
its own partition layout. Each board's default upgrade mode, and on the Black Pill also the
overwrite-only mode:

| Adapter | Board | Upgrade | Layout |
|---|---|---|---|
| `f411.yaml` | STM32F411 Black Pill | swap using scratch | MCUboot 32 KB at 0x08000000; slot 0, slot 1 and scratch one 128 KB sector each |
| `f411-overwrite.yaml` | STM32F411 Black Pill | overwrite only | the same (the scratch sector is unused) |
| `nrf52840.yaml` | nRF52840 DK | swap using move | MCUboot 48 KB at 0x0; slot 0 at 0xC000 and slot 1 at 0x82000, 472 KB of 4 KB pages each |

A small app (`app/`) prints `APP v1` or `APP v2`. v2 is signed with `--pad --confirm`, so
the upgrade is permanent: after any cut, v2 must be installed in slot 0 and running.

## Running it

The built firmware for both boards is committed in `prebuilt/`, so this needs nothing but
BrickProof and Renode:

```bash
brickproof run adapters/mcuboot/f411.yaml -j 3 --html mcuboot-f411.html
brickproof run adapters/mcuboot/f411-overwrite.yaml -j 3 --per-phase 1 --real-every 4 --torn --depth 2
brickproof run adapters/mcuboot/nrf52840.yaml -j 3
```

To build it yourself (another MCUboot or Zephyr, another configuration), you need a Zephyr workspace with MCUboot (`west init`, `west update`, with `hal_stm32` and
`hal_nordic`), and either the Zephyr SDK or `arm-none-eabi-gcc`
(`ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb`).

```bash
python adapters/mcuboot/build.py <zephyr workspace> mcuboot-out f411
brickproof run adapters/mcuboot/f411.yaml --target mcuboot-out -j 3 --html mcuboot-f411.html

python adapters/mcuboot/build.py <zephyr workspace> mcuboot-out-nrf52840 nrf52840
brickproof run adapters/mcuboot/nrf52840.yaml --target mcuboot-out-nrf52840 -j 3
```

A fourth argument picks another upgrade mode: `overwrite` builds MCUboot with
`CONFIG_BOOT_UPGRADE_ONLY=y` (`MODES` in `build.py` lists them).

The only change from MCUboot's defaults is the signature type: ECDSA-P256 instead of
RSA-2048, which with Ubuntu's compiler does not fit the Black Pill's 32 KB bootloader
partition. It does not change how an upgrade is done.

| File | What |
|---|---|
| `f411.yaml`, `f411-overwrite.yaml`, `nrf52840.yaml` | the chip, the approved images and the cut plan |
| `build.py` | builds MCUboot and the app for one board, signs v1 and v2 |
| `app/` | the app, with an overlay that links it for slot 0 |
| `prebuilt/f411/`, `prebuilt/f411-overwrite/`, `prebuilt/nrf52840/` | `build.py`'s output for each board and mode, which the adapters use unless `--target` says otherwise |

## What it found

No failure on either board, in either mode. Tested on MCUboot `4eba8087fa60` with Zephyr
v4.2.0 (2026-10-13; overwrite-only 2026-10-19).

**STM32F411.** The F411 is programmed a byte at a time here, so one update is about 392,000
flash operations, 14 s of erasing and programming on the chip. The update with no cut, and
57 cuts over all 19 phases of the swap (every state of the 14 short phases, 8 sampled states
in each of the 5 long copies), plus two more: after every cut MCUboot finished the swap on
the next boot and v2 ran from slot 0. The layout is the one that broke wolfBoot (one sector
per slot); MCUboot keeps its swap status in the scratch sector and the slot trailers and
resumes from there.

**STM32F411, overwrite only.** Here v2 is copied over slot 0 with no copy of v1 kept
anywhere, so after a cut MCUboot must copy again from slot 1. The update is 17,348 flash
operations in 6 phases: slot 0's sector erased, v2 copied a byte at a time, slot 0's
trailer written, slot 1 erased. The update with no cut, 14 cuts (every state of the 4 short
phases, edges and samples in the copy and the trailer), 31 torn erases and programs, and 12
new states from a second cut during the recovery from a first (162 more second cuts gave a
state already tested): after every one v2 ran from slot 0. MCUboot also refused all 8
damaged images (truncated, a bit flipped in the header, body or signature, erased) and kept
v1, and ran none of the 4 copies of v2 with a bit flipped at rest.

**nRF52840.** The nRF52840 programs whole 32-bit words, so the update is 15,400 flash
operations in 52 phases, 2.1 s of erasing and programming. The update with no cut, and 156
cuts over all 52 phases (8 sampled states in each of the 15 page copies, every state of the
rest): after every cut MCUboot finished the move on the next boot and v2 ran from slot 0.

The F411 run found a problem in BrickProof instead: Renode does not run at an even pace over
that many byte-wide programs, and the hang limit called a slow but healthy emulator locked
up. That is fixed (see docs/decisions.md, 2026-10-13).
