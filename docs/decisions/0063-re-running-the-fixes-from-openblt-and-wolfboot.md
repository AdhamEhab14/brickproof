# Re-running the fixes from OpenBLT and wolfBoot

2026-10-15

Both maintainers answered our reports with a fix within two days, so the adapters ran the
fixes.

**OpenBLT r1326** (`62786e72`) swaps the two writes in `FlashDone()`: the last data block now
goes before the boot block. Run with the same adapter (phases plan, 23 cuts): the data
blocks are fine, and 4 cuts fail, all in the boot block after its checksum word (0x10C),
because the block is still written from its start. The driver's message said "before the
last block", which no longer fits: it now says "before the rest of the program". Suggested
back to Feaser: the part of the block after the checksum first, then the part up to and
including it, so nothing is written twice (some of their targets allow one write per cell).

**wolfBoot PR #940** (`45a5909e`) moves the STM32F4 trailers to sectors 1 and 2. The driver
gets a `trailer` option, the address where the UPDATE trailer ends, because the update flag
is no longer at the end of the partition; `adapter-custom-trailer.yaml` sets it. 44 cuts, all
recovered, every state cut in the new trailer rewrite (erase the 16 KB sector, write 64
bytes back), which was the step most likely to fail. Run on this PC with 6 emulators: 86
minutes, each cut 10 to 12 minutes of byte-by-byte programming over 128 KB sectors.
