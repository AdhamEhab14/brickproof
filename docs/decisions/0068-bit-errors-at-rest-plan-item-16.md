# Bit errors at rest (plan item 16)

2026-10-16

Flash cells lose charge over the years, and a bit in a stored image can flip while the device
is off. The test takes the flash the uninterrupted update left (the golden run replayed to its
end), flips seeded random bits in one region, powers up and samples the CPU from outside: it
must not execute inside that region, and must not be in a fault handler. Refusing to boot
counts as right, because running damaged code is the failure that matters.

The first run used the whole of each accepted image as the region and failed the correct demo
on 3 of 4 flips. All three were in the 0x1F0 bytes of padding between the demo's 16-byte header
and its body at +0x200, which nothing reads and its CRC does not cover: the image there is as
good as before. So the demo adapters name header and body. MCUboot hashes its whole header
area, so its default regions are right.

**Checked** in Renode: the demo on the F103, F411 and nRF52 refuses all 8 (4 in the header, 4 in
the body) and stays in its bootloader; `bug-trust_header` (magic only) runs every damaged body
(one run stored to flash from the damaged code, which the flash rules caught); MCUboot on the
F411 and the nRF52840 refuses all 4 on each.
