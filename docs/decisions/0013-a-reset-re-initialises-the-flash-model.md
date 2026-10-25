# A reset re-initialises the flash model

2026-10-10

Measured: after `machine Reset` the Python flash model's op counter is 0 and its cut point is
cleared. So for a boot-time update the engine resets with the machine paused (`settle=0`),
arms the cut, then lets it run. A driver says it needs this with `update_on_boot = True`.
