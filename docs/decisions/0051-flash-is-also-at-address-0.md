# Flash is also at address 0

2026-10-12

Found the first time a bootloader that is not ours was run. An STM32 that boots from its main
flash shows that flash at address 0 as well as at 0x08000000, and some firmware uses the
low address: wolfBoot's STM32F4 port programs through it. The platforms had flash at one
address only. On the F411 nothing was mapped at 0, so those stores went nowhere, the flash
model saw erases and no programs, and the update could not work. On the F103 Renode's stock
file maps one huge memory from 0, so a store at 0x00002000 landed in different bytes from
0x08002000.

Now the flash memory is registered at both addresses (one memory, so a read, a store or an
instruction fetch at either address is the same byte), it has its real size on both chips,
and a store through the low address while PG is set is a program like any other. The gap
between the end of the alias and 0x08000000 is guarded like the other holes, where the F103
used to read zeros. Both demos give the same traces as before.

This is the kind of gap the demo and our own bootloader could never show, because both
were written by people who knew what the emulator had.
