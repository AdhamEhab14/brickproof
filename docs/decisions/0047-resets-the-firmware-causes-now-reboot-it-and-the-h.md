# Resets the firmware causes now reboot it, and the hardware watchdog

2026-10-12

**A reset made inside the emulator left the device dead.** Found while modelling the
watchdog. When the engine resets the machine it also sets the CPU's vector table to the
flash base, because Renode's Cortex-M starts with it at address 0, where an STM32 has its
flash aliased and Renode's platforms have nothing. A reset the emulator makes by itself (a
watchdog, a firmware reset request) got no such follow-up. Measured on both chips with a
bootloader that sits in its "no image" loop under a hardware watchdog: after the first
reset, vector table 0x00000000, PC 0xEFFFFFFE (locked up), no second boot banner.

Fix: Renode runs a per-machine `reset` macro after every machine reset. The session now
defines it (vector table, then the adapter's `reset:` lines). Same test afterwards: the
banner repeats every 0.4 s on the F103 and every 0.5 s on the F411.

What this had been hiding: the Three-Tier self-update ends with the firmware resetting
itself, and what the Boot Manager does after that reset never ran. The golden trace went
from 20,527 operations to 20,574: the state page is rewritten (one erase, six programs) and
Slot B is erased (40 pages). Those 47 operations are now part of the trace and get cut like
the rest. Every earlier Three-Tier result, including the exhaustive run, covers the update up
to that reset and not the tail after it.

**The hardware watchdog.** The USER option byte's WDG_SW bit is now honoured. With it cleared
(`flash.hardware_watchdog: true`), a handler on the machine's reset event starts the
independent watchdog after every reset, before the first instruction, as the chip does.
Renode's own watchdog model does the counting; the F103 platform gets one (the stock file has
none, 40 kHz LSI), the F411's is the stock one (32 kHz). Checked by stopping the CPU right
after reset: 3 watchdog resets in 1.5 s on the F103, 2 on the F411, none with the option off.
A reset while the power is "off" after a cut does not wake the device: a halted CPU stays
halted across a machine reset (checked: no flash change, no operation, no banner in 1.5 s).

OBR on the F1 now shows the USER and Data bytes as loaded at reset, where it used to read
as all ones.

Together with flash timing this makes a classic visible. The demo is now watchdog-aware (the
app and the bootloader feed it, and the bootloader gives it its longest timeout before
erasing). `f411-bug-watchdog` leaves that last step out: a 128 KB sector erase takes a
second, the watchdog waits half a second, the chip stands still for the erase and is reset
in the middle of it, and the next boot starts the same erase again. It fails the baseline.
`watchdog` and `f411-watchdog` are the correct build on a device with a hardware watchdog
and must pass every cut. The F103 has no bug build for this: its page erases are a tenth of
the watchdog's timeout.

The Three-Tier adapter used to map plain memory over the watchdog's registers. It now gets
the real one. The bootloader passes with it.

Not modelled: the other two USER bits (nRST_STOP, nRST_STDBY: whether entering a low-power
mode resets the chip), because Renode does not model those modes for these chips. And a
reset in the middle of an erase leaves the erase finished here, where the chip would leave
the sector half erased; the torn states cover that shape, but only at the cuts, not at a
watchdog reset.
