# Baseline run before any cut

2026-10-10

The run now starts with the same update left to finish (`baseline (no cut)`), judged like a
cut. If it fails, no cuts are run and the exit code is 1. Reasons: a broken update makes
every cut result meaningless, and a bug that needs no power cut (like the stack one, which
faults on every boot) has to be reported somewhere. It also prints the update's operation
count. New scenario field `update_time`: virtual seconds an uninterrupted update needs.

Demo bug builds are now four: three power-loss bugs BrickProof found, plus
`bug-pop_after_switch`, the one a board found first.
