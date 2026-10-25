# 4-byte addresses; no quad mode (plan item 9)

2026-10-16

**4-byte addresses** follow the W25Q256JV datasheet, for chips over 16 MB: B7h and E9h
enter and leave 4-byte mode, ADS (status register 3, bit 0) reports it, ADP (bit 1, stored)
sets it at power-up; 13h, 0Ch, 12h, 21h, 5Ch and DCh take four address bytes in either
mode; in 3-byte mode the extended address register (C5h with a write enable, C8h to read,
volatile) is the top byte. That chip has no SEC bit and four BP bits, so its block
protection table is its own: BP = n protects 64 KB << (n - 1) from the top, or with TB from
the bottom, until it covers everything. A chip of 16 MB or less ignores all of these
commands, as a W25Q128 does, so firmware that sends them to the wrong chip sees them do
nothing. `external_flash.size` goes to 64 MB (a W25Q512).

The plan said this needs sparse flash images. It does not, up to 64 MB: an image is held
whole, and a 64 MB chip makes each saved state 64 MB bigger, which costs memory and time
but works. Sparse images would make a campaign on a big chip cheaper, not possible; they
wait until someone needs one.

**Quad and dual modes are not modelled.** Renode's SPI controllers on these chips (STM32
SPI, nRF52 SPIM) move one bit per clock. Firmware cannot send a quad command through one,
so a quad read in the model could never be reached. The controllers that can (an STM32
QUADSPI, the nRF52840 QSPI) are where the work would be: the F411 has no QUADSPI, and
Zephyr's nRF QSPI driver hangs in Renode (found with the storage adapters). This stays
out until a target with a working quad controller needs it.

**Checked** in Renode (tests/renode/test_spinor_4byte_rules.py, the f411-ext chip made
32 MB through the fixture's new ADJUST hook): the 4-byte commands above 16 MB, 4-byte mode
for the 3-byte commands, the extended address register and its loss at power cycle, ADP at
power-up, the BP3-BP0 table at the top, the bottom and all of it. On the 1 MB chip, B7h and
13h do nothing.
