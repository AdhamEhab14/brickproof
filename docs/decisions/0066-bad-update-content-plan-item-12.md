# Bad update content (plan item 12)

2026-10-16

A bootloader that survives every power cut can still run an image that is wrong. Content
faults stage damaged versions of the update and let it run to the end. Judging uses only the
oracle and the driver's `alive()`: the image named by `keep` must still be installed, and the
CPU running inside it. The driver's own recovery check is not used, because it expects the
update to have happened.

The mutations are generic, so they need no knowledge of the image format: truncation (at a
quarter, a half, three quarters, and four bytes short, the rest erased), one bit flipped in
the middle of each region the adapter names, and an erased image. What needs the format
(another signing key, an older version, the wrong slot) comes from the adapter as finished
files (`images`). `image_size` keeps the part of the staged file after the image as it was:
MCUboot's staged image is padded to the slot with a trailer that asks for the upgrade, and
truncating that away would make MCUboot not try the image at all, which tests nothing.

**Checked** in Renode: the demo on the F103, F411 (internal and external staging) and nRF52
refuses all 7 and keeps v1; the `trust_header` bug build, which checks only the magic,
accepts 6 of 7 (all but the erased one; a truncated image left installed ran into erased
code and stored to flash, which the flash rules caught). MCUboot refuses all 8 on both boards
(F411 and nRF52840), a bit in its TLV area included. A first version cut a damaged image staged in the external
chip to nothing (it limited the copy to the internal flash's size), so `f411-ext` passed
nothing; the copy now stops at the end of the flash it is staged in.

In a sharded run only shard 1 makes the content faults: they are not cuts, and the other
shards would repeat them. Not done yet: a cut while a bad image is being checked or erased.
