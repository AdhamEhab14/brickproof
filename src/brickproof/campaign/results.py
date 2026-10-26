"""What a campaign returns: one result per cut, the outcome of a whole run, and that
outcome as plain data for the reports."""
import os
from dataclasses import asdict, dataclass, field

from brickproof import __version__
from brickproof import regulations
from brickproof import trace as traces


KIND_NAMES = {0: "none", 1: "erase", 2: "program"}


BASELINE = "baseline (no cut)"


@dataclass
class CutResult:
    cut: str
    fired: bool = False
    kind: str = "none"
    addr: int = 0
    op_index: int = None        # which operation of the update was cut (0 = first)
    alive: bool = False
    recovered: bool = False
    passed: bool = False
    skipped: bool = False       # an at_ops range ran past the end of the update
    baseline: bool = False      # the uninterrupted update, run before any cut
    rewound: bool = False       # a program cut whose halfword had landed and was put back
    image: str = None           # the approved image the oracle found installed
    torn: str = None            # set for a torn state: which shape (see torn.py)
    depth: int = 1              # 2 = a second cut, during the recovery from a first one
    computed: bool = False      # powered up from the computed flash state, not cut in the emulator
    content: str = None         # a content fault: which damaged image was staged (see content.py)
    link: int = None            # a broken link: how many bytes of the host's session got through
    bit_error: str = None       # bits flipped at rest: the region and where (see bit_errors.py)
    hung: bool = False          # the emulator stopped making progress, on two runs in a row
    message: str = ""
    seconds: float = 0.0


class SelfCheckFailed(RuntimeError):
    """The emulated flash is not what the golden run says it should be. Either the
    tool is wrong or the update is not the same from one run to the next; both mean
    the results cannot be trusted, so the run stops (exit code 3)."""


@dataclass
class Outcome:
    results: list               # CutResult: the baseline first, then each cut
    trace: list                 # the golden run's operations
    plan: object = None         # plan.Plan: what the trace offers and what was chosen
    depth: dict = None          # what the exploration of cuts during recovery covered
    timings: dict = field(default_factory=dict)
    started: str = ""           # when the run began, UTC
    inputs: list = field(default_factory=list)   # the firmware files tested, with their hashes
    jobs: int = 1               # how many emulators shared the work
    shard: dict = None          # set when this run made only its share of the cuts
    pre: bytes = None           # the whole flash image with the update staged, before it ran

    @property
    def passed(self):
        return all(r.passed or r.skipped for r in self.results) and any(r.passed for r in self.results)


def as_dict(outcome, adapter):
    """Everything about a run, as plain data. The JSON, JUnit and HTML reports are all
    made from this."""
    report = {
        "adapter": adapter.name,
        "adapter_file": getattr(adapter, "path", "") or "adapter.yaml",
        "target": os.path.basename(adapter.target),
        "brickproof": __version__,
        "started": outcome.started,
        "inputs": outcome.inputs,
        "oracle": bool(getattr(adapter, "oracle", None)),
        "passed": outcome.passed,
        "jobs": outcome.jobs,
        "coverage": outcome.plan.as_dict() if outcome.plan else None,
        "update": dict(traces.cost(outcome.trace, adapter.flash), timing=adapter.flash.timing)
        if outcome.trace else None,
        "depth": outcome.depth,
        "shard": outcome.shard,
        "timings": outcome.timings,
        "cuts": [asdict(r) for r in outcome.results],
    }
    report["regulations"] = regulations.evidence(report)
    return report
