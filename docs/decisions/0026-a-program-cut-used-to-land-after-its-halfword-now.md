# A program cut used to land AFTER its halfword. Now it lands before.

2026-10-10

Found when the trace put addresses on cut results. The model halts the CPU when PG is set,
but Renode finishes the instruction block it is in, and the store of the halfword is in that
block. Measured on the demo: 17 of 17 program cuts had already written their halfword.

Why it matters: an erase cut stops before the erase. So with program cuts landing after, the
state "page erased, nothing programmed yet" was never tested, and every result was labelled
one operation early.

Fix: after a program cut fires, the runner looks up the operation in the golden run. If the
halfword is in flash, it writes back the value that was there before (`trace.value_before`).
Every cut now means exactly "just before op N". The state after the last operation is the
baseline's.

Correction to the entry "Demo results" above: `bug-naive_floor` was said to fail at op 158
because "the floor page was erased, not yet rewritten". Wrong. In that build ops 151 to 158
copy the header, 159 and 160 clear the staged magic, and the floor page is erased at 161.
The cut "at 158" had landed after the last header halfword: install complete, floor still
at 1, so v1 is accepted again. Same bug, wrong description, and the reason was this landing
problem.
