"""Run the campaigns listed in tests/scenarios.yaml and check each one's exit code.

    python tools/scenarios.py list [--part K/N] [--emulator renode]
    python tools/scenarios.py run --part K/N --emulator renode     # what a CI job runs
    python tools/scenarios.py run --id demo-f411 --id demo-l476    # a few, by name

A part is a share of the scenarios, balanced by their `minutes`, so N jobs take about the
same time. Each campaign writes <out>/<id>.json, .xml and .html; the parity job compares
the JSON files with tests/parity/baseline.json. A campaign that runs past its time limit is
stopped and counted as failed, and the others still run, so one stuck campaign does not
lose the results of the rest.
"""
import argparse
import os
import shlex
import signal
import subprocess
import sys
import time

import yaml

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
MANIFEST = os.path.join(ROOT, "tests", "scenarios.yaml")
EMULATORS = ("renode", "m33mu")


def load(path=MANIFEST):
    with open(path, encoding="utf-8") as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    for s in scenarios:
        s.setdefault("emulator", "renode")
    return scenarios


def parse_part(text):
    k, n = (int(x) for x in text.split("/"))
    if not 1 <= k <= n:
        raise argparse.ArgumentTypeError("a part is K/N with 1 <= K <= N, not %s" % text)
    return k, n


def share(scenarios, n):
    """Split the scenarios into n parts of about the same total time: the longest first,
    each into the part with the least so far. The same list always splits the same way."""
    parts = [[] for _ in range(n)]
    totals = [0.0] * n
    for s in sorted(scenarios, key=lambda s: (-s["minutes"], s["id"])):
        i = totals.index(min(totals))
        parts[i].append(s)
        totals[i] += s["minutes"]
    return parts


def select(scenarios, part=None, emulator=None, ids=()):
    chosen = [s for s in scenarios if emulator is None or s["emulator"] == emulator]
    if ids:
        unknown = set(ids) - {s["id"] for s in scenarios}
        if unknown:
            raise SystemExit("no such scenario: %s" % ", ".join(sorted(unknown)))
        chosen = [s for s in chosen if s["id"] in ids]
    if part:
        k, n = part
        chosen = share(chosen, n)[k - 1]
    return chosen


def time_limit(s):
    """Seconds a campaign may run: three times what it took on a runner, and 10 minutes at least."""
    return max(600.0, 3 * 60 * s["minutes"] + 300)


def run_one(s, command, out):
    """Run one campaign; (exit code or None if it ran out of time, seconds)."""
    base = os.path.join(out, s["id"])
    # the adapter as the manifest writes it, relative to the repository root: the report
    # keeps that path, and the parity check knows each campaign by it
    args = command + ["run", s["adapter"]] + shlex.split(s["args"]) + [
        "--json", base + ".json", "--junit", base + ".xml", "--html", base + ".html"]
    t0 = time.time()
    # its own process group, so that running out of time stops its emulators too
    kw = {"start_new_session": True} if os.name == "posix" else {}
    proc = subprocess.Popen(args, cwd=ROOT, **kw)
    try:
        code = proc.wait(timeout=time_limit(s))
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        proc.wait()
        code = None
    return code, time.time() - t0


def summary(rows):
    lines = ["| Scenario | Expected | Exit code | Minutes | |", "|---|---|---|---|---|"]
    for s, code, secs in rows:
        verdict = "ok" if code == s["expect"] else "**WRONG**"
        lines.append("| %s | %d | %s | %.1f | %s |" % (
            s["id"], s["expect"], "timed out" if code is None else code, secs / 60, verdict))
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("list", "run"):
        c = sub.add_parser(name)
        c.add_argument("--part", type=parse_part, metavar="K/N", help="one of N balanced shares")
        c.add_argument("--emulator", choices=EMULATORS)
        c.add_argument("--id", action="append", default=[], help="only this scenario (repeatable)")
        c.add_argument("--manifest", default=MANIFEST)
    r = sub.choices["run"]
    r.add_argument("--out", default="brickproof-out", help="folder for the reports")
    r.add_argument("--command", default="brickproof", help="how to start BrickProof (default: brickproof)")
    a = p.parse_args(argv)

    chosen = select(load(a.manifest), a.part, a.emulator, a.id)
    if a.cmd == "list":
        for s in chosen:
            print("%-40s %5.1f min  expect %d  %s %s" % (
                s["id"], s["minutes"], s["expect"], s["adapter"], s["args"]))
        print("%d scenarios, %.0f minutes" % (len(chosen), sum(s["minutes"] for s in chosen)))
        return 0

    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    rows = []
    for i, s in enumerate(chosen, 1):
        print("\n=== [%d/%d] %s: brickproof run %s %s (expect %d)" % (
            i, len(chosen), s["id"], s["adapter"], s["args"], s["expect"]), flush=True)
        code, secs = run_one(s, shlex.split(a.command), out)
        rows.append((s, code, secs))
        ended = "timed out" if code is None else "exit code %d" % code
        print("=== %s: %s in %.1f min, expected %d" % (s["id"], ended, secs / 60, s["expect"]), flush=True)
    table = summary(rows)
    print("\n" + table)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(table + "\n")
    wrong = [s["id"] for s, code, _ in rows if code != s["expect"]]
    if wrong:
        print("\nnot as expected: " + ", ".join(wrong))
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
