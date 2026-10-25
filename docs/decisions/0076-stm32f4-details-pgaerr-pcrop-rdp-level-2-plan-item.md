# STM32F4 details: PGAERR, PCROP, RDP level 2 (plan item 5)

2026-10-16

From RM0383. **PGAERR**: the data of one program must fit in one 128-bit (16-byte) flash row;
a store across a row boundary is not written and sets PGAERR. The model checks it after the
width (PGPERR) and before write protection, and counts it with the refused programs, so the
run fails the way a PGPERR does.

**PCROP**: with SPRMOD set the nWRP bits change meaning: a set bit makes the sector
proprietary code, which the CPU can execute but not read as data, erase or program. Erase and
program refusals go through write protection as before, with the bit's meaning flipped. A
data read is the hard part: on the chip it gets RDERR and no data, but a Renode memory hook
cannot change the value a read returns. So the model finds the read and fails the run
("proprietary code read as data", new test registers 0x150 and 0x154), the way it reports a
store the chip ignores. Finding reads means hearing every memory access, which is slow, so it
is on only while SPRMOD is set; nothing changes for other adapters. Two Renode details shaped
it: a reset runs the model's init again and drops its handle on the bus, so the read watcher
is made in the reset handler with its own (a hook using the model's handle crashed Renode on
the first read after a reset); and RDERR lives in the model's state memory, read into SR, for
the same reason.

**RDP level 2** (0xCC) is for good: an OPTSTRT changes nothing. `flash.read_protected: 2`
builds such option bytes.

**Checked** in Renode (tests/renode/test_f4_rules.py), with the CPU itself making each store
and read from a few instructions in RAM: a word inside one row is programmed; a word across a
row is refused with PGAERR; a data read of a PCROP sector is counted, with RDERR, and running
code there is not; a PCROP sector cannot be erased; without SPRMOD a set nWRP bit is plain
writable flash; level 2 option bytes do not change. Four of the six fail on the old model. The
F411 demo builds (correct, external flash, hold_pg and the bug builds) behave as before.
