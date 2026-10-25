"""Check that a change kept every result: the parity check behind restructuring.

Every campaign BrickProof runs in CI writes a JSON report. This reduces each report to
what decides its result (the verdict, the coverage, and each cut's outcome; no timings),
and compares a set of reports against a committed baseline:

    python tools/parity.py fingerprint <reports folder> -o tests/parity/baseline.json
    python tools/parity.py compare tests/parity/baseline.json <reports folder>

`compare` exits 1 if a scenario is missing or any result differs. A failure message that
changed on a cut that fails either way is only a warning: firmware that jumps into erased
flash can be stopped by more than one check, and which one comes first can depend on the
emulator (docs/decisions.md, 2026-10-25).

A deliberate change of results (a new chip rule, a rebuilt target) updates the baseline in
the same pull request, so the diff shows exactly what moved.
"""
import argparse
import glob
import json
import os
import sys

# the fields of a cut result that decide it; seconds, hung and the like are left out
CUT_FIELDS = ("cut", "fired", "kind", "addr", "op_index", "alive", "recovered", "passed",
              "skipped", "baseline", "rewound", "image", "torn", "depth", "computed",
              "content", "link", "bit_error", "message")
MESSAGE = CUT_FIELDS.index("message")
PASSED = CUT_FIELDS.index("passed")


def key(report):
    """A name for the campaign a report comes from: its adapter and how it was run."""
    cov = report.get("coverage") or {}
    parts = [report["adapter_file"]]
    shard = report.get("shard")
    if shard:
        parts.append("shard %d/%d" % (shard["index"], shard["of"]))
    if cov.get("mode"):
        parts.append("plan %s" % cov["mode"])
    if any(c.get("torn") for c in report["cuts"]):
        parts.append("torn")
    if report.get("depth"):
        parts.append("depth %d" % report["depth"]["levels"])
    return " | ".join(parts)


def fingerprint(report):
    cov = dict(report.get("coverage") or {})
    return {
        "passed": report["passed"],
        "coverage": cov or None,
        "depth": report.get("depth"),
        "shard": report.get("shard"),
        "cuts": [[c.get(f) for f in CUT_FIELDS] for c in report["cuts"]],
    }


def collect(folder):
    """Every BrickProof report under `folder`, fingerprinted, by key."""
    out = {}
    for path in sorted(glob.glob(os.path.join(folder, "**", "*.json"), recursive=True)):
        with open(path, encoding="utf-8") as f:
            try:
                report = json.load(f)
            except ValueError:
                continue
        if not isinstance(report, dict) or "adapter_file" not in report or "cuts" not in report:
            continue                                # not a BrickProof report
        k = key(report)
        if k in out and out[k] != fingerprint(report):
            raise SystemExit("two different reports for the same campaign: %s (%s)" % (k, path))
        out[k] = fingerprint(report)
    return out


def dump(scenarios, source, path):
    """One cut per line, so a changed result is one changed line in a diff."""
    lines = ["{", '  "source": %s,' % json.dumps(source), '  "scenarios": {']
    for i, (k, s) in enumerate(sorted(scenarios.items())):
        head = {f: s[f] for f in ("passed", "coverage", "depth", "shard")}
        lines.append("    %s: {" % json.dumps(k))
        for f, v in head.items():
            lines.append("      %s: %s," % (json.dumps(f), json.dumps(v, sort_keys=True)))
        lines.append('      "cuts": [')
        rows = [json.dumps(r) for r in s["cuts"]]
        lines += ["        %s%s" % (r, "," if j < len(rows) - 1 else "") for j, r in enumerate(rows)]
        lines.append("      ]")
        lines.append("    }%s" % ("," if i < len(scenarios) - 1 else ""))
    lines += ["  }", "}", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def compare(base, new):
    """(errors, warnings) between two {key: fingerprint} maps."""
    errors, warnings = [], []
    for k in sorted(set(base) - set(new)):
        errors.append("missing: %s" % k)
    for k in sorted(set(new) - set(base)):
        warnings.append("new campaign, not in the baseline: %s" % k)
    for k in sorted(set(base) & set(new)):
        a, b = base[k], new[k]
        for f in ("passed", "coverage", "depth", "shard"):
            if a[f] != b[f]:
                errors.append("%s: %s was %s, now %s" % (k, f, json.dumps(a[f]), json.dumps(b[f])))
        mine = []
        ca, cb = by_name(a["cuts"]), by_name(b["cuts"])
        for name in ca:
            if name not in cb:
                mine.append("%s: %s is gone" % (k, name))
        for name in cb:
            if name not in ca:
                mine.append("%s: %s is new" % (k, name))
        for name, ra in ca.items():
            rb = cb.get(name)
            if rb is None or ra == rb:
                continue
            fields = [f for f, x, y in zip(CUT_FIELDS, ra, rb, strict=True) if x != y]
            what = "%s: %s changed %s" % (k, name, ", ".join(
                "%s %s -> %s" % (f, json.dumps(ra[CUT_FIELDS.index(f)]), json.dumps(rb[CUT_FIELDS.index(f)]))
                for f in fields))
            failing_both = not ra[PASSED] and not rb[PASSED]
            (warnings if fields == ["message"] and failing_both else mine).append(what)
        if len(mine) > MAX_PER_CAMPAIGN:
            mine = mine[:MAX_PER_CAMPAIGN] + ["%s: and %d more" % (k, len(mine) - MAX_PER_CAMPAIGN)]
        errors += mine
    return errors, warnings


MAX_PER_CAMPAIGN = 12


def by_name(rows):
    """The results of one campaign by cut name; a name met twice gets #2, #3."""
    out, seen = {}, {}
    for r in rows:
        n = seen[r[0]] = seen.get(r[0], 0) + 1
        out[r[0] if n == 1 else "%s #%d" % (r[0], n)] = r
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fingerprint", help="write a baseline from a folder of reports")
    f.add_argument("folder")
    f.add_argument("-o", "--out", required=True)
    f.add_argument("--source", default="", help="where the reports come from (a CI run, a commit)")
    c = sub.add_parser("compare", help="compare a folder of reports with a baseline")
    c.add_argument("baseline")
    c.add_argument("folder")
    a = p.parse_args(argv)

    if a.cmd == "fingerprint":
        scenarios = collect(a.folder)
        if not scenarios:
            raise SystemExit("no BrickProof reports in %s" % a.folder)
        dump(scenarios, a.source, a.out)
        print("%d campaigns written to %s" % (len(scenarios), a.out))
        return 0

    with open(a.baseline, encoding="utf-8") as fh:
        base = json.load(fh)["scenarios"]
    errors, warnings = compare(base, collect(a.folder))
    for w in warnings:
        print("warning: " + w)
    for e in errors:
        print("DIFFERENT: " + e)
    differing = {e.split(": ")[0] for e in errors if not e.startswith("missing: ")}
    missing = sum(e.startswith("missing: ") for e in errors)
    print("%d campaigns in the baseline: %s" % (len(base), (
        "%d differ, %d missing" % (len(differing), missing)) if errors else "every result the same"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
