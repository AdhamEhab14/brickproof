# What the lock-up really is, and noticing it sooner

2026-10-11

Single-stepped the `trust_header` lock-up. The bootloader does `bx` to 0xFFFFFFFF, read from
an erased vector. Renode takes that value as an exception-return code, pops a frame from a
stack pointer that is 0xFFFFFFFC, gets zeros from memory that is not there, and lands at PC 0
with the Thumb bit clear. From there `RunFor` never returns, and Renode logs nothing. On the
chip the same jump is a fault taken while fetching the fault vector: a true lock-up. So
"the device locked up" is the right verdict; only the way of noticing is ours.

Tried and dropped: a block of "branch to self" at the top of memory, so the core would spin
with time passing. It is never reached, because of the exception-return path above.

Kept: the wall-clock limit on a slice of emulated time now follows the machine. It is twenty
times the slowest rate this session has measured (starting from a pessimistic guess), never
under 30 s and never over the old fixed allowance. A healthy slice takes a second or two, so
30 s cannot call a slow but live device dead; that would be a false failure and is worse than
waiting. A locked-up demo cut now costs 54 s instead of 114 s.
