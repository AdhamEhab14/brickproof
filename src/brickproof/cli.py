"""brickproof run adapter.yaml"""
import argparse
import json
import os
import sys

from brickproof import adapter as adapters
from brickproof import runner


def _print_result(r):
    where = "%s 0x%08X" % (r.kind, r.addr) if r.kind == "erase" else r.kind
    op = "op %s" % r.op_index if r.op_index is not None else "op ?"
    print("%-4s %-28s %-8s %-22s %6.1fs  %s" % (
        "PASS" if r.passed else "FAIL", r.cut, op, where, r.seconds, r.message), flush=True)


def cmd_run(args):
    try:
        ad = adapters.load(args.adapter, target=args.target)
    except (adapters.AdapterError, OSError) as e:
        print("adapter error: %s" % e, file=sys.stderr)
        return 2
    if not ad.cuts:
        print("adapter has no cuts in scenario.cuts", file=sys.stderr)
        return 2
    for out in (args.json, args.renode_log):
        if out and os.path.dirname(out):
            os.makedirs(os.path.dirname(out), exist_ok=True)
    print("BrickProof: %s, %d cut(s), target %s" % (ad.name, len(ad.cuts), ad.target), flush=True)
    results, timings = runner.run(ad, keep_workdir=args.keep, log=args.renode_log,
                                  on_result=_print_result)
    report = runner.as_dict(results, timings, ad)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
    passed = sum(r.passed for r in results)
    print("%d/%d cuts recovered (setup %.0fs, total %.0fs)" % (
        passed, len(results), timings.get("setup_s", 0), timings.get("total_s", 0)))
    return 0 if report["passed"] else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="brickproof", description="Power-fail testing for firmware updates.")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="run an adapter's power cuts")
    r.add_argument("adapter", help="adapter YAML file")
    r.add_argument("--target", help="firmware project folder (overrides the adapter's 'target')")
    r.add_argument("--json", help="write the results as JSON to this file")
    r.add_argument("--keep", action="store_true", help="keep the Renode work folder")
    r.add_argument("--renode-log", help="write Renode's own output to this file")
    args = p.parse_args(argv)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
