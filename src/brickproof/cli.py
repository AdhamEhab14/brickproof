"""brickproof run adapter.yaml      cut power during the update and judge each cut
brickproof trace adapter.yaml    show what the update does to flash, uninterrupted

Exit codes: 0 every cut recovered, 1 at least one cut failed,
2 the adapter is wrong, 3 BrickProof itself failed (Renode missing, crashed...).
"""
import argparse
import json
import os
import sys

from brickproof import adapter as adapters
from brickproof import runner
from brickproof import trace as traces


def _print_result(r):
    where = "%s 0x%08X" % (r.kind, r.addr) if r.addr else r.kind
    op = "op %s" % r.op_index if r.op_index is not None else "op ?"
    if r.baseline:
        where = ""
        op = "%s ops" % r.op_index if r.op_index is not None else ""
    status = "SKIP" if r.skipped else "PASS" if r.passed else "FAIL"
    print("%-4s %-28s %-9s %-22s %6.1fs  %s" % (
        status, r.cut, op, where, r.seconds, r.message), flush=True)


def _load(args):
    try:
        return adapters.load(args.adapter, target=args.target)
    except (adapters.AdapterError, OSError) as e:
        print("adapter error: %s" % e, file=sys.stderr)
        return None


def _make_dirs(*paths):
    for out in paths:
        if out and os.path.dirname(out):
            os.makedirs(os.path.dirname(out), exist_ok=True)


def _run(ad, args, **kw):
    """runner.run, with a tool failure turned into a message. Returns None on failure."""
    try:
        return runner.run(ad, keep_workdir=args.keep, log=args.renode_log,
                          on_result=_print_result, **kw)
    except Exception as e:      # the tool broke: not the same thing as a failed cut
        print("brickproof error: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return None


def cmd_run(args):
    ad = _load(args)
    if ad is None:
        return 2
    if not ad.cuts:
        print("adapter has no cuts in scenario.cuts", file=sys.stderr)
        return 2
    _make_dirs(args.json, args.renode_log, args.trace)
    print("BrickProof: %s, %d cut(s), target %s" % (ad.name, len(ad.cuts), ad.target), flush=True)
    out = _run(ad, args, fail_fast=args.fail_fast)
    if out is None:
        return 3
    results, timings, trace = out
    report = runner.as_dict(results, timings, ad)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
    if args.trace:
        traces.write_jsonl(trace, args.trace)
    if not results[0].passed:
        print("the update fails even with no power cut, so no cuts were run")
    ran = [r for r in results if not (r.skipped or r.baseline)]
    passed = sum(r.passed for r in ran)
    print("%d/%d cuts recovered (setup %.0fs, total %.0fs)" % (
        passed, len(ran), timings.get("setup_s", 0), timings.get("total_s", 0)))
    return 0 if report["passed"] else 1


def cmd_trace(args):
    ad = _load(args)
    if ad is None:
        return 2
    _make_dirs(args.out, args.renode_log)
    print("BrickProof: tracing %s, target %s" % (ad.name, ad.target), flush=True)
    out = _run(ad, args, baseline_only=True)
    if out is None:
        return 3
    results, _, trace = out
    print()
    for line in traces.describe(trace, ad.flash.page, ad.flash.write_unit):
        print(line)
    guessed = sum(1 for op in trace if op.get("inferred"))
    if guessed:
        print("%d program(s) wrote what was already there; their addresses are inferred "
              "from the ones before" % guessed)
    if args.out:
        traces.write_jsonl(trace, args.out)
        print("trace written to %s" % args.out)
    return 0 if results[0].passed else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="brickproof", description="Power-fail testing for firmware updates.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(c):
        c.add_argument("adapter", help="adapter YAML file")
        c.add_argument("--target", help="firmware project folder (overrides the adapter's 'target')")
        c.add_argument("--keep", action="store_true", help="keep the Renode work folder")
        c.add_argument("--renode-log", help="write Renode's own output to this file")

    r = sub.add_parser("run", help="run an adapter's power cuts")
    common(r)
    r.add_argument("--json", help="write the results as JSON to this file")
    r.add_argument("--trace", help="write the golden-run trace (JSONL) to this file")
    r.add_argument("--fail-fast", action="store_true", help="stop at the first cut that fails")
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("trace", help="run the update uninterrupted and show its flash operations")
    common(t)
    t.add_argument("-o", "--out", help="write every operation as JSONL to this file")
    t.set_defaults(func=cmd_trace)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
