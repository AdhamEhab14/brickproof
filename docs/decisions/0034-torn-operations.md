# Torn operations

2026-10-11

A clean cut falls between two operations. A real one can fall inside one. `torn.py` builds
the states that leaves, following what flash cells do:
- an erase moves bits 0 to 1; cut short, some of the page's 0 bits have flipped, the 1 bits
  stay 1;
- a program moves bits 1 to 0; cut short, some of the bits due to become 0 have.

Which bits get there first is not knowable from here, so each torn operation is tried as a
few shapes that obey those rules: for an erase, half the page done, a random scatter, almost
all done (one byte in 64 still old); for a program, only the low byte's bits, only the high
byte's, a random subset. Shapes equal to the state before or after the operation are dropped
(those are the clean cuts), so a program with a single bit to clear has no torn state.
Seeded, so a run is repeatable.

A torn state is built, not provoked: the flash before the operation comes from replaying the
golden run (the same replay every real cut is checked against), the half-done operation is
applied to that image, and the device is powered up from it. No update run is needed, so a
torn state costs less than a clean cut.

They matter more with the flash rules enforced: a half-programmed cell is not erased, so
recovery code that writes to it again without erasing first is refused, as on the chip.

Honesty about what this is: the shapes are a model. Until the hardware rig has compared them
with real interrupted operations on a real STM32, a pass means "survives these plausible
shapes". Results are labelled `torn` and counted on their own line, never mixed into the
clean-cut count.

Use: `scenario.torn: true` (or a list of shapes) in the adapter, or `--torn`. Torn states
are made for each operation a clean cut was placed in front of, after all clean cuts.

Proof that torn states earn their place, measured 2026-10-11 with a seventh demo bug build,
`bug-resume_copy` ("resume instead of restart": after an interrupted install, skip the erase
and write only the halfwords still missing):
- clean cuts only, `plan: every`: 167/167 pass. A clean-cut tool calls it safe.
- with torn states: fails at `op-7 erase-half`. Half of Slot A still holds the old image, the
  resume path programs over it, and the chip refuses (`flash rule broken ... 0x0800224E`).
It takes the torn states and the flash rules together to see it.

Three-Tier v2.0.0 with torn states: 23/23 clean cuts and 59/59 torn states pass.

CI: the correct demo build and the Three-Tier run use `--torn`; `adapter.yaml` itself does
not turn it on, so a first local run stays short.
