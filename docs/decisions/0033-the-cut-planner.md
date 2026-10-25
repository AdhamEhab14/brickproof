# The cut planner

2026-10-11

Hand-picked cuts were the weakest part of a result: 12 cuts of a 20,527-operation update, with
no account of what the other 20,515 would have shown. `plan.py` chooses cuts from the golden
run and says what they cover.

**The exact part.** When power is lost, RAM and the CPU state go with it; only flash remains.
So two cuts that leave the same flash are the same test. The planner replays the trace and
keeps only operations that begin a new flash state: an erase of an already-erased page, or a
program of the value already there, adds none. Three-Tier FBL self-update: 20,527 operations,
11,874 distinct states. (13 of the 40 page erases hit pages that were already erased, and
8,640 programs write 0xFFFF over erased flash.) Demo: 168 operations, 167 states.

**The judgement part.** `plan: every` cuts at every distinct state: exhaustive for a single
power loss at operation boundaries. `plan: phases` does that only in short phases (12 states
or fewer). In a long one it takes the two operations at each end plus `per_phase` evenly
spaced samples, on the argument that recovery treats "k halfwords copied" alike for most k.
That is a judgement, not a proof, so the plan table says per phase whether it was "cut all"
or "N sampled", the summary says how many states exist against how many were cut, and the
JSON report carries the same under `coverage`. A result must not claim more than was run.

Demo: `plan: every`, 167 cuts. Three-Tier: `{mode: phases, per_phase: 4}`, 23 cuts (all 7
states of the Boot Manager's state page, 8 of the 27 erase states, 8 of the 11,840 copy
states). `--plan every` on Three-Tier would be 11,874 cuts, about three days at 22 s each on
one emulator; that needs parallel instances, which the design allows (cuts are independent)
but is not built yet.

Listed cuts still work and run first; a planned cut at the same operation is not repeated.
