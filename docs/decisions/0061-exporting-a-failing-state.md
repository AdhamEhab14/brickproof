# Exporting a failing state

2026-10-15

Checking a finding on a board took a hand-made flash image (OpenBLT, 2026-10-13). `brickproof
export` makes it: one uninterrupted run, then the golden run replayed to just before the
operation (`trace.Replay`, the same bytes a computed cut powers up from, and checked against
every real cut). `--torn KIND` builds that operation's torn state with the adapter's seed, so
it is the state the campaign booted. The image is split the way a programmer writes it: the
flash, the option bytes (a file of their own, with a warning: a wrong value can lock the
chip), the external chip and its status registers. A state after cuts in a row has no export
command: it is the recovery's flash, and a replay of the second cut needs that first
recovery run.

The image is not run again to check it can be: that is what the campaign did.

**Checked** against the five OpenBLT images made by hand on 2026-10-13 and flashed to the
Nucleo (commit 7dfd266): with the bootloader and the program taken from the complete image,
one run of the update (3,335 operations), and the states before operations 2957, 2976, 3079
and 3148 and after the last one exported. All five are identical to the hand-made files,
byte for byte.
