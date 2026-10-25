# The flash model enforces the chip's programming rules

2026-10-10

Audit question: where else is the emulator more forgiving than silicon? Flash. Renode's flash
is plain memory, and the CPU writes into it directly:
- program a halfword that is not erased: silicon refuses (PGERR, cell unchanged, unless the
  value is 0x0000); Renode stores it.
- store into flash with PG clear or the controller locked: silicon ignores it; Renode stores it.

So "forgot to erase" and "forgot to unlock" pass in a plain emulator and brick a board.

The model now keeps a shadow copy of flash in a hidden memory (`bpShadow`) that only real
operations update. When PG is cleared it finds the halfword(s) written by comparing flash with
the shadow, and applies the rule: a refused program gets its old value written back and PGERR
set in SR, like the chip, and is counted. Any other difference between flash and shadow is a
write with no operation behind it; an audit register reports the first such address.

The runner reads both at the same points as the bus-fault latch and fails the run:
- `flash rule broken: 4 program(s) over cells that were not erased, first at 0x0800224E`
- `flash changed at 0x08002004 with no flash operation behind it`

The engine has to declare its own writes (image load, restore, rewind) with a resync, or they
would look like stray writes.

Costs measured in the model: whole-flash compare 0.8 ms, the usual one-halfword check 26 us.

Side effects that are improvements:
- firmware that keeps PG set across several sequential halfwords now has each one found,
  counted and traced (was: one operation);
- the trace no longer needs its own shadow; it logs what the rule check already found.

Two more demo bug builds prove the rules: `bug-no_erase` and `bug-no_unlock`, both caught at
the baseline. The Three-Tier bootloader v2.0.0 passes with enforcement on: no refused program,
no stray write, on the update path and on the recovery paths of its five cuts.

Not modelled, stated plainly: write protection (WRP option bytes), read protection, the option
bytes themselves, flash timing (every operation is instant), and wear.
