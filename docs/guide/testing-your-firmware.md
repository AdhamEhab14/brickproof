# Testing your own firmware

Go to the folder with your built firmware and run:

```bash
brickproof init
brickproof run brickproof.yaml --full
```

`init` asks which chip, which files and how the update happens (a few numbered choices),
then boots your firmware once in the emulator to find out the rest by itself: which UART it
talks on, what it prints while running and once updated, and how long the update takes. It
reads an MCUboot image's real size from its header. It writes `brickproof.yaml`, with a
comment on every line, and checks it. `run --full` then does everything in one go: clean
cuts, torn writes, a second cut during each recovery, damaged images, and bits flipped at
rest, and ends with PASS or FAIL and the path of an HTML report.

Three kinds of update are covered:

| Kind | What it means | What you need |
|---|---|---|
| staged | the bootloader installs a new image that waits in flash, at the next boot (MCUboot, most OTA designs) | the bootloader, the old app image, the new one |
| storage | a flash storage library (key-value store, file system) | a workload firmware that speaks [the storage protocol](../../src/brickproof/drivers/storage.py), like [adapters/zephyr_storage/app](../../adapters/zephyr_storage/app) |
| protocol | a host sends the update over the UART with its own protocol | `init` writes a `driver.py` to fill in; [adapters/openblt_f103](../../adapters/openblt_f103) is a complete one |

`brickproof check brickproof.yaml` reads the adapter and every file it names without starting
an emulator, and says what to fix: a file that is not built yet, firmware that does not fit
the chip's flash or RAM, a UART the chip does not have, an image size that does not match
the image, an emulator that is not installed. `run`, `trace` and `export` make the same
checks first. Every key of the adapter is explained in [the adapter reference](../reference/adapter.md).

For MCUboot built with Zephyr, the adapter can be written from the build:

```bash
brickproof adapter-from-zephyr build/mcuboot --images <folder with the signed images> -o adapter.yaml
```

It reads the chip, MCUboot's upgrade mode, the flash, the RAM, the slots, the console UART
and an STM32 board's crystal from `zephyr/zephyr.dts` and `zephyr/.config`.
