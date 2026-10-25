# An I2C EEPROM (plan item 10)

2026-10-16

A C# model (`BpI2cEeprom.cs`, an `II2CPeripheral`) for the 24-series, attached to the
platform's own I2C controller, so firmware drives it through the real controller model. It
shares the flash model's operation count, cut point and trace switch, as the SPI NOR model
does, so one numbering covers every memory.

**A write is not a program.** A 24-series EEPROM erases the bytes it was given and writes
them in one internal cycle, all bytes of the page at once. So a write can set bits as well
as clear them, and a cut inside one leaves the page part way through the erase (old 0 bits
partly back to 1), erased (0xFF), or part way through the write (from 0xFF, part of the new
value's 0 bits cleared). The flash torn shapes all assume old AND new and would never give
the case that matters: an old record coming back as 0xFF, or half new under a magic the
write had not reached yet. The EEPROM has three shapes of its own, `page-erasing`,
`page-erased` and `page-writing`, chosen by address (`trace.in_eeprom`). They are models,
like most flash shapes; nothing was measured on a real EEPROM.

A first version mixed whole bytes (each byte old, 0xFF or new). The chip does not write
byte by byte, and with that model the demo bug below was caught only by luck, so it went.

**Where it sits.** It comes last in the flash image, after the external flash and its status
bytes, so images saved before it existed keep their layout. Its unit in `locate` is the
page, which is what a write can touch.

**Timing.** The write cycle (5 ms, the 24LC256's maximum, which the datasheet also gives as
the only figure) is spent, but the model never NAKs its address while busy. That is the same
choice as the SPI NOR model, which never reports busy. Firmware that polls correctly sees
one poll succeed. Firmware that forgets to poll would work in the emulator and fail on a real
chip, which is a known gap.

**Renode's I2C controller** (STM32F1_I2C, also used for the F4) does not end the transfer
before a repeated start, so a random read reaches the model as a word address with no stop
and then a read. The model takes a pending word address at the start of a read.
tests/renode/test_eeprom_rules.py checks this; it fails without the fix.

**The demo.** `EEPROM_FLOOR` keeps the F411 demo's rollback floor in a 24C256 on I2C1, a
record per 64-byte page, through a bare-metal polling I2C driver. The device ships as one
that has been updated before (both records written), so the next record goes over an old
one. The correct build clears the old magic, writes seq and floor, then the magic: three
writes, each harmless to cut. `BUG_EE_NO_INVALIDATE` skips the first. Between two writes
the page holds the old record or the new seq and floor under the old magic, which is still
right, so every clean cut passes. A torn record write leaves seq and floor at anything
under a valid magic, and the newest-looking record names a floor no image meets.

Not modelled: the write-protect pin, the chip select address pins beyond the bus address,
and the 24C04 to 24C16 kind that puts address bits in the bus address.
