"""The cut planner: which operations to cut at, and what that covers.

When power is lost, RAM and the CPU state go with it. All that is left is flash. So
two cuts that leave the same flash contents are the same test, exactly, and the
planner only ever cuts at distinct flash states. An operation that changes nothing
(programming a value already there, erasing a page already erased) adds no state.
In a real update that is a large share: a copy of a 40 KB region whose image is
24 KB programs 0xFFFF over erased flash thousands of times.

That reduction is exact. Choosing fewer cuts than there are distinct states is not:
inside a long run of operations (a copy), the planner can take the edges plus evenly
spaced samples, on the argument that recovery treats "k halfwords copied" the same
for most k. That is a judgement, and the plan says where it was applied, so a result
never claims more than was run. `every` cuts at every distinct state: exhaustive for
a single power loss at operation boundaries.
"""
from dataclasses import dataclass, field

from brickproof import trace as traces

MODES = ("phases", "every")


@dataclass
class PhasePlan:
    phase: traces.Phase
    distinct: int               # flash states that begin inside this phase
    cuts: list                  # operation indexes chosen in it

    @property
    def complete(self):
        return len(self.cuts) == self.distinct


@dataclass
class Plan:
    mode: str
    operations: int
    phases: list = field(default_factory=list)

    @property
    def cuts(self):
        return [n for p in self.phases for n in p.cuts]

    @property
    def distinct(self):
        return sum(p.distinct for p in self.phases)

    @property
    def exhaustive(self):
        return all(p.complete for p in self.phases)

    def summary(self):
        text = "%d cut(s) over %d distinct flash states (%d operations)" % (
            len(self.cuts), self.distinct, self.operations)
        if self.exhaustive:
            return text + ": every state is cut"
        sampled = sum(1 for p in self.phases if not p.complete)
        return text + ": %d of %d phases are sampled, the rest cut at every state" % (
            sampled, len(self.phases))

    def lines(self):
        out = []
        for p in self.phases:
            ph = p.phase
            idx = "op %d" % ph.first if ph.count == 1 else "ops %d-%d" % (ph.first, ph.last)
            where = "0x%08X" % ph.start if ph.count == 1 else "0x%08X .. 0x%08X" % (ph.start, ph.end)
            cover = "all" if p.complete else "%d sampled" % len(p.cuts)
            out.append("%-16s %-10s %6d ops %6d states  cut %-11s %s" % (
                idx, ph.kind, ph.count, p.distinct, cover, where))
        return out

    def as_dict(self):
        return {"mode": self.mode, "operations": self.operations, "distinct_states": self.distinct,
                "cuts": len(self.cuts), "exhaustive": self.exhaustive,
                "phases": [{"first": p.phase.first, "last": p.phase.last, "kind": p.phase.kind,
                            "start": "0x%08X" % p.phase.start, "end": "0x%08X" % p.phase.end,
                            "distinct_states": p.distinct, "cuts": len(p.cuts)} for p in self.phases]}


def changes(ops, pre, flash):
    """For each operation: did it change flash? Replays the update on the image from
    before it, so an erase of an erased page and a program of the value already there
    both count as no change."""
    image = bytearray(pre)
    out = []
    for op in ops:
        if op["kind"] == "erase":
            off, size = traces.locate(op["addr"], flash)
            erased = bytes([0xFF]) * size
            out.append(image[off:off + size] != erased)
            image[off:off + size] = erased
        elif op["kind"] == "mass_erase":
            out.append(any(b != 0xFF for b in image[:flash.size]))
            image[:flash.size] = bytes([0xFF]) * flash.size
        elif op["kind"] == "program" and "value" in op:
            off, _ = traces.locate(op["addr"], flash)
            lo, hi = op["value"] & 0xFF, op["value"] >> 8
            out.append(image[off] != lo or image[off + 1] != hi)
            image[off], image[off + 1] = lo, hi
        else:
            out.append(False)           # refused, protected, or it wrote what was already there
    return out


def _sample(candidates, per_phase):
    """The two operations at each end, plus per_phase spread evenly between them."""
    n = len(candidates)
    picks = {0, 1, n - 2, n - 1}
    for i in range(1, per_phase + 1):
        picks.add(round(i * (n - 1) / (per_phase + 1)))
    return [candidates[i] for i in sorted(picks)]


def make(ops, pre, flash, mode="phases", per_phase=8, small=12):
    """Plan the cuts for a traced update.

    mode       "every": each distinct flash state. "phases": the same in short phases,
               edges plus samples in long ones
    per_phase  samples inside a long phase, besides its four edge cuts
    small      a phase with at most this many distinct states is cut at all of them
    """
    if mode not in MODES:
        raise ValueError("plan mode must be one of %s, not %r" % (", ".join(MODES), mode))
    changed = changes(ops, pre, flash)
    # cutting before op n shows a new state only if op n-1 changed something
    # (op 0 always does: it is the flash the update started from)
    new_state = [n == 0 or changed[n - 1] for n in range(len(ops))]
    plan = Plan(mode=mode, operations=len(ops))
    for ph in traces.phases(ops, flash.page, flash.write_unit):
        candidates = [n for n in range(ph.first, ph.last + 1) if new_state[n]]
        if mode == "every" or len(candidates) <= max(small, 4):
            cuts = candidates
        else:
            cuts = _sample(candidates, per_phase)
        plan.phases.append(PhasePlan(ph, len(candidates), cuts))
    return plan
