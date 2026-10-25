# W1 speed measurement (the kill-criterion number)

2026-10-09

Local run, Windows 11, Renode 1.17.0, Three-Tier FBL self-update, 5 real cuts:
setup 26 s (boot, stage, one flash dump), then 42 to 70 s per cut, 272 s total.
Most of a cut is the Boot Manager redoing the 40 KB copy in emulation.

The update has about 11,900 flash operations (7 before the SBL, 40 erases, 11,848 halfword
programs). Cutting at every one at ~45 s each would take about 150 hours, far over the 2 h
budget in the risk table. So "every op" cannot be brute force. Options for W3, in the order
we will try them:
1. Equivalence classes: inside a uniform loop (the copy) the post-cut states differ only in
   how many halfwords landed; cut real at the loop's edges plus a sample, and use generated
   states (cheap to inject) for the rest.
2. Parallel Renode instances (cuts are already independent).
3. Move the flash model to C# so Renode snapshots work and restore is instant.
