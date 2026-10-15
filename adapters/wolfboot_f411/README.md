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
| `adapter-custom-trailer.yaml` | the same with the fix proposed in PR #940: trailers in sectors 1 and 2 |
| `driver.py` | stages v2 with the update flag set, and reads the version the app reports; with `trailer`, the flag goes in a trailer sector of its own |

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

## The proposed fix (PR #940)

wolfSSL answered within two days with
[wolfSSL/wolfBoot#940](https://github.com/wolfSSL/wolfBoot/pull/940): a partition smaller than
two sectors (three with `NVM_FLASH_WRITEONCE`) is now a build error, unless
`CUSTOM_PARTITION_TRAILER` is set; on the STM32F4 that option keeps the BOOT and UPDATE
trailers in the 16 KB sectors 1 and 2, and the Black Pill config uses it. The trigger then
erases nothing, so storing the image and then triggering works again.

`adapter-custom-trailer.yaml` runs it: the same build steps on the PR's branch, with the
update flag staged in sector 2 (`trailer: 0x0800C000`). On `45a5909e` (2026-10-15):

- the update with no cut completes and v2 runs (143,502 operations);
- 44 cuts, every distinct flash state in 13 of the 16 phases and 8 samples in each of the
  three long copies: all recovered. That includes every cut in the new step where a trailer
  sector is erased and its 64 bytes written back;
- a cut after BOOT is set to TESTING and before v2 first runs ends on v1: wolfBoot takes an
  image in TESTING that never confirmed as a failed one and goes back. That is its design.

Each trailer sector is erased twice per update, the most of any sector: 5,000 updates at the
10,000 cycles the datasheet promises.
