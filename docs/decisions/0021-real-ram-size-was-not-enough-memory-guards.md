# Real RAM size was not enough: memory guards

2026-10-10

Experiment: the demo bootloader with the bench bug put back (`ldmia sp!, {r4, lr}` right
after `msr msp`, the same instruction the other bootloader had) boots its app with 256 MB of
RAM, and ALSO with the real 20 KB. Renode answers a read of unmapped memory with 0 and
carries on. Silicon bus-faults. So shrinking RAM is necessary but does not catch the bug.

Fix: every range that does not exist on the chip gets a `mem_guard` Python peripheral
(F103: end of RAM up to 0x22000000, end of flash up to 0x1FFF0000). Any access stops the CPU
and latches the address and PC in the flash model's test registers (0x118, 0x11C). The runner
reads the latch before each reset (a reset clears it) and fails the run with
"bus fault: the firmware touched 0x20005000 (PC 0x080000C4)".

Limits, stated plainly:
- Stopping the CPU is not what silicon does (it takes the BusFault/HardFault vector). Firmware
  that recovers from bus faults on purpose would be judged wrongly. None of our targets does.
- Only the holes next to RAM and flash are guarded. A peripheral that Renode does not model
  is NOT a hole (it exists on the chip), so it is not guarded.
