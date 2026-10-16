# wolfBoot on an STM32H563, with TrustZone

[wolfBoot](https://github.com/wolfSSL/wolfBoot) with its `stm32h5-tz` example config: wolfBoot
and its wolfCrypt secure service in the secure world, and in the non-secure world the test
application wolfBoot's own emulator CI runs (`test-app/emu-test-apps`). The update installs
v4 over v1 by swapping the BOOT and UPDATE partitions sector by sector, through the swap
sector. The chip is emulated by [m33mu](https://github.com/danielinux/m33mu), which models
what a power cut meets on an H5: 128-bit programs that cannot be repeated, 8 KB sectors, the
datasheet's timings.

The update is staged the way wolfBoot's library leaves it after `wolfBoot_update_trigger()`:
the signed v4 image at the start of the UPDATE partition, and the "update" flag in that
partition's trailer. On the next boot wolfBoot swaps the partitions. The application prints
`get_version=N` when it starts, and v4 confirms itself (`wolfBoot_nsc_success()`). Either image
is a right answer after a cut: wolfBoot goes back to v1 by design when v4 has not confirmed
itself.

## Running it

```bash
git clone https://github.com/wolfSSL/wolfBoot
cd wolfBoot
git submodule update --init
cp config/examples/stm32h5-tz.config .config
make wolfboot.bin
# the test app's linker script: the BOOT partition after the 1 KB image header
sed -e 's/@FLASH_ORIGIN@/0x08060400/' -e 's/@FLASH_SIZE@/0x9FC00/' \
    test-app/emu-test-apps/stm32h563/target.ld.in > test-app/emu-test-apps/stm32h563/target.ld
for v in 1 4; do
  make -C test-app/emu-test-apps TARGET=stm32h5 TZEN=1 IMAGE_HEADER_SIZE=1024 EMU_VERSION=$v sign-emu
done
# the device as it leaves the factory: wolfBoot, and v1 in the BOOT partition
make -C tools/bin-assemble
tools/bin-assemble/bin-assemble factory_brickproof.bin \
    0 wolfboot.bin 0x60000 test-app/emu-test-apps/stm32h563/image_v1_signed.bin
cd -
brickproof run adapters/wolfboot_h563/adapter.yaml --target wolfBoot --html wolfboot.html
```

That needs m33mu on PATH (or in `M33MU_PATH`). The Docker image carries it; with Docker or
podman:

```bash
docker run --rm -v "$PWD/adapters/wolfboot_h563:/adapter:ro" -v "$PWD/wolfBoot:/wolfboot:ro" \
    -v "$PWD/out:/work" ghcr.io/adhamehab14/brickproof \
    run /adapter/adapter.yaml --target /wolfboot -j 8 --torn --depth 2 --html /work/wolfboot.html
```

| File | What |
|---|---|
| `adapter.yaml` | the chip, the factory image, the approved images and the cut plan |
| `driver.py` | stages v4 with the update flag set, and reads the version the app reports |

## What it found

No failure. The update with no cut is 17,612 flash operations through 6,611 distinct flash
states, and every planned cut, torn state and second cut came back with v1 or v4 installed
and running:

| | |
|---|---|
| cuts (every state of 219 phases, the 15 long ones sampled) | 171/171 recovered |
| torn erases and programs | 403/403 recovered |
| a second cut during the recovery from the first | 323/323 recovered |

One thing to know: the two sectors at the end of the UPDATE partition, where wolfBoot keeps
its flags, are erased 17 times per update. With `NVM_FLASH_WRITEONCE` a flag change means
erasing a sector and writing it again, and at the 10,000 cycles the datasheet promises that
is about 588 updates before those sectors wear out.

Tested on wolfBoot master `9bdc6cb3` (2026-10-14) with m33mu `23960ed`, in the Docker image
built with rootless podman.
