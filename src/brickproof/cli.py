"""brickproof check adapter.yaml    find what is wrong with an adapter, without an emulator
brickproof run adapter.yaml      cut power during the update and judge each cut
brickproof trace adapter.yaml    show what the update does to flash, uninterrupted
brickproof export adapter.yaml   write the flash a cut leaves, to put on a real board
brickproof adapter-from-zephyr   write an MCUboot adapter from a Zephyr build

Exit codes: 0 every cut recovered, 1 at least one cut failed,
2 the adapter is wrong, 3 BrickProof itself failed (emulator missing, crashed...).
"""
import argparse
import json
import os
import sys

from brickproof import adapter as adapters
from brickproof import export as exports
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
    if r.content:
        where, op = "damaged image", ""
    if r.link is not None:
        where, op = "link broken", "%d B" % r.link
    if r.bit_error:
        where, op = "bits flipped", ""
    status = "SKIP" if r.skipped else "PASS" if r.passed else "FAIL"
    note = r.message
    if r.passed and r.image:
        note = "runs %s" % r.image              # what the oracle found installed and running
    print("%-4s %-28s %-9s %-22s %6.1fs  %s" % (
        status, r.cut, op, where, r.seconds, note), flush=True)


def _load(args):
    """The adapter, after the same checks `brickproof check` makes; None (after saying
    what is wrong and how to fix it) if any fails, before an emulator is started."""
    from brickproof import check as checks
    ad, rep = checks.check(args.adapter, target=args.target)
    if not rep.passed:
        print("%s has a problem, so nothing was run:" % args.adapter, file=sys.stderr)
        for line in rep.lines(only_failures=True):
            print(line, file=sys.stderr)
        print("(brickproof check %s shows every check)" % args.adapter, file=sys.stderr)
        return None
    ad.path = args.adapter              # as typed, so a report's commands can be pasted back
    return ad


def cmd_check(args):
    from brickproof import check as checks
    print("checking %s" % args.adapter)
    _ad, rep = checks.check(args.adapter, target=args.target)
    for line in rep.lines():
        print(line)
    if rep.passed:
        print("all good: brickproof run %s" % args.adapter)
        return 0
    print("%d problem(s) to fix" % sum(1 for f in rep.findings if not f.ok))
    return 2


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


def _hint_time(trace, ad):
    """A baseline can fail just because the adapter gives the update too little time."""
    spent = traces.cost(trace, ad.flash)["flash_time_s"] if trace else 0
    if spent > ad.update_time:
        print("note: the flash operations seen so far take %.2f s on the chip, more than "
              "scenario.update_time (%.2f s). Give the update more time." % (spent, ad.update_time))


def _print_cost(trace, flash):
    for line in traces.describe_cost(traces.cost(trace, flash), flash.timing):
        print(line)


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
    if args.full and not args.cut:
        # everything worth testing, as fast as this machine allows
        args.torn = True
        if args.depth is None:
            args.depth = 2
        if args.jobs is None:
            args.jobs = "auto"
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
        levels = adapters.EXHAUSTIVE if args.depth == "exhaustive" else int(args.depth)
        deeper = dict(adapters.DEPTH_DEFAULTS, **(ad.depth or {}), levels=levels)
        ad.depth = deeper if levels > 1 else None
    if args.real_every and ad.plan:
        ad.plan = dict(ad.plan, real_every=args.real_every)
    elif args.full and ad.plan and "real_every" not in ad.plan:
        ad.plan = dict(ad.plan, real_every="auto")     # chosen once the update's length is known
    if args.per_phase is not None and not args.cut:
        ad.plan = dict(ad.plan or {"mode": "phases"}, per_phase=args.per_phase)
    if args.soak:
        ad.soak = (args.soak * 60.0, args.seed)
        ad.plan = ad.plan or {"mode": "phases"}
    if args.shard:
        try:
            k, n = (int(x) for x in args.shard.split("/"))
            if not 1 <= k <= n:
                raise ValueError
        except ValueError:
            print("--shard: use K/N with K from 1 to N, for example 3/20", file=sys.stderr)
            return 2
        ad.shard = (k, n)
    if not ad.cuts and not ad.plan:
        print("nothing to cut: the adapter has no scenario.cuts and no scenario.plan "
              "(or pass --plan phases)", file=sys.stderr)
        return 2
    if not args.html:
        # always a report to open, even when nobody asked for one
        args.html = os.path.join("brickproof-out", "%s.html" % ad.name)
    _make_dirs(args.json, args.renode_log, args.trace, args.junit, args.html, args.sarif)
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
    if args.sarif:
        with open(args.sarif, "w", encoding="utf-8") as f:
            json.dump(reports.sarif(report), f, indent=2)
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(reports.html_page(report))
    if args.trace:
        traces.write_jsonl(out.trace, args.trace)
    if not out.results[0].passed:
        print("the update fails even with no power cut, so no cuts were run")
        _hint_time(out.trace, ad)
        if ad.flash.worn:
            print("note: flash.worn is set: programs at 0x%08X..0x%08X report success but leave "
                  "bit 0 of each cell as it was, so a bootloader that does not read back what "
                  "it wrote cannot tell" % (ad.flash.worn[0], ad.flash.worn[1] - 1))
    ran = [r for r in out.results if not (r.skipped or r.baseline or r.torn or r.content)
           and r.link is None and not r.bit_error and r.depth == 1]
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
        print("%d/%d torn states survived (shapes of a half-done erase or program: erase-early "
              "and erase-late measured on an STM32F103 stopped by a reset, the others "
              "modelled)" % (sum(r.passed for r in torn), len(torn)))
    bad = [r for r in out.results if r.content]
    if bad:
        print("%d/%d damaged images refused, with %s still installed and running" % (
            sum(r.passed for r in bad), len(bad), ad.content_faults["keep"]))
    flipped = [r for r in out.results if r.bit_error]
    if flipped:
        print("%d/%d images damaged at rest were not run" % (sum(r.passed for r in flipped), len(flipped)))
    links = [r for r in out.results if r.link is not None]
    if links:
        print("%d/%d broken links recovered (the host's session cut off, then run again)" % (
            sum(r.passed for r in links), len(links)))
    deep = [r for r in out.results if r.depth > 1]
    if out.depth:
        note = "; stopped at the limit of %d states" % ad.depth["max_states"] if out.depth["capped"] else ""
        if out.depth["levels"] >= adapters.EXHAUSTIVE and not out.depth["capped"]:
            note += "; no new state after %d cuts in a row" % out.depth.get("deepest", 1)
        print("%d/%d states after a further cut during recovery recovered (up to %d cuts in a "
              "row; %d more led to a state already tested%s)" % (
                  sum(r.passed for r in deep), len(deep),
                  min(out.depth["levels"], out.depth.get("deepest", 1)),
                  out.depth["skipped_known"], note))
    if getattr(ad, "soak", None):
        print("soak: %d random tests in %.1f of the %.0f minutes allowed, seed %d%s" % (
            len(out.results) - 1, out.timings.get("total_s", 0) / 60, ad.soak[0] / 60, ad.soak[1],
            ", stopped at the first failure" if not out.passed else ""))
    elif ad.plan and out.plan:
        print("coverage: %s" % out.plan.summary())
    if out.shard:
        print("shard %d of %d: this run made %d of the campaign's %d cuts; the coverage above is "
              "that of all shards together" % (out.shard["index"], out.shard["of"],
                                               out.shard["cuts"], out.shard["all_cuts"]))
    if out.trace:
        _print_cost(out.trace, ad.flash)
    _print_verdict(out, report, args.html)
    return 0 if out.passed else 1


def _print_verdict(out, report, html):
    """The one line to read: did it pass, where the report is, and how to see a failure again."""
    print()
    if out.passed:
        print("PASS: the device recovered every time. Report: %s" % html)
        return
    failed = [c for c in report["cuts"] if not c["passed"] and not c["skipped"]]
    print("FAIL: %d of %d did not recover. Report: %s" % (len(failed), len(report["cuts"]), html))
    if failed:
        print("the first one: %s: %s" % (failed[0]["cut"], failed[0]["message"]))
        print("run it alone:  %s" % reports.reproduce(report, failed[0]))


def demo_folder():
    """Where the bundled demo lives: inside the installed package."""
    import brickproof.demo
    return os.path.dirname(os.path.abspath(brickproof.demo.__file__))


def demo_builds():
    """The demo's adapters: 'adapter' is the correct bootloader, the rest have a known bug."""
    names = sorted(f[:-5] for f in os.listdir(demo_folder()) if f.endswith(".yaml") and f[0] != "_")
    return ["adapter"] + [n for n in names if n != "adapter"]


def cmd_demo(args):
    builds = demo_builds()
    if args.list:
        for name in builds:
            with open(os.path.join(demo_folder(), name + ".yaml")) as f:
                first = f.readline().lstrip("# ").strip()
            print("%-22s %s" % (name, first))
        return 0
    name = args.name if args.name in builds else "bug-" + args.name
    if name not in builds:
        print("no demo build called %r (try: brickproof demo --list)" % args.name, file=sys.stderr)
        return 2
    args.adapter = os.path.join(demo_folder(), name + ".yaml")
    return cmd_run(args)


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
    if trace:
        _print_cost(trace, ad.flash)
    if not results[0].passed:
        _hint_time(trace, ad)
    guessed = sum(1 for op in trace if op.get("inferred"))
    if guessed:
        print("%d program(s) wrote what was already there; their addresses are inferred "
              "from the ones before" % guessed)
    if args.out:
        traces.write_jsonl(trace, args.out)
        print("trace written to %s" % args.out)
    return 0 if results[0].passed else 1


def cmd_export(args):
    ad = _load(args)
    if ad is None:
        return 2
    _make_dirs(args.out, args.renode_log)
    print("BrickProof: running the update of %s once, to export the state at operation %d"
          % (ad.name, args.cut), flush=True)
    out = _run(ad, args, baseline_only=True)
    if out is None:
        return 3
    if not out.results[0].passed:
        print("the update fails even with no power cut: nothing to export", file=sys.stderr)
        return 1
    try:
        files = exports.write(ad, out.pre, out.trace, args.out, args.cut, args.torn)
    except ValueError as e:
        print("export: %s" % e, file=sys.stderr)
        return 2
    for part, path in files.items():
        print("%-26s %s" % (part, path))
    return 0


def cmd_adapter_from_zephyr(args):
    from brickproof import zephyr_adapter
    try:
        d = zephyr_adapter.describe(args.build)
    except (OSError, KeyError, ValueError) as e:
        print("adapter-from-zephyr: %s" % e, file=sys.stderr)
        return 2
    out_dir = os.path.dirname(os.path.abspath(args.out))
    try:
        images = os.path.relpath(os.path.abspath(args.images), out_dir)
    except ValueError:                  # another drive (Windows): no relative path there
        images = os.path.abspath(args.images)
    text = zephyr_adapter.adapter_yaml(d, images, args.alive, args.expect)
    _make_dirs(args.out)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("%s: %s, %s, slot 0 at 0x%X, slot 1 at 0x%X" % (args.out, d["soc"], d["mode"],
                                                          d["slot0"][0], d["slot1"][0]))
    return 0


def main(argv=None):
    # a Windows console in a legacy code page cannot print every character a device
    # may send; show a placeholder rather than die with an encoding error
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="brickproof", description="Power-fail testing for firmware updates.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(c, adapter=True):
        if adapter:
            c.add_argument("adapter", help="adapter YAML file")
        c.add_argument("--target", help="firmware project folder (overrides the adapter's 'target')")
        c.add_argument("--keep", action="store_true", help="keep the emulator's work folder")
        c.add_argument("--renode-log", "--emulator-log", dest="renode_log",
                       help="write the emulator's own output (Renode or m33mu) to this file")
        c.add_argument("-j", "--jobs", metavar="N",
                       help="emulators to run side by side: a number, or 'auto' for one per "
                            "core but one. The results do not depend on it (default 1)")

    c = sub.add_parser("check", help="find what is wrong with an adapter, without an emulator",
                       description="Checks the adapter, the files it names, that the firmware "
                                   "fits the chip and that the emulator is installed, and says "
                                   "how to fix what is wrong. run, trace and export make the "
                                   "same checks first.")
    c.add_argument("adapter", help="adapter YAML file")
    c.add_argument("--target", help="firmware project folder (overrides the adapter's 'target')")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("run", help="run an adapter's power cuts")
    common(r)
    run_options(r)
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("demo", help="run the bundled demo bootloader: no firmware of your own needed",
                       description="Runs the demo that ships with BrickProof. With no name it is the "
                                   "correct bootloader; a bug build's name runs that one "
                                   "(see --list).")
    d.add_argument("name", nargs="?", default="adapter", help="which build (default: the correct one)")
    d.add_argument("--list", action="store_true", help="list the builds and exit")
    common(d, adapter=False)
    run_options(d)
    d.set_defaults(func=cmd_demo)

    t = sub.add_parser("trace", help="run the update uninterrupted and show its flash operations")
    common(t)
    t.add_argument("-o", "--out", help="write every operation as JSONL to this file")
    t.set_defaults(func=cmd_trace)

    e = sub.add_parser("export", help="write the flash a cut leaves, to put on a real board",
                       description="Runs the update once, uninterrupted, and writes the flash "
                                   "as a cut just before operation N leaves it (the same bytes a "
                                   "run's cut there starts from), with a note on how to program "
                                   "it.")
    common(e)
    e.add_argument("--cut", type=int, required=True, metavar="N", help="the operation, as a run reports it")
    e.add_argument("--torn", choices=torns.KINDS, metavar="KIND",
                   help="leave operation N half done, in this shape: %s" % ", ".join(torns.KINDS))
    e.add_argument("-o", "--out", default="state.bin", help="the flash image (default state.bin); "
                   "the other files go next to it")
    e.set_defaults(func=cmd_export)

    z = sub.add_parser("adapter-from-zephyr", help="write an MCUboot adapter from a Zephyr build",
                       description="Reads an MCUboot build folder (zephyr/zephyr.dts and "
                                   "zephyr/.config) and writes an adapter for MCUboot and an app "
                                   "whose signed images are in --images.")
    z.add_argument("build", help="the MCUboot build folder `west build` made")
    z.add_argument("--images", required=True,
                   help="folder with mcuboot.elf, app_v1.img, app_v2_staged.img and app_v2.img")
    z.add_argument("-o", "--out", default="adapter.yaml", help="the adapter to write")
    z.add_argument("--alive", default="APP v[0-9]", help="regex: an app is running")
    z.add_argument("--expect", default="APP v2", help="regex: the new app is running")
    z.set_defaults(func=cmd_adapter_from_zephyr)

    args = p.parse_args(argv)
    return args.func(args)


def _depth_arg(text):
    if text == "exhaustive":
        return text
    try:
        return int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("a number of cuts in a row, or exhaustive") from None


def run_options(r):
    r.add_argument("--json", help="write the results as JSON to this file")
    r.add_argument("--junit", help="write the results as JUnit XML to this file")
    r.add_argument("--sarif", help="write the failures as SARIF to this file (GitHub code scanning)")
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
    r.add_argument("--full", action="store_true",
                   help="everything worth testing in one run: the clean cuts, torn states, a "
                        "second cut during each recovery and the adapter's damaged-image tests, "
                        "on one emulator per core, with long updates sped up by powering most "
                        "cuts up from their computed state")
    r.add_argument("--torn", action="store_true",
                   help="also boot from torn states: each cut's operation left half done")
    r.add_argument("--depth", type=_depth_arg, metavar="N",
                   help="power cuts in a row to explore: 2 also cuts during the recovery "
                        "from each first cut (default 1); 'exhaustive' goes on until no "
                        "new flash state turns up")
    r.add_argument("--per-phase", type=int, metavar="N",
                   help="samples inside a long phase when planning by phases (default 8)")
    r.add_argument("--soak", type=float, metavar="MINUTES",
                   help="instead of the plan, random cuts and torn states until this many "
                        "minutes have passed or one fails")
    r.add_argument("--seed", type=int, default=0, help="the random seed for --soak (default 0)")
    r.add_argument("--shard", metavar="K/N",
                   help="run only every Nth cut, starting with the Kth: splits a long campaign "
                        "over N machines, each given a different K")


if __name__ == "__main__":
    sys.exit(main())
