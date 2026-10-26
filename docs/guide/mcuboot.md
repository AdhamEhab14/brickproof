# MCUboot (Zephyr)

An MCUboot build finds a signed image waiting in slot 1 and installs it at the next boot.
BrickProof cuts power during that install and checks that the device always comes back
running v1 or v2, byte for byte. [adapters/mcuboot](../../adapters/mcuboot) is a complete
example on two boards, in swap-with-scratch, overwrite-only and swap-with-move modes.

1. **Build** MCUboot and your app with Zephyr, and sign two versions of the app with
   `imgtool`: v1, and v2 with `--pad --confirm` so the upgrade is permanent.

2. **Write the adapter from the build.** It reads the chip, MCUboot's upgrade mode, the
   flash, the RAM, the slots, the console UART and an STM32 board's crystal:

   ```bash
   brickproof adapter-from-zephyr build/mcuboot --images signed/ -o brickproof.yaml
   ```

   (`brickproof init --kind staged` works too, for a build that is not Zephyr's.)

3. **Check it** without an emulator: the files, their sizes, the UART, every key.

   ```bash
   brickproof check brickproof.yaml
   ```

4. **A first look**, in a minute or two:

   ```bash
   brickproof run brickproof.yaml --quick
   ```

5. **Everything**: clean cuts, torn writes, a second cut during each recovery, damaged images
   (the image header, body and signature, read from the image) and bits flipped at rest.

   ```bash
   brickproof run brickproof.yaml --full
   ```

A byte-wide F411 swap is about 392,000 flash operations, so `--full` powers most cuts up
from the computed flash state and checks that against real cuts; give it time, or
`--shard K/N` over several machines.
