"""Bit errors at rest: a stored image loses a bit while the device is off.

Flash cells do fail over time. A bootloader that checks an image before it runs it notices
and refuses; one that does not runs damaged code. Each test takes the flash as the update
left it, flips `flips` bits at random (seeded, so a run can be repeated) inside one region,
powers up and looks at the CPU from outside: it must not be executing inside that region,
and not be in a fault handler. Staying in the bootloader, or running another intact image,
is a right answer.

scenario.bit_errors:
  regions   {name: [start, end]} addresses to damage (default: each image the oracle
            accepts, where it is installed)
  flips     bits flipped per test, default 1
  runs      tests per region, default 4
  seed      default 0
"""
import random

KEYS = {"regions", "flips", "runs", "seed"}


def damaged(image, base, start, end, flips, rng):
    """`image` (the whole flash image, from `base`) with `flips` bits flipped in
    [start, end): (new image, [(address, bit)])."""
    out = bytearray(image)
    where = []
    for _ in range(flips):
        addr = rng.randrange(start, end)
        bit = rng.randrange(8)
        out[addr - base] ^= 1 << bit
        where.append((addr, bit))
    return bytes(out), where


def cases(image, base, regions, flips=1, runs=4, seed=0):
    """[(name, image, (start, end))]: every damaged flash image to boot."""
    out = []
    for name, (start, end) in sorted(regions.items()):
        rng = random.Random("%s/%s" % (seed, name))
        for _ in range(runs):
            img, where = damaged(image, base, start, end, flips, rng)
            label = "%s %s" % (name, " ".join("0x%08X.%d" % w for w in where))
            out.append((label, img, (start, end)))
    return out
