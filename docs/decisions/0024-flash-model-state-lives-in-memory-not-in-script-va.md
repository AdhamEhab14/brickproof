# Flash model state lives in memory, not in script variables

2026-10-10

A firmware reset re-runs the Python model's `IsInit` and wiped its op count, cut point and
fault latch. For a bootloader that resets itself mid-update that meant: the baseline's op
count read 0, and a cut could not land after the reset. The test registers (0x100 to 0x124)
are now backed by a small `bpState` memory at 0x90000000, which Renode keeps across a reset.
`power_cycle()` clears them on purpose. The hardware registers (CR, keys) still reset, as on
the chip.
