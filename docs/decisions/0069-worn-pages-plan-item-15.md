# Worn pages (plan item 15)

2026-10-16

A page past its rated cycles may still erase but no longer program reliably. The datasheets
say it differently per chip (on an F1 the data does not match after programming; the F4 may
or may not flag it; on the nRF52 nothing flags it), and they agree on the part that matters:
the program can look fine and the data is wrong. So one behaviour is modelled on all three:
in the `flash.worn` range a program is accepted and bit 0 of each cell keeps its old value.
No status flag is set, which is the hardest case for firmware.

The models get the range as two constants (`WORN_FROM`, `WORN_TO`, none by default), like
their geometry, so nothing changes for an adapter that does not set it. The value the model
stores is what goes into the trace and the shadow copy, so the replay and the self-check
follow the worn cells too.

Not modelled: a cycle count after which a page wears out (`fail_after` in the plan). Counting
erases per page across runs would need state that outlives a run, and one fixed worn range
already answers the question the plan asks: does the bootloader notice. The demo does not:
with its Slot A worn the copy of v2 is wrong, its CRC fails at boot, and the old image has
already been erased, so the update fails with no power cut at all. That is what an
overwrite updater that does not read back its writes does on such a chip.
