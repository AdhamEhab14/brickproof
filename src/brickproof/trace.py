"""The golden-run trace: every flash operation of one uninterrupted update.

The flash model records it (see models/stm32f1_flash.py and RenodeSession.trace_stop).
Here it is saved, and folded into phases: runs of operations that do the same thing
to neighbouring addresses. A 20,000-operation update is a handful of phases, and a
power cut anywhere inside one phase leaves the same kind of state behind.
"""
import json
from dataclasses import dataclass


@dataclass
class Phase:
    first: int          # index of its first operation
    last: int
    kind: str           # erase / mass_erase / program
    start: int          # address of the first operation
    end: int            # address of the last one

    @property
    def count(self):
        return self.last - self.first + 1


def phases(ops, page, unit=2):
    """Group consecutive operations that walk forward through flash: erases page by
    page, programs write-unit by write-unit."""
    out = []
    for op in ops:
        step = unit if op["kind"] == "program" else page
        p = out[-1] if out else None
        if p and p.kind == op["kind"] and op["addr"] == p.end + step:
            p.last, p.end = op["index"], op["addr"]
        else:
            out.append(Phase(op["index"], op["index"], op["kind"], op["addr"], op["addr"]))
    return out


def describe(ops, page, unit=2):
    """The phases as text lines, for the terminal."""
    lines = []
    for p in phases(ops, page, unit):
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
                row["value"] = "0x%04X" % op["value"]
            if op.get("inferred"):
                row["inferred"] = True
            f.write(json.dumps(row) + "\n")


def value_before(ops, index, pre, flash_base, page):
    """The halfword at ops[index]'s address as it was just before that operation:
    what the last earlier program put there, 0xFFFF if its page was erased since,
    else what the flash image `pre` held before the update started."""
    addr = ops[index]["addr"]
    for i in range(index - 1, -1, -1):
        op = ops[i]
        if op["kind"] == "program":
            if op["addr"] == addr and "value" in op:
                return op["value"]
        elif op["kind"] == "mass_erase" or (op["kind"] == "erase" and op["addr"] == addr & ~(page - 1)):
            return 0xFFFF
    off = addr - flash_base
    return pre[off] | (pre[off + 1] << 8)


class Replay:
    """Flash as it is just before operation n: the image before the update with the
    first n traced operations applied. Asking for growing n is cheap (it continues
    from where it was), which is how a campaign walks through an update.

    A program stores its value as the emulator does. Real flash can only clear bits,
    but firmware only programs erased cells (or writes 0), where the two agree.
    """

    def __init__(self, pre, ops, flash_base, page):
        self.pre, self.ops, self.base, self.page = pre, ops, flash_base, page
        self.n = 0
        self.image = bytearray(pre)

    def at(self, n):
        if n < self.n:
            self.n, self.image = 0, bytearray(self.pre)
        for op in self.ops[self.n:n]:
            off = op["addr"] - self.base
            if op["kind"] == "erase":
                self.image[off:off + self.page] = b"\xFF" * self.page
            elif op["kind"] == "mass_erase":
                self.image[:] = b"\xFF" * len(self.image)
            elif op["kind"] == "program" and "value" in op:     # a refused one changes nothing
                self.image[off] = op["value"] & 0xFF
                self.image[off + 1] = op["value"] >> 8
        self.n = n
        return self.image
