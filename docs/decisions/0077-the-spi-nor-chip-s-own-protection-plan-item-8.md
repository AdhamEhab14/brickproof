# The SPI NOR chip's own protection (plan item 8)

2026-10-16

Following the W25Q16JV datasheet's status register protection table. **/WP**: the chip's
GPIO 1, active low, reads high unless `external_flash.wp` wires an MCU pin to it; with SRP set
and /WP low, status writes are refused. **SRL**: with SRP clear it locks the status
registers until the next power cycle, with SRP set for good. **Volatile writes**: after 50h
the next status write changes what is in force but not what is stored, and a power cycle goes
back to the stored value; the engine saves the stored value with the chip's contents, which
is what survives a power cut. **Individual block locks**: with WPS (status register 3) set,
BP/TB/SEC/CMP no longer count and each 64 KB block (each 4 KB sector in the bottom and top
blocks) has a lock bit, all set at power-up, changed by 36h/39h and 7Eh/98h, read by 3Dh.

Status register 3 is non-volatile, so the chip's saved state grew from two status bytes to
three (`EXT_STATUS_BYTES`); an image saved by an older version is one byte shorter. The
device's power cycle now power-cycles the chip as well (`PowerCycle`), because a reset of
the MCU alone does not reset the chip's volatile state, and a power loss does.

**Not modelled: suspend and resume** (75h/7Ah) beyond being accepted. The model finishes an
erase at once and skips its time; firmware never sees the chip busy, so there is never an
erase to suspend, and the chip ignores 75h when it is not busy. Modelling a suspended erase
needs erases that take time the firmware can see, which is a change to how every external
operation is timed; it stays a known gap until a target uses suspend.

Status writes are not counted operations (a power cut does not fall on them). They are rare
in an update, and making them operations would change the trace format.

**Checked** in Renode (tests/renode/test_spinor_rules.py, commands straight to the chip
through the monitor): SRP with /WP low refuses a status write and /WP high allows it; SRL
locks until a power cycle; a volatile write is in force but not stored and is gone after a
power cycle; with WPS every block is locked at power-up, unlock lets a program through, lock
and read-lock agree; global unlock and lock; without WPS the lock bits do not matter. The
f411-ext demo: 90/90 cuts and 268/268 torn states, its consume_first bug still caught.
