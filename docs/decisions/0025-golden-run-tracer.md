# Golden-run tracer

2026-10-10

With the trace register set, the flash model appends every operation to a file: `E addr`,
`P addr value`. An erase knows its address. A program does not: the CPU writes the halfword
straight into flash memory, so when PG is cleared the model compares flash with a shadow copy
to find what changed (the page being filled first, then every page by fingerprint, which is
native code). A program that writes what is already there changes nothing; its address is
then inferred as "the next halfword" and marked `inferred`.

Cost: demo 168 ops in 1 s. Three-Tier FBL self-update 20,527 ops in 33 s (434 s before the
fingerprints). Note the count: the SBL copies the whole 40 KB region, padding included, so
the update is 20,527 operations, not the 11,900 estimated on 2026-10-09 from the image size.

`brickproof trace adapter.yaml` prints the update as phases (runs of operations walking
forward through flash). The demo is six: erase the spare floor page, write the floor record,
erase Slot A, copy the body, copy the header, clear the staged magic. Phases are the
equivalence classes the cut planner will sample from.

Limit: an operation is counted when PG goes from 0 to 1. Firmware that keeps PG set across
several halfwords would have them counted as one. Both targets clear PG each time (so does
ST's HAL).
