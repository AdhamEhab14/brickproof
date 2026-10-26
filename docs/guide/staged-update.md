# A bootloader that installs a staged image

Most OTA designs work this way: the app writes the new image into a staging slot, and the
bootloader installs it at the next boot. BrickProof's built-in `staged_slot` driver covers
it with no code of your own: it puts the new image in the slot, resets the device, and after
each cut checks that the device runs an image you approve. The bundled demo
([examples/demo_ab_bootloader](../../examples/demo_ab_bootloader)) and MCUboot
([guide](mcuboot.md)) are both this kind; wolfBoot ([adapters/wolfboot_f411](../../adapters/wolfboot_f411))
is too, with a small driver of its own.

1. **Build** the bootloader, the app as it ships (v1), and the update (v2) as the bootloader
   expects to find it in the slot.

2. **Write the adapter.** `init` asks for the chip, the files and the slot, boots the
   firmware once to learn its UART, what it prints and how long the update takes, and
   writes `brickproof.yaml` with a comment on every line:

   ```bash
   brickproof init --kind staged
   ```

3. **Check it**:

   ```bash
   brickproof check brickproof.yaml
   ```

4. **A first look**:

   ```bash
   brickproof run brickproof.yaml --quick
   ```

5. **Everything**:

   ```bash
   brickproof run brickproof.yaml --full
   ```

Add an `oracle` with the images byte for byte (init writes one) so a verdict never rests on
what the firmware prints about itself, and `driver.options.rollback` to check that an older
image cannot be installed again.
