# Write protection and option bytes

2026-10-11

Another place where plain emulated flash is more forgiving than the chip: a page the option
bytes write-protect can be erased and programmed in Renode. On an STM32F1 it cannot.

**Model.** The option bytes are 16 real bytes at 0x1FFFF800 (RDP, USER, Data0/1, WRP0..3, each
with its complement). As on the chip, they are loaded into `FLASH_WRPR` and `FLASH_OBR` at
reset, so a change takes effect after the next reset. An erase or a program in a protected
unit is refused with WRPRTERR, changes nothing, and is counted; the run fails with
`write protection: N ... operation(s) ... were refused, first at 0x...`. A mass erase is
refused if anything is protected. Read protection also write-protects the first unit.

**Adapter.** `flash.write_protected: [{from, size}]` and `flash.read_protected` say what the
option bytes hold when a test starts. Ranges must fit the chip's protection units (4 KB on
the F103). The demo ships with its bootloader's 8 KB locked, the Three-Tier adapter with the
Boot Manager's 16 KB locked, as deployed.

**Option bytes can be reprogrammed, and a cut can fall there.** `OPTKEYR`, `OPTER` and `OPTPG`
are implemented, and those operations are counted, traced and cut like any other. To make
that work the option bytes are part of the flash image: an image is the flash followed by the
16 bytes, so dump, restore, replay, the per-cut self-check and the planner all cover them
(`trace.locate` is the one place that maps an address into an image).

**The hazard this exposes, and models.** Reprogramming option bytes means erasing all of them
first. Erased, the RDP byte reads as "read protection on" at the next reset. If power fails
between the erase and the rewrite, the chip boots protected, and when firmware then writes the
unprotected value, the chip removes protection the only way it can: by mass-erasing the main
flash. The model does that mass erase when RDP is written to 0xA5 while protection was loaded
at reset. `bug-self_lock` (the demo locking its own pages from the bootloader) is caught by it:
cut at op 1, the device never comes back. `bug-protected_slot` (the app slot protected by
mistake) is caught at the baseline.

A fix along the way: the rewind of a program cut compared the cell with the traced value.
An option byte is traced as the chip stores it (byte plus complement), but at the moment of
the cut the cell holds what was written. It now compares with the value before the operation.

Not modelled: the USER and Data option bytes have no effect; option byte error (OPTERR) for a
bad complement is not raised.
