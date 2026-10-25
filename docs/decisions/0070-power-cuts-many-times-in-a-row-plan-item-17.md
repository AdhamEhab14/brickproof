# Power cuts many times in a row (plan item 17)

2026-10-16

The exploration of cuts during recovery already went level by level, so depth 3 and beyond
needed no new machinery: each level's new states are the parents of the next, and a flash
state already tested is skipped. What was missing is a way to say "until nothing new turns
up": `depth: exhaustive` (or `--depth exhaustive`) runs levels until one brings no new state,
with `max_states` (2,000 by default) as the stop that keeps it finite. The report says how
deep it went.

**Checked** in Renode, this PC, 6 emulators: the demo at depth 3, 173 first cuts and 202 new
states, all recovered, 2 minutes. The Three-Tier bootloader v2.0.0 at depth 3: 37 first cuts,
10 broken links and 34 new states, all recovered, 13 minutes. The demo exhaustive stopped at
the 2,000-state limit after 20 cuts in a row, all recovered: it never runs out of new states,
because every interrupted install raises the rollback-floor record's sequence number, so each
further cut leaves flash never seen before. For such a design the limit is the answer; a
design whose recovery repeats itself exactly (the unit test's fake updater) stops at level 2.
