# A third chip family, the nRF52840

2026-10-14

Chosen over the STM32L4 because Renode emulates the nRF52840 (UARTE, timers, RTC, clock)
and has no L4 platform at all: the L4 would have meant a whole platform first. The nRF52 is
also a different vendor with different flash rules, and the home of MCUboot.

**The NVMC model** (`models/nrf52_flash.py`). Renode has none: its flash is plain memory.
CONFIG.WEN says what the flash does (Ren, Wen, Een). A program is a store while WEN is Wen,
heard through the CPU's memory-access hook as on the F4; it must be a whole, aligned 32-bit
word (narrower is a hard fault on the chip, refused and reported here), it can only clear
bits, and a word may be written twice between erases (nWRITE = 2; a third write is refused
and reported). How often each word was written lives in memory (`bpCounts`), not in the
model, because a CPU reset does not undo it on the chip. ERASEPAGE erases a 4 KB page and
ERASEALL everything. Times from the product specification, which gives only maximums: 41 us
a word, 85 ms a page, 169 ms for all. The test registers sit at 0x100..0x14C as on the STM32
models; the NVMC's own start at 0x400.

**The platform** is Renode's, written out (`platforms/nrf52840.repl`): the stock file applies
an SVD it downloads at every start, only to name registers in logs, and the download failing
prints an error the engine takes as Renode refusing a command. FICR gets CODEPAGESIZE and
CODESIZE, because Zephyr's flash driver takes the flash size from them; without them MCUboot
cannot read its own slots. The guards cover what is empty on this chip: after flash up to the
RAM alias at 0x00800000, after that alias up to FICR, between UICR and RAM, and after RAM up
to the peripherals. The engine no longer assumes an STM32: the RAM name and the CPU speed
(64 MHz here) come from the chip.

**Checked** with MCUboot on the nRF52840 DK (swap using move, the board's own partitions):
15,400 operations in 52 phases, baseline and 156 cuts, all recovered to v2.

Not modelled: partial erase, the UICR (not part of the flash image; ERASEUICR is ignored),
ACL protection, the cache.
