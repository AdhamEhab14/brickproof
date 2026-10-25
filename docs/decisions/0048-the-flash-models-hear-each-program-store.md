# The flash models hear each program store

2026-10-12

**What was wrong.** A program is a store by the CPU straight into Renode's flash memory,
and a Python peripheral does not see it. The models therefore worked backwards: when PG
was cleared they compared flash with their shadow copy and took what differed as what had
been programmed, looking first at the cell after the last one. To allow for firmware that
leaves PG set over a few cells, a difference right after the expected cell was accepted too.

That allowance was a hole. Firmware that programs one halfword properly and stores the next
one after clearing PG leaves exactly that pattern, and the F103 model accepted the stray
store as a program. On the chip that store is ignored and half the image is never written.
Checked with a build that does this (`bug-early_unpg`): the old F103 model passed its
baseline, "runs v2". A false pass, the worst kind of mistake for this tool. (The old F4
model happened to catch it, through a different path.)

The same guesswork had two smaller costs: a program that wrote the value already there had
its address inferred, and a cut could not fall between two stores made under one PG.

**What it does now.** Renode can report every memory access of a CPU to a hook
(`SetHookAtMemoryAccess`). Hearing all of them would be far too slow, so the model turns it
on when PG is set and off when it is cleared. One detail makes it work: the store usually
sits in the same translated block as the write to CR, and a block already translated has
no hook in it. `RequestTranslationBlockRestart` ends the block after the CR write, and the
store is then translated with the hook. Measured on the demo: 172 stores reported for 172
programs, each with its address, width and value.

The hook is called after the store has landed, so the model applies the chip's rules there
and puts the old value back when the chip would not have written: the programming rule and
write protection as before, and now also the width (an F4 store that is not as wide as PSIZE
says sets PGPERR and writes nothing; an F1 programs halfwords only). A cut is the same move:
old value back, CPU halted, block ended. So a program cut lands exactly before its store
with no help from the runner, and it can land between two stores under one PG.

Whatever differs from the shadow at an audit was stored with PG clear. There is nothing left
to guess, and no inferred addresses: the Three-Tier trace used to have 8,640 of them.

A reset removes the hook (the machine's reset event), so a watchdog reset in the middle of
a program does not leave the CPU reporting every access for the rest of the run.

**Demo.** Two builds for each chip: `hold_pg` writes whole runs of cells under one PG and
must pass every cut, and `bug-early_unpg` is the mistake above and must fail its baseline.
