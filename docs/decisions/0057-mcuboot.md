# MCUboot

2026-10-13

`adapters/mcuboot` (then `adapters/mcuboot_f411`): MCUboot built with Zephyr v4.2.0 for `blackpill_f411ce`, its
default swap using scratch, the board's own layout (MCUboot 32 KB, then slot 0, slot 1 and
scratch at one 128 KB sector each), ECDSA-P256 signatures (RSA-2048 does not fit 32 KB with
Ubuntu's compiler). A small app prints its version; v2 is staged with `--pad --confirm`, so
only v2 is accepted after a cut.

The update is 391,974 operations (the Zephyr F4 driver programs a byte at a time) in 19
phases; 14.3 s of flash time on the chip. Result: the baseline and 57 planned cuts plus two
more, every one recovered to v2. One build mistake on the way, worth knowing: an app built
for MCUboot on this board must be linked for slot 0 (`zephyr,code-partition`), which the
board files do not choose; without it MCUboot jumps into an app linked for address 0 and
the app aborts.
