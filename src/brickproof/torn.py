"""Torn operations: power lost in the middle of an erase or a program.

A clean cut falls between two operations. A real one can fall inside one, and then
the cells are left half way:

  erase    moves bits from 0 to 1. Cut short, some of a page's 0 bits have flipped
           and some have not. Bits that were already 1 stay 1.
  program  moves bits from 1 to 0. Cut short, some of the halfword's bits that were
           due to become 0 have, and some have not.

Both rules are what flash cells do. Which bits get there first was measured on a real
STM32F103 (a Nucleo-F103RB, 2026-10-14), with an erase or a program stopped by a reset
at a known number of cycles, three times each:

  erase    every bit that is still 0 goes to 1 on its own, and the slow ones are the
           same cells every time. Stopped at once, 4.5% of the old 0 bits were still 0
           (31% of the bytes showed one, nearly all of them a single bit); 15 us later
           0.35%; after 50 us of a 22 ms erase, none. The page is never left half done
           in one piece. `erase-early` and `erase-late` are those two measurements.
  program  a halfword was untouched up to 0.5 us and complete from 0.6 us: no torn
           program was seen.

An EEPROM page write is both, in one internal cycle: the chip erases the bytes it was
given (0 bits to 1), then writes them (1 bits to 0), every byte of the page at once. Cut
short, `page-erasing` has some of the old 0 bits flipped, `page-erased` all of them and
nothing written yet, `page-writing` some of the bits the new value clears cleared. Unlike a
flash program the result need not be old AND new: an old record can come back as 0xFF.
Models too; nothing was measured on an EEPROM.

A reset is not a power loss, which lets the supply sag rather than stopping the
operation cleanly, so the other shapes stay as harder cases: a clean half, a scattered
random part, an almost-finished one, and the torn programs. They are models, not
measurements, and the report says "torn" for all of them.

A torn state is built, not provoked: the flash just before the operation comes from
replaying the golden run (checked against real cuts on every one of them), and the
half-done operation is applied to that image. The device is then powered up from it.
"""
import random
from dataclasses import dataclass

from brickproof import trace as traces

ERASE_KINDS = ("erase-early", "erase-late", "erase-half", "erase-partial", "erase-almost")
# measured (see the top): the chance an old 0 bit is still 0 when the erase is stopped
ERASE_MEASURED = {"erase-early": 0.045, "erase-late": 0.0035}
PROGRAM_KINDS = ("program-low", "program-high", "program-partial")
PAGE_KINDS = ("page-erasing", "page-erased", "page-writing")
KINDS = ERASE_KINDS + PROGRAM_KINDS + PAGE_KINDS


@dataclass
class TornState:
    kind: str               # one of KINDS
    op_index: int
    addr: int               # the page, or the halfword
    image: bytes            # the whole flash to boot from


def _rng(seed, op_index, kind):
    # the same seed gives the same states on every run and every machine
    return random.Random("%s/%d/%s" % (seed, op_index, kind))


def _torn_erases(page_bytes, rng):
    """{kind: bytes} for a page whose erase was cut short. Every result keeps the bits
    that were already 1 and has at least as many 1 bits as before."""
    n = len(page_bytes)
    half = bytes([0xFF]) * (n // 2) + page_bytes[n // 2:]
    partial = bytes(b | rng.getrandbits(8) for b in page_bytes)
    # nearly done: one byte in 64 still holds its old value
    almost = bytes(b if i % 64 == 17 else 0xFF for i, b in enumerate(page_bytes))
    out = {"erase-half": half, "erase-partial": partial, "erase-almost": almost}
    # measured: each old 0 bit stays 0 on its own with probability p. Drawn after the
    # shapes above, so their bytes are what they were before these were added.
    for kind, p in ERASE_MEASURED.items():
        out[kind] = bytes(0xFF & ~sum(1 << i for i in range(8)
                                      if not (b >> i) & 1 and rng.random() < p)
                          for b in page_bytes)
    return out


def _torn_programs(old, target, rng, size=2):
    """{kind: value} for a cell of `size` bytes whose program from `old` to `target` was
    cut short. The finished cell would hold old & target; a torn one has cleared only
    some of the bits on the way there: those in its low half, those in its high half,
    a random part of them."""
    bits = 8 * size
    full = (1 << bits) - 1
    low_half = (1 << (bits // 2)) - 1
    done = old & target
    todo = old & ~target & full             # the bits this program has to clear
    low = old & ~(todo & low_half) & full
    high = old & ~(todo & (full ^ low_half)) & full
    partial = old & ~(todo & rng.getrandbits(bits)) & full
    out = {"program-low": low, "program-high": high, "program-partial": partial}
    return {k: v for k, v in out.items() if v not in (old, done)}


def _torn_pages(old, new, rng):
    """{kind: bytes} for EEPROM bytes whose write from `old` to `new` was cut short:
    in the erase half of the cycle, after it, or in the write half. Every bit gets there on
    its own, with even odds."""
    erasing = bytes(b | rng.getrandbits(8) for b in old)
    writing = bytes(0xFF & ~(~w & rng.getrandbits(8)) for w in new)
    return {"page-erasing": erasing, "page-erased": bytes([0xFF]) * len(new), "page-writing": writing}


def states(op, before, flash, kinds=KINDS, seed=0):
    """The torn states of one traced operation. `before` is the whole flash just before
    it. States equal to the flash before or after the operation are left out (those
    are the clean cuts), and so are duplicates of each other."""
    off, unit = traces.locate(op["addr"], flash)
    if op["kind"] == "erase":
        off, unit = traces.erase_span(op, flash)
    out, seen = [], set()

    def add(kind, image):
        if kind in kinds and image != before and image not in seen:
            seen.add(image)
            out.append(TornState(kind, op["index"], op["addr"], image))

    if op["kind"] == "erase":
        page = bytes(before[off:off + unit])
        after = bytes([0xFF]) * unit
        for kind in ERASE_KINDS:
            torn = _torn_erases(page, _rng(seed, op["index"], kind))[kind]
            if torn != after:
                add(kind, bytes(before[:off]) + torn + bytes(before[off + unit:]))
    elif op["kind"] == "program" and "value" in op and traces.in_eeprom(op["addr"], flash):
        size = traces.size_of(op, flash)
        old = bytes(before[off:off + size])
        new = op["value"].to_bytes(size, "little")
        for kind in PAGE_KINDS:
            torn = _torn_pages(old, new, _rng(seed, op["index"], kind))[kind]
            if torn != new:
                add(kind, bytes(before[:off]) + torn + bytes(before[off + size:]))
    elif op["kind"] == "program" and "value" in op:
        size = traces.size_of(op, flash)
        old = int.from_bytes(before[off:off + size], "little")
        for kind in PROGRAM_KINDS:
            torn = _torn_programs(old, op["value"], _rng(seed, op["index"], kind), size)
            if kind in torn:
                add(kind, bytes(before[:off]) + torn[kind].to_bytes(size, "little")
                    + bytes(before[off + size:]))
    return out
