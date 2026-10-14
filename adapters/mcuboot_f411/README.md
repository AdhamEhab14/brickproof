# MCUboot on an STM32F411 Black Pill

[MCUboot](https://github.com/mcu-tools/mcuboot), built with Zephyr for the `blackpill_f411ce`
board, with its default upgrade mode (swap using scratch) and the board's own partition
layout:

| Partition | Address | Size |
|---|---|---|
| MCUboot | 0x08000000 | 32 KB |
| slot 0 (running image) | 0x08020000 | 128 KB, one sector |
| slot 1 (new image) | 0x08040000 | 128 KB, one sector |
| scratch | 0x08060000 | 128 KB, one sector |

A small app (`app/`) prints `APP v1` or `APP v2`. v2 is signed with `--pad --confirm`, so
the upgrade is permanent: after any cut, v2 must be installed in slot 0 and running.

The F411 programs flash a byte at a time here, so one update is about 392,000 flash
operations, 14 s of erasing and programming on the chip.

## Running it

You need a Zephyr workspace with MCUboot (`west init`, `west update`), and either the Zephyr
SDK or `arm-none-eabi-gcc` (`ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb`).

```bash
python adapters/mcuboot_f411/build.py <zephyr workspace> mcuboot-out
brickproof run adapters/mcuboot_f411/adapter.yaml --target mcuboot-out -j 3 --html mcuboot.html
```

The only change from MCUboot's defaults is the signature type: ECDSA-P256 instead of
RSA-2048, which with Ubuntu's compiler does not fit the 32 KB bootloader partition. It does
not change how an upgrade is done.

| File | What |
|---|---|
| `adapter.yaml` | the chip, the approved images and the cut plan |
| `build.py` | builds MCUboot and the app, signs v1 and v2 |
| `app/` | the app, with an overlay that links it for slot 0 |

## What it found

No failure. Tested on MCUboot `4eba8087fa60` with Zephyr v4.2.0 (2026-10-13): the update
with no cut, and 57 cuts over all 19 phases of the swap (every state of the 14 short phases,
8 sampled states in each of the 5 long copies), plus two more. After every cut MCUboot
finished the swap on the next boot and v2 ran from slot 0.

The layout is the one that broke wolfBoot (one sector per slot); MCUboot keeps its swap
status in the scratch sector and the slot trailers and resumes from there.

The run found a problem in BrickProof instead: Renode does not run at an even pace over
this many byte-wide programs, and the hang limit called a slow but healthy emulator locked
up. That is fixed (see docs/decisions.md, 2026-10-13).
