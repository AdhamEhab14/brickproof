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


# nRF52 partial erase (ERASEPAGEPARTIAL): a page is erased once the time spent on it adds
# up to tERASEPAGE, and the bits are undefined until then. Each 0 bit needs its own share of
# that time before it reads 1, spread evenly and the same on every run. The flash model
# (models/nrf52_flash.py) has the same function.
T_PAGE_ERASE = 85000


def partial_needs(i):
    """Microseconds of partial erase bit i of a page (8 * byte offset + bit) needs."""
    h = (i * 2654435761) & 0xFFFFFFFF
    h ^= h >> 15
    return 1 + h % T_PAGE_ERASE


def partially_erased(page, total_us):
    """A page after `total_us` microseconds of partial erase."""
    if total_us >= T_PAGE_ERASE:
        return bytes([0xFF]) * len(page)
    out = bytearray(page)
    for off, b in enumerate(page):
        if b != 0xFF:
            for bit in range(8):
                if not (b >> bit) & 1 and partial_needs(8 * off + bit) <= total_us:
                    b |= 1 << bit
            out[off] = b
    return bytes(out)


def size_of(op, flash):
    """How many bytes a program wrote: recorded with the operation, or the chip's usual unit."""
    return op.get("size") or flash.write_unit


def _external(addr, flash):
    ext = getattr(flash, "ext_base", None)
    return ext is not None and ext <= addr < ext + flash.ext_size


def in_eeprom(addr, flash):
    base = getattr(flash, "eeprom_base", None)
    return base is not None and base <= addr < base + flash.eeprom_size


def locate(addr, flash):
    """(offset, erase size) of an address in a flash image: where it sits, and how much an
    erase there wipes. The image is the flash, then the option bytes where the chip has
    them (erasing those wipes all of them), then an external flash chip if there is one,
    then an I2C EEPROM (which is never erased: its unit is the page one write covers)."""
    if in_eeprom(addr, flash):
        return flash.eeprom_offset + (addr - flash.eeprom_base), flash.eeprom_page
    if _external(addr, flash):
        return flash.size + flash.ob_size + (addr - flash.ext_base), flash.ext_sector
    ob = getattr(flash, "ob_base", None)
    if ob is not None and addr >= ob:
        return flash.size + (addr - ob), flash.ob_size
    _, size = flash.unit_at(addr)
    return addr - flash.base, size


def erase_start(addr, flash):
    """The address an erase of the unit holding `addr` starts at."""
    if _external(addr, flash):
        return addr - (addr - flash.ext_base) % flash.ext_sector
    ob = getattr(flash, "ob_base", None)
    if ob is not None and addr >= ob:
        return ob
    return flash.unit_at(addr)[0]


def erase_span(op, flash):
    """(offset in the image, length) of what one traced erase wipes. An external chip has
    erase commands of several sizes, so its erases say how much they took."""
    off, size = locate(erase_start(op["addr"], flash), flash)
    return off, op.get("length") or size


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
            after = start + erase_span(op, flash)[1]
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


def cost(ops, flash):
    """What one update costs the flash: the time the chip spends erasing and programming
    (the CPU waits for all of it), and wear. Wear is counted where it is worst: the
    page or sector that is erased most often in one update."""
    erased = {}
    for op in ops:
        if op["kind"] == "program" and in_eeprom(op["addr"], flash):
            # an EEPROM has no erase: every write cycle wears the page it falls in
            page = op["addr"] - (op["addr"] - flash.eeprom_base) % flash.eeprom_page
            erased[page] = erased.get(page, 0) + 1
        elif op["kind"] == "erase" and _external(op["addr"], flash):
            # a big erase wears every sector it covers
            for a in range(op["addr"], op["addr"] + erase_span(op, flash)[1], flash.ext_sector):
                erased[a] = erased.get(a, 0) + 1
        elif op["kind"] == "erase" and op["addr"] < flash.base + flash.size:
            start = erase_start(op["addr"], flash)
            erased[start] = erased.get(start, 0) + 1
        elif op["kind"] == "mass_erase":
            for start, _ in flash.units():
                erased[start] = erased.get(start, 0) + 1
        elif op["kind"] == "partial_erase" and op.get("total_us", 0) >= T_PAGE_ERASE:
            # partial erases wear a page once they add up to a whole erase
            start = erase_start(op["addr"], flash)
            erased[start] = erased.get(start, 0) + 1
    out = {"flash_time_s": round(sum(op.get("us", 0) for op in ops) / 1e6, 6),
           "erases": sum(erased.values()), "most_erased": None, "updates_to_wear_out": None}
    if erased:
        # wear is judged against what each memory promises: the unit that uses up the
        # largest share of its endurance per update is the one that fails first
        def endurance_of(a):
            if in_eeprom(a, flash):
                return flash.eeprom_endurance
            return (flash.ext_endurance if _external(a, flash) else getattr(flash, "endurance", 0)) or 0

        def share(a):
            return erased[a] / endurance_of(a) if endurance_of(a) else 0

        addr = max(sorted(erased), key=lambda a: (share(a), erased[a]))
        out["most_erased"] = {"addr": addr, "erases_per_update": erased[addr]}
        endurance = endurance_of(addr)
        if endurance:
            out["updates_to_wear_out"] = endurance // erased[addr]
            out["endurance"] = endurance
    return out


def describe_cost(c, timing=1):
    """The same as two lines of text."""
    lines = []
    if timing:
        lines.append("flash time: the chip spends %.3f s erasing and programming (%s datasheet timings)"
                     % (c["flash_time_s"], "typical" if timing == 1 else "slowest"))
    worst = c["most_erased"]
    if worst and c.get("updates_to_wear_out"):
        lines.append("wear: 0x%08X is erased %d time(s) per update, the most of any page or sector; "
                     "at the %d cycles the datasheet promises that is %d updates"
                     % (worst["addr"], worst["erases_per_update"], c["endurance"],
                        c["updates_to_wear_out"]))
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
            if op.get("us"):
                row["us"] = op["us"]
            if op.get("length"):
                row["length"] = "0x%X" % op["length"]
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
        elif op["kind"] == "mass_erase" and (flash.base <= addr < flash.base + flash.size or (
                getattr(flash, "mass_erase_ob", False) and flash.ob_base is not None
                and flash.ob_base <= addr < flash.ob_base + flash.ob_size)):
            return (1 << (8 * size)) - 1
        elif op["kind"] == "partial_erase" and op["addr"] <= addr < op["addr"] + _wiped(op, flash):
            # bits part way through: replay up to here instead of guessing
            off, _ = locate(addr, flash)
            image = Replay(pre, ops, flash).at(index)
            return int.from_bytes(image[off:off + size], "little")
        elif op["kind"] == "erase" and op["addr"] <= addr < op["addr"] + _wiped(op, flash):
            return (1 << (8 * size)) - 1
    off, _ = locate(addr, flash)
    return int.from_bytes(pre[off:off + size], "little")


def _wiped(op, flash):
    """How many bytes from its own address a traced erase wipes."""
    return erase_span(op, flash)[1] - (op["addr"] - erase_start(op["addr"], flash))


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
                off, size = erase_span(op, self.flash)
                self.image[off:off + size] = bytes([0xFF]) * size
            elif op["kind"] == "mass_erase":
                self.image[:self.flash.size] = bytes([0xFF]) * self.flash.size
                if getattr(self.flash, "mass_erase_ob", False) and self.flash.ob_size:
                    end = self.flash.size + self.flash.ob_size
                    self.image[self.flash.size:end] = bytes([0xFF]) * self.flash.ob_size
            elif op["kind"] == "partial_erase":
                off, size = erase_span(op, self.flash)
                self.image[off:off + size] = partially_erased(bytes(self.image[off:off + size]),
                                                              op["total_us"])
            elif op["kind"] == "program" and "value" in op:
                off, _ = locate(op["addr"], self.flash)
                size = size_of(op, self.flash)
                self.image[off:off + size] = op["value"].to_bytes(size, "little")
        self.n = n
        return self.image
