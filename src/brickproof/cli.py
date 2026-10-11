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
from brickproof import report as reports
from brickproof import runner
from brickproof import torn as torns
from brickproof import trace as traces


def _print_result(r):
    where = "%s 0x%08X" % (r.kind, r.addr) if r.addr else r.kind
    if r.torn:
        where = "torn at 0x%08X" % r.addr       # the shape is already in the cut's name
    op = "op %s" % r.op_index if r.op_index is not None else "op ?"
    if r.baseline:
        where = ""
        op = "%s ops" % r.op_index if r.op_index is not None else ""
    status = "SKIP" if r.skipped else "PASS" if r.passed else "FAIL"
    note = r.message
    if r.passed and r.image:
        note = "runs %s" % r.image              # what the oracle found installed and running
    print("%-4s %-28s %-9s %-22s %6.1fs  %s" % (
        status, r.cut, op, where, r.seconds, note), flush=True)


def _load(args):
    try:
        ad = adapters.load(args.adapter, target=args.target)
        ad.path = args.adapter              # as typed, so a report's commands can be pasted back
        return ad
    except (adapters.AdapterError, OSError) as e:
        print("adapter error: %s" % e, file=sys.stderr)
        return None


def _make_dirs(*paths):
    for out in paths:
        if out and os.path.dirname(out):
            os.makedirs(os.path.dirname(out), exist_ok=True)


def _print_plan(plan):
    print()
    for line in plan.lines():
        print(line)
    print("plan (%s): %s" % (plan.mode, plan.summary()))
    print(flush=True)


def _jobs(args):
    """--jobs N, or 'auto' for one emulator per core, leaving one core free."""
    j = getattr(args, "jobs", None)
    if j in (None, "1"):
        return 1
    if j == "auto":
        return max(1, (os.cpu_count() or 2) - 1)
    return max(1, int(j))


def _run(ad, args, **kw):
    """runner.run, with a tool failure turned into a message. Returns None on failure."""
    try:
        return runner.run(ad, keep_workdir=args.keep, log=args.renode_log,
                          on_result=_print_result, jobs=_jobs(args), **kw)
    except Exception as e:      # the tool broke: not the same thing as a failed cut
        print("brickproof error: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return None


def cmd_run(args):
    ad = _load(args)
    if ad is None:
        return 2
    if args.plan and not args.cut:
        ad.plan = dict(ad.plan or {}, mode=args.plan)
    if args.cut:
        # just these operations: for reproducing a result. The adapter's plan, torn
        # states and depth are left out unless asked for again on this command line.
        ad.cuts = [adapters.Cut(name="op-%d" % n, at_op=n) for n in args.cut]
        ad.plan = ad.torn = ad.depth = None
    if args.torn:
        ad.torn = list(torns.KINDS)
    if args.depth is not None:
        deeper = dict(adapters.DEPTH_DEFAULTS, **(ad.depth or {}), levels=args.depth)
        ad.depth = deeper if args.depth > 1 else None
    if args.real_every and ad.plan:
        ad.plan = dict(ad.plan, real_every=args.real_every)
    if args.per_phase is not None and not args.cut:
        ad.plan = dict(ad.plan or {"mode": "phases"}, per_phase=args.per_phase)
    if not ad.cuts and not ad.plan:
        print("nothing to cut: the adapter has no scenario.cuts and no scenario.plan "
              "(or pass --plan phases)", file=sys.stderr)
        return 2
    _make_dirs(args.json, args.renode_log, args.trace, args.junit, args.html)
    print("BrickProof: %s, target %s" % (ad.name, ad.target), flush=True)
    if not ad.oracle:
        print("note: this adapter has no 'oracle' section, so each verdict rests on the "
              "driver alone (what the firmware says about itself)", flush=True)
    out = _run(ad, args, fail_fast=args.fail_fast, on_plan=_print_plan if ad.plan else None)
    if out is None:
        return 3
    report = runner.as_dict(out, ad)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
    if args.junit:
        with open(args.junit, "w", encoding="utf-8") as f:
            f.write(reports.junit(report))
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(reports.html_page(report))
    if args.trace:
        traces.write_jsonl(out.trace, args.trace)
    if not out.results[0].passed:
        print("the update fails even with no power cut, so no cuts were run")
    ran = [r for r in out.results if not (r.skipped or r.baseline or r.torn) and r.depth == 1]
    passed = sum(r.passed for r in ran)
    print("%d/%d cuts recovered (setup %.0fs, total %.0fs%s)" % (
        passed, len(ran), out.timings.get("setup_s", 0), out.timings.get("total_s", 0),
        ", %d emulators" % out.jobs if out.jobs > 1 else ""))
    computed = sum(1 for r in ran if r.computed)
    if computed:
        print("%d of those cuts were made in the emulator and checked against the computed "
              "state; the other %d were powered up from the computed state" % (
                  len(ran) - computed, computed))
    torn = [r for r in out.results if r.torn]
    if torn:
        print("%d/%d torn states survived (modelled shapes of a half-done erase or program, "
              "not yet calibrated against silicon)" % (sum(r.passed for r in torn), len(torn)))
    deep = [r for r in out.results if r.depth > 1]
    if out.depth:
        note = "; stopped at the limit of %d states" % ad.depth["max_states"] if out.depth["capped"] else ""
        print("%d/%d states after a further cut during recovery recovered (up to %d cuts in a "
              "row; %d more led to a state already tested%s)" % (
                  sum(r.passed for r in deep), len(deep), out.depth["levels"],
                  out.depth["skipped_known"], note))
    if ad.plan and out.plan:
        print("coverage: %s" % out.plan.summary())
    return 0 if out.passed else 1


def cmd_trace(args):
    ad = _load(args)
    if ad is None:
        return 2
    _make_dirs(args.out, args.renode_log)
    print("BrickProof: tracing %s, target %s" % (ad.name, ad.target), flush=True)
    out = _run(ad, args, baseline_only=True)
    if out is None:
        return 3
    results, trace = out.results, out.trace
    if out.plan:
        _print_plan(out.plan)
    guessed = sum(1 for op in trace if op.get("inferred"))
    if guessed:
        print("%d program(s) wrote what was already there; their addresses are inferred "
              "from the ones before" % guessed)
    if args.out:
        traces.write_jsonl(trace, args.out)
        print("trace written to %s" % args.out)
    return 0 if results[0].passed else 1


def main(argv=None):
    # a Windows console in a legacy code page cannot print every character a device
    # may send; show a placeholder rather than die with an encoding error
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="brickproof", description="Power-fail testing for firmware updates.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(c):
        c.add_argument("adapter", help="adapter YAML file")
        c.add_argument("--target", help="firmware project folder (overrides the adapter's 'target')")
        c.add_argument("--keep", action="store_true", help="keep the Renode work folder")
        c.add_argument("--renode-log", help="write Renode's own output to this file")
        c.add_argument("-j", "--jobs", metavar="N",
                       help="emulators to run side by side: a number, or 'auto' for one per "
                            "core but one. The results do not depend on it (default 1)")

    r = sub.add_parser("run", help="run an adapter's power cuts")
    common(r)
    r.add_argument("--json", help="write the results as JSON to this file")
    r.add_argument("--junit", help="write the results as JUnit XML to this file")
    r.add_argument("--html", help="write a self-contained HTML report to this file")
    r.add_argument("--cut", type=int, action="append", metavar="N",
                   help="cut only at operation N (repeatable): reproduces one result")
    r.add_argument("--trace", help="write the golden-run trace (JSONL) to this file")
    r.add_argument("--fail-fast", action="store_true", help="stop at the first cut that fails")
    r.add_argument("--plan", choices=("phases", "every"),
                   help="let the planner choose the cuts: every distinct flash state, or "
                        "(phases) all of them in short phases and samples in long ones")
    r.add_argument("--real-every", type=int, metavar="N",
                   help="make only every Nth planned cut in the emulator and power the others "
                        "up from the computed flash state (much faster on a long update)")
    r.add_argument("--torn", action="store_true",
                   help="also boot from torn states: each cut's operation left half done")
    r.add_argument("--depth", type=int, metavar="N",
                   help="power cuts in a row to explore: 2 also cuts during the recovery "
                        "from each first cut (default 1)")
    r.add_argument("--per-phase", type=int, metavar="N",
                   help="samples inside a long phase when planning by phases (default 8)")
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("trace", help="run the update uninterrupted and show its flash operations")
    common(t)
    t.add_argument("-o", "--out", help="write every operation as JSONL to this file")
    t.set_defaults(func=cmd_trace)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
