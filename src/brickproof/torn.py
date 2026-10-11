"""Torn operations: power lost in the middle of an erase or a program.

A clean cut falls between two operations. A real one can fall inside one, and then
the cells are left half way:

  erase    moves bits from 0 to 1. Cut short, some of a page's 0 bits have flipped
           and some have not. Bits that were already 1 stay 1.
  program  moves bits from 1 to 0. Cut short, some of the halfword's bits that were
           due to become 0 have, and some have not.

Both rules are what flash cells do; which bits get there first is not knowable from
here. So each torn operation is tried as a few shapes that obey the rules: a clean
half, a scattered random part, an almost-finished one. They are models, not
measurements. Until the hardware rig has compared them with real cuts, a pass on a
torn state means "survives these plausible shapes", and the report says "torn".

A torn state is built, not provoked: the flash just before the operation comes from
replaying the golden run (checked against real cuts on every one of them), and the
half-done operation is applied to that image. The device is then powered up from it.
"""
import random
from dataclasses import dataclass

from brickproof import trace as traces

ERASE_KINDS = ("erase-half", "erase-partial", "erase-almost")
PROGRAM_KINDS = ("program-low", "program-high", "program-partial")
KINDS = ERASE_KINDS + PROGRAM_KINDS


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
    return {"erase-half": half, "erase-partial": partial, "erase-almost": almost}


def _torn_programs(old, target, rng):
    """{kind: value} for a halfword whose program from `old` to `target` was cut short.
    The finished cell would hold old & target; a torn one has cleared only some of
    the bits on the way there."""
    done = old & target
    todo = old & ~target & 0xFFFF           # the bits this program has to clear
    low = (old & ~(todo & 0x00FF)) & 0xFFFF
    high = (old & ~(todo & 0xFF00)) & 0xFFFF
    partial = old & ~(todo & rng.getrandbits(16)) & 0xFFFF
    out = {"program-low": low, "program-high": high, "program-partial": partial}
    return {k: v for k, v in out.items() if v not in (old, done)}


def states(op, before, flash, kinds=KINDS, seed=0):
    """The torn states of one traced operation. `before` is the whole flash just before
    it. States equal to the flash before or after the operation are left out (those
    are the clean cuts), and so are duplicates of each other."""
    off, unit = traces.locate(op["addr"], flash)
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
    elif op["kind"] == "program" and "value" in op:
        old = before[off] | (before[off + 1] << 8)
        for kind in PROGRAM_KINDS:
            torn = _torn_programs(old, op["value"], _rng(seed, op["index"], kind))
            if kind in torn:
                v = torn[kind]
                add(kind, bytes(before[:off]) + bytes([v & 0xFF, v >> 8]) + bytes(before[off + 2:]))
    return out
