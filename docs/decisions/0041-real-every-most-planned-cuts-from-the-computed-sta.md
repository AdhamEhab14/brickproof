# `real_every`: most planned cuts from the computed state

2026-10-11

On a long update most of a cut's time is running the update up to the cut. Every cut made in
the emulator has its flash compared with the golden run replayed to that point, and they have
always matched. So with `plan: {real_every: N}` (or `--real-every N`) only every Nth planned
cut, plus the last, is made in the emulator; the others are powered up from the replayed
state. The real ones keep the check running through the whole campaign, and the report says
how many of each there were. A listed cut with an `expect` is always made for real.
