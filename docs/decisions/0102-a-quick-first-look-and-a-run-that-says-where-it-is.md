# A quick first look, and a run that says where it is

2026-10-26

Testing new firmware went: write the adapter, run it, wait. A full campaign on even the
demo is about 12 minutes; on a real update, hours. While the adapter is still being got
right, that wait is for nothing, and in the meantime the run said nothing about how far it
was.

`brickproof run --quick` makes one cut at each edge between the update's phases and one
inside each long phase, and nothing else: no torn states, second cuts, damaged images, bit
errors or broken links. On the demo that is 22 cuts in 32 seconds; it shows whether the
adapter and the update work before an hour goes on them. `--quick` and `--full` together
are refused.

In a terminal, each clean cut is followed by "cut 12 of 173, about 3 min left", counted
from the plan (a shard's share for `--shard`). A log file or CI gets one line per result as
before. A failure now ends with the command that exports its flash for a real board, next
to the one that runs it again, as the HTML report already had.
