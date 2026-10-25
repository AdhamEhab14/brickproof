# Reset during an erase is covered by the torn states (plan item 3)

2026-10-16

The plan: when a watchdog or the firmware resets the chip during an erase, apply the measured
torn shape if the reset falls in its first 50 us, else finish the erase. Both halves are
already what happens. The measured shapes (`erase-early`, 4.5% of old 0 bits still 0, and
`erase-late`, 0.35%) were measured with exactly that, a reset at a counted cycle (the torn
kit, 2026-10-14), and every `--torn` campaign applies them at every erase. From 50 us on the
measurement found the page fully erased, which is what the models do when a reset comes
after the erase. So the flash a mid-erase reset leaves is already among the states tested.

What a reset adds over a power cut is that RAM survives it. That only matters to firmware
that keeps state in RAM across a reset (a `.noinit` variable), which the Standby work above
now covers where it matters most. The plan's acceptance case, a demo bug that resets in the
middle of an erase, is `f411-bug-watchdog` (a one-second sector erase under a half-second
hardware watchdog), caught in CI since 2026-10-11.

A separate path would only be needed if a real power loss turns out to tear an erase
differently from a reset: that is the power-cut rig's question (item 27), not this one's.
