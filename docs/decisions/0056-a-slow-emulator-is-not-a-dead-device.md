# A slow emulator is not a dead device

2026-10-13

MCUboot's swap on the F411 is about 392,000 byte-wide programs. Its cut runs failed with
"the emulator hung before the cut fired", on four of the last cuts, and the baseline once
with "locked up". None of them was a hang. Measured, one second of emulated time at a time:

- a plain run: 13 to 19 s of wall time for each busy second, every time;
- a second run in the same Renode process, with or without a trace: most seconds the same,
  and a few, at different places each time, 95 to 201 s;
- with the step limit raised to 15 minutes the "hung" cut passed, taking 1152 s instead of
  about 150 s.

So Renode sometimes runs more than ten times slower than its usual pace for a while. The
hang limit allowed twenty times the slowest pace seen, with a fixed ceiling (180 s for a
one-second slice), and the wait for a cut never learned the pace at all: it kept the
starting guess, which gave a 0.16 s step 30 s. A step of 91 s was a "hang".

Now: fifty times the slowest pace seen (27 times was measured), no ceiling, and
`run_until_cut` learns the pace like `run_for`. A device that really locks up is still
caught; on a slow run it takes longer to say so, which costs time, not correctness. The
four cuts that had failed then passed, with three emulators side by side.
