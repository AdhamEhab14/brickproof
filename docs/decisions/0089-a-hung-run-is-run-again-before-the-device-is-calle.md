# A hung run is run again before the device is called locked up

2026-10-23

The F411 MCUboot shards failed four times in about 56 runs with "the device locked up" on
the baseline, after 318 s, while the same commit passed on the other shards in 75 s. 318 s
is one one-second slice reaching its 300 s limit (50 times the starting guess of 6 s per
emulated second, which a CI runner never measures above) plus the 18 s it takes to kill
Renode and start a fresh one. So it was one slice, not a slow run.

A probe on CI ran the baseline 64 times with three emulators up, timing every slice and
looking at Renode's threads while one ran long. Two slices took 430 and 565 s where 7 to 21
s is usual for that runner; both finished, and the update then passed. During them the
runner was 97% idle and Renode's CPU thread ran at about 5% of one core, sleeping on a
futex in between: the usual amount of work, spread over twenty-five times the time. Not a
slow machine and not dead firmware; something inside Renode holds the CPU thread back. It
happened in first and in fourth runs of a process, early and late in the update.

The same probe showed Renode pacing virtual time against the host clock: unless told to
advance immediately, it will not let virtual time get ahead of host time, and host time
counts only while emulation runs. A flash model skips a whole sector erase at once, so every
first update spent two slices asleep for exactly one second each. The session now sends
`emulation SetGlobalAdvanceImmediately true` (Renode's own tests do the same); nothing here
measures wall time. It did not stop the long stalls: three in 64 runs with it.

What does: a run that hangs (a cut, the baseline, a torn state, a content or bit-error
image, a broken link, a second cut) is run once more on the fresh emulator the hang left,
and only a second hang is reported. Renode replays a run exactly, so firmware that locks up
does it again and is still caught; a stall that hits one run in twenty hits two in a row
about one time in four hundred. The cost falls on real lock-ups, which take twice as long
to report; the bug demos that expect one stop at the first (`--fail-fast`), so that is one
extra wait per job. Results keep a `hung` flag.

Not done: finding what holds Renode's CPU thread back. The hang limit stays at fifty times.
