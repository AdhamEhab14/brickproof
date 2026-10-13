# wolfBoot on an STM32F411 Black Pill

[wolfBoot](https://github.com/wolfSSL/wolfBoot) with its own test application and its own
Black Pill example config, updating v1 to v2 by swapping the BOOT and UPDATE partitions.

The update is staged the way wolfBoot's library leaves it after `wolfBoot_update_trigger()`:
the signed v2 image at the start of the UPDATE partition, and the "update" flag in that
partition's trailer. On the next boot wolfBoot swaps the partitions. Either image is a right
answer after a cut: wolfBoot goes back to v1 by design when v2 has not confirmed itself.

## Running it

```bash
git clone https://github.com/wolfSSL/wolfBoot
cd wolfBoot
git submodule update --init lib/wolfssl
cp config/examples/stm32f411-blackpill.config .config
make keytools
make UART_FLASH=0
tools/keytools/sign --ed25519 --sha256 test-app/image.bin wolfboot_signing_private_key.der 2
cd -
brickproof run adapters/wolfboot_f411/adapter.yaml --target wolfBoot --html wolfboot.html
```

The stock config keeps the UPDATE and SWAP partitions on a host reached over the UART.
`UART_FLASH=0` puts them in the chip's own flash, at the addresses the config gives.

| File | What |
|---|---|
| `adapter.yaml` | the chip, the factory image, the approved images and the cut plan |
| `driver.py` | stages v2 with the update flag set, and reads the version the app reports |

## What it found

With this config even the update with no cut fails: the device is dead afterwards. The
example config uses partitions of one sector (`WOLFBOOT_PARTITION_SIZE` and
`WOLFBOOT_SECTOR_SIZE` both 0x20000), and in `wolfBoot_swap_and_final_erase()`
(`src/update_flash.c`)

```c
uintptr_t tmpBootPos = WOLFBOOT_PARTITION_SIZE - eraseLen - WOLFBOOT_SECTOR_SIZE;
```

comes out as minus one sector, which is the bootloader's own sector. After the swap has
installed v2, the final phase erases the boot partition (the new image), then that sector
(the bootloader), then the update partition. Nothing is left to boot.

The same happens in wolfBoot's own simulator with a one-sector layout, so it is not
something the emulation made up. Four other example configs use the same layout.

What is still open: with this layout the usual order (store the image, then call
`wolfBoot_update_trigger()`) erases the new image before the update can start, because the
trigger erases the last sector of the UPDATE partition, which is the whole partition. The
update then never happens, and the device keeps v1. The bootloader is erased when the update
is staged with the flag already set, as this adapter does.

Tested on wolfBoot master `400bce6` (2026-10-12); the same code is in v2.10.0. Reported in
[wolfSSL/wolfBoot#937](https://github.com/wolfSSL/wolfBoot/issues/937).
