# Depth 2 on the Three-Tier bootloader (measured)

2026-10-11

`depth: {levels: 2, per_phase: 0, small: 4}` on v2.0.0, local run: 23/23 clean cuts, then
13/13 new states after a second cut during the Boot Manager's recovery; 119 more second cuts
led to a state a first cut had already produced. The recovery mostly retraces the update's
own steps, which is why interrupting it again is safe. 14 minutes in all. CI, correct demo
build with `--torn --depth 2`: 167/167 clean cuts, 485/485 torn states, 95/95 deeper states
(324 known).
