"""The golden-run trace: every flash operation of one uninterrupted update.

The flash model records it (see models/ and RenodeSession.trace_stop). Here it is saved,
replayed to any point, and folded into phases: runs of operations that do the same thing
to neighbouring addresses. A 20,000-operation update is a handful of phases, and a power
cut anywhere inside one phase leaves the same kind of state behind.

An operation is a dict: index, kind (erase / mass_erase / program / refused / protected),
addr, and for a program its value and its size in bytes. Chips differ in both of the
things that matter here: what an erase wipes (a 1 KB page on an STM32F1, a sector of 16
to 128 KB on an F4) and how much a program writes (a halfword, or a byte, a word, a
double word). Nothing below assumes either; `locate` and `size_of` are where they are asked.
"""
import json
from dataclasses import dataclass


def size_of(op, flash):
    """How many bytes a program wrote: recorded with the operation, or the chip's usual unit."""
    return op.get("size") or flash.write_unit


def locate(addr, flash):
    """(offset, erase size) of an address in a flash image: where it sits, and how much an
    erase there wipes. The image is the flash, then the option bytes where the chip has
    them; erasing those wipes all of them."""
    ob = getattr(flash, "ob_base", None)
    if ob is not None and addr >= ob:
        return flash.size + (addr - ob), flash.ob_size
    _, size = flash.unit_at(addr)
    return addr - flash.base, size


def erase_start(addr, flash):
    """The address an erase of the unit holding `addr` starts at."""
    ob = getattr(flash, "ob_base", None)
    if ob is not None and addr >= ob:
        return ob
    return flash.unit_at(addr)[0]


@dataclass
class Phase:
    first: int          # index of its first operation
    last: int
    kind: str           # erase / mass_erase / program
    start: int          # address of the first operation
    end: int            # address of the last one
    next: int = None    # where the next operation must be for the phase to go on

    @property
    def count(self):
        return self.last - self.first + 1


def phases(ops, flash):
    """Group consecutive operations that walk forward through flash: erases unit by unit,
    programs one write after the other."""
    out = []
    for op in ops:
        if op["kind"] == "program":
            after = op["addr"] + size_of(op, flash)
        else:
            start = erase_start(op["addr"], flash)
            after = start + locate(start, flash)[1]
        p = out[-1] if out else None
        if p and p.kind == op["kind"] and op["addr"] == p.next:
            p.last, p.end, p.next = op["index"], op["addr"], after
        else:
            out.append(Phase(op["index"], op["index"], op["kind"], op["addr"], op["addr"], after))
    return out


def describe(ops, flash):
    """The phases as text lines, for the terminal."""
    lines = []
    for p in phases(ops, flash):
        where = "0x%08X" % p.start if p.count == 1 else "0x%08X .. 0x%08X" % (p.start, p.end)
        idx = "op %d" % p.first if p.count == 1 else "ops %d-%d" % (p.first, p.last)
        lines.append("%-16s %-10s %6d  %s" % (idx, p.kind, p.count, where))
    return lines


def write_jsonl(ops, path):
    """One operation per line: index, kind, addr, and value for a program. Addresses
    and values are hex strings, so the file reads well and diffs well."""
    with open(path, "w", newline="\n") as f:
        for op in ops:
            row = {"index": op["index"], "kind": op["kind"], "addr": "0x%08X" % op["addr"]}
            if "value" in op:
                row["value"] = "0x%0*X" % (2 * op.get("size", 2), op["value"])
            if op.get("inferred"):
                row["inferred"] = True
            f.write(json.dumps(row) + "\n")


def value_before(ops, index, pre, flash):
    """What was at ops[index]'s address just before that operation, over as many bytes
    as it writes: what the last earlier program put there, all ones if its unit was
    erased since, else what the flash image `pre` held before the update started."""
    addr = ops[index]["addr"]
    size = size_of(ops[index], flash)
    for i in range(index - 1, -1, -1):
        op = ops[i]
        if op["kind"] == "program":
            if op["addr"] == addr and "value" in op and size_of(op, flash) == size:
                return op["value"]
        elif op["kind"] == "mass_erase" and addr < flash.base + flash.size:
            return (1 << (8 * size)) - 1
        elif op["kind"] == "erase" and op["addr"] == erase_start(addr, flash):
            return (1 << (8 * size)) - 1
    off, _ = locate(addr, flash)
    return int.from_bytes(pre[off:off + size], "little")


class Replay:
    """Flash as it is just before operation n: the image before the update with the
    first n traced operations applied. Asking for growing n is cheap (it continues
    from where it was), which is how a campaign walks through an update.

    A program stores the value the flash model recorded, which is what ended up in the
    cell (on a chip that can only clear bits, that is already the AND with what was
    there). Operations the chip refused change nothing.
    """

    def __init__(self, pre, ops, flash):
        self.pre, self.ops, self.flash = pre, ops, flash
        self.n = 0
        self.image = bytearray(pre)

    def at(self, n):
        if n < self.n:
            self.n, self.image = 0, bytearray(self.pre)
        for op in self.ops[self.n:n]:
            if op["kind"] == "erase":
                off, size = locate(erase_start(op["addr"], self.flash), self.flash)
                self.image[off:off + size] = bytes([0xFF]) * size
            elif op["kind"] == "mass_erase":
                self.image[:self.flash.size] = bytes([0xFF]) * self.flash.size
            elif op["kind"] == "program" and "value" in op:
                off, _ = locate(op["addr"], self.flash)
                size = size_of(op, self.flash)
                self.image[off:off + size] = op["value"].to_bytes(size, "little")
        self.n = n
        return self.image
