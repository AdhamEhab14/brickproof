# A flash storage library

For a key-value store or a file system, not a bootloader. A small workload firmware writes
and deletes values in a fixed order and answers a line protocol on the UART. After a cut,
BrickProof checks that every value a finished write left is there, that nothing half
written comes back, and that the store still takes a new write and keeps it.
[adapters/zephyr_storage](../../adapters/zephyr_storage) runs Zephyr's NVS, ZMS, littlefs
and settings on FCB this way, and found data lost in two of them.

1. **Build the workload** for your store. The protocol is at the top of
   [drivers/storage.py](../../src/brickproof/drivers/storage.py), and
   [adapters/zephyr_storage/app](../../adapters/zephyr_storage/app) is a complete one, the
   same source for all four stores.

2. **Write the adapter**:

   ```bash
   brickproof init --kind storage
   ```

3. **Check it**:

   ```bash
   brickproof check brickproof.yaml
   ```

4. **A first look**:

   ```bash
   brickproof run brickproof.yaml --quick
   ```

5. **Every flash state**: a store's update is short, so cut all of it:

   ```bash
   brickproof run brickproof.yaml --plan every --torn -j auto
   ```
