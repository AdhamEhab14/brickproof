# The torn-write kit in the repository

2026-10-15

`hardware/torn_f103` is the v2 firmware that gave the 2026-10-14 measurements, the binary that
ran (rebuilt with another compiler the bytes differ, so the measured one is kept), and both
runs' results. `tools/torn_fit.py` reads a run: per delay, the share of old 0 bits still 0 and
the share of bytes showing one against what independent bits predict; where the program goes
from untouched to complete. On the v2 run it gives 4.50% at 0 us and 0.35% at 15 us, the
values in `torn.py`, and a test keeps the two in step. The same reading will take the F411 and
nRF52840 kits (plan item 29) once they exist.
