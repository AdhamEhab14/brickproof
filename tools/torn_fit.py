"""Turn a torn-write kit's results (hardware/torn_f103) into what torn.py uses.

    python tools/torn_fit.py hardware/torn_f103/results/nucleo-f103rb-v2.txt [--early-us 0 --late-us 15]

For each delay of a cut erase: the share of the old 0 bits still 0, and the share of bytes
still showing one, against what that bit share predicts if every bit stays 0 on its own
(1 - (1 - p)^8 for an old 0x00 byte). For the programs: the last delay that left the
halfword untouched and the first that left it complete, and anything in between. Then the
two numbers for ERASE_MEASURED in torn.py.
"""
import argparse
import re
import sys
from collections import defaultdict

CYCLE_US = 0.125                     # the reset clock, 8 MHz HSI
PAGE_BITS = 1024 * 8

ERASE = re.compile(r"^E (\d+) (\d+) r(\d+) (\d+) (\d+) (\S+)")
PROGRAM = re.compile(r"^P (\d+) (\d+) r(\d+) (0x[0-9A-Fa-f]+) (0x[0-9A-Fa-f]+)")


def parse(lines):
    """{"erase": {delay: [(bytes FF, bits 1)]}, "program": {delay: [value]}, "cal": {...}}"""
    erase, program, cal = defaultdict(list), defaultdict(list), {}
    for line in lines:
        line = line.strip()
        if line.startswith("CAL "):
            cal = {k: int(v) for k, v in (x.split("=") for x in line.split()[1:])}
        elif m := ERASE.match(line):
            erase[int(m.group(2))].append((int(m.group(4)), int(m.group(5))))
        elif m := PROGRAM.match(line):
            program[int(m.group(2))].append(int(m.group(4), 16))
    return {"erase": dict(erase), "program": dict(program), "cal": cal}


def erase_rows(erase):
    """[(delay cycles, still-0 share of bits, share of bytes not 0xFF, predicted share)]"""
    rows = []
    for delay in sorted(erase):
        runs = erase[delay]
        p = sum(PAGE_BITS - ones for _ff, ones in runs) / (PAGE_BITS * len(runs))
        bytes_left = sum(1024 - ff for ff, _ones in runs) / (1024 * len(runs))
        rows.append((delay, p, bytes_left, 1 - (1 - p) ** 8))
    return rows


def still_zero_at(erase, us):
    """The still-0 share at the delay closest to `us` microseconds."""
    delay = min(erase, key=lambda d: abs(d * CYCLE_US - us))
    return delay, erase_rows({delay: erase[delay]})[0][1]


def program_edges(program, erased=0xFFFF, written=0x0000):
    """(last delay left untouched, first delay complete, delays with anything else)."""
    untouched = [d for d, vs in program.items() if all(v == erased for v in vs)]
    complete = [d for d, vs in program.items() if all(v == written for v in vs)]
    other = sorted(d for d in program if d not in untouched and d not in complete)
    last = max((d for d in untouched if not any(c < d for c in complete)), default=None)
    first = min((d for d in complete if last is None or d > last), default=None)
    return last, first, other


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("results", help="torn_results.txt from capture.py")
    p.add_argument("--early-us", type=float, default=0, help="delay for erase-early (default 0)")
    p.add_argument("--late-us", type=float, default=15, help="delay for erase-late (default 15)")
    args = p.parse_args(argv)
    with open(args.results, encoding="utf-8", errors="replace") as f:
        data = parse(f)
    if not data["erase"]:
        print("no erase lines in %s" % args.results, file=sys.stderr)
        return 2
    cal = data["cal"]
    if cal:
        print("uncut: erase %.1f ms, program %.1f us" % (
            cal.get("erase_cycles", 0) * CYCLE_US / 1000, cal.get("program_cycles", 0) * CYCLE_US))
    print("\nerase cut after   bits still 0   bytes not FF   predicted")
    done = None
    for delay, share, left, predicted in erase_rows(data["erase"]):
        if share == 0 and done is None:
            done = delay
        if share:
            done = None
        print("%9.1f us     %10.4f%%   %10.1f%%   %8.1f%%" % (
            delay * CYCLE_US, 100 * share, 100 * left, 100 * predicted))
    if done is not None:
        print("from %.1f us on, every page was fully erased" % (done * CYCLE_US))
    if data["program"]:
        last, first, other = program_edges(data["program"])
        print("\nprogram: untouched up to %s, complete from %s%s" % (
            "%.3f us" % (last * CYCLE_US) if last is not None else "-",
            "%.3f us" % (first * CYCLE_US) if first is not None else "-",
            "; partly written at %s" % ", ".join("%.3f us" % (d * CYCLE_US) for d in other)
            if other else "; never partly written"))
    early_d, early = still_zero_at(data["erase"], args.early_us)
    late_d, late = still_zero_at(data["erase"], args.late_us)
    print("\nfor torn.py:")
    print('ERASE_MEASURED = {"erase-early": %.4f, "erase-late": %.4f}   # at %.1f us and %.1f us'
          % (early, late, early_d * CYCLE_US, late_d * CYCLE_US))
    return 0


if __name__ == "__main__":
    sys.exit(main())
