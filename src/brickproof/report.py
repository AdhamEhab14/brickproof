"""Reports of a run: JUnit XML for CI systems, and one self-contained HTML page for people.

Both are built from the same dictionary the JSON report holds (runner.as_dict), so
the three can never disagree.
"""
import html
from xml.sax.saxutils import escape, quoteattr

from brickproof import trace as traces


def group(cut):
    """Which part of a run a result belongs to."""
    if cut["baseline"]:
        return "baseline"
    if cut.get("content"):
        return "content"
    if cut.get("link") is not None:
        return "link"
    if cut.get("bit_error"):
        return "bits"
    if cut["torn"]:
        return "torn"
    if cut["depth"] > 1:
        return "depth-%d" % cut["depth"]
    return "cut"


GROUP_TITLES = {
    "baseline": "The update, uninterrupted",
    "cut": "Clean cuts: power lost between two flash operations",
    "torn": "Torn states: power lost inside an erase or a program",
    "content": "Bad update content: a damaged image the bootloader must refuse",
    "link": "A broken link: the host's session cut off, then tried again",
    "bits": "Bit errors at rest: a stored image damaged while the device was off",
}


def group_title(name):
    if name.startswith("depth-"):
        return "A further cut during recovery (%s cuts in a row)" % name.split("-")[1]
    return GROUP_TITLES[name]


def where(cut):
    if cut["baseline"]:
        return ""
    if not cut["fired"]:
        return "did not fire"
    return "%s at 0x%08X" % (cut["kind"], cut["addr"]) if cut["addr"] else cut["kind"]


def reproduce(report, cut):
    """A command that runs just this result again, where one exists."""
    base = "brickproof run %s" % report["adapter_file"]
    if cut["baseline"]:
        return base + " --cut 0"
    if cut["torn"]:
        return "%s --cut %d --torn" % (base, cut["op_index"])
    if cut["depth"] > 1:
        first = cut["cut"].split(" > ")[0].replace("op-", "")
        return "%s --cut %s --depth %d" % (base, first, cut["depth"])
    if cut["op_index"] is not None:
        return "%s --cut %d" % (base, cut["op_index"])
    return base


def export_command(report, cut):
    """A command that writes the flash this result started from, for a real board.
    None where there is no single such state (the baseline, cuts in a row)."""
    if cut["baseline"] or cut["depth"] > 1 or cut["op_index"] is None or not cut["fired"]:
        return None
    base = "brickproof export %s --cut %d" % (report["adapter_file"], cut["op_index"])
    if cut["torn"]:
        return "%s --torn %s -o op-%d-%s.bin" % (base, cut["torn"], cut["op_index"], cut["torn"])
    return "%s -o op-%d.bin" % (base, cut["op_index"])


# ---- JUnit ---------------------------------------------------------------------

def junit(report):
    """JUnit XML: one test case per result, grouped by kind in the class name."""
    cuts = report["cuts"]
    failures = sum(1 for c in cuts if not c["passed"] and not c["skipped"])
    skipped = sum(1 for c in cuts if c["skipped"])
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<testsuite name=%s tests="%d" failures="%d" skipped="%d" time="%.1f" timestamp=%s>' % (
               quoteattr("brickproof." + report["adapter"]), len(cuts), failures, skipped,
               report["timings"].get("total_s", 0), quoteattr(report["started"]))]
    out.append("  <properties>")
    props = [("target", report["target"]), ("brickproof", report["brickproof"])]
    props += [("firmware." + i["file"], i["sha256"]) for i in report["inputs"]]
    if report["coverage"]:
        cov = report["coverage"]
        props += [("coverage.operations", cov["operations"]),
                  ("coverage.distinct_states", cov["distinct_states"]),
                  ("coverage.cuts", cov["cuts"]), ("coverage.exhaustive", cov["exhaustive"])]
    for name, value in props:
        out.append("    <property name=%s value=%s/>" % (quoteattr(name), quoteattr(str(value))))
    out.append("  </properties>")
    for c in cuts:
        head = '  <testcase classname=%s name=%s time="%.1f"' % (
            quoteattr("brickproof.%s.%s" % (report["adapter"], group(c))), quoteattr(c["cut"]),
            c["seconds"])
        if c["passed"]:
            out.append(head + "/>")
        elif c["skipped"]:
            out.append(head + ">\n    <skipped message=%s/>\n  </testcase>" % quoteattr(c["message"]))
        else:
            detail = "%s\n%s\nreproduce: %s" % (c["message"], where(c), reproduce(report, c))
            if export_command(report, c):
                detail += "\non a board: %s" % export_command(report, c)
            out.append(head + ">\n    <failure message=%s>%s</failure>\n  </testcase>" % (
                quoteattr(c["message"] or "failed"), escape(detail)))
    out.append("</testsuite>")
    return "\n".join(out) + "\n"


# ---- HTML ----------------------------------------------------------------------

STYLE = """
:root { --bg:#fbfaf7; --fg:#1d1f21; --dim:#5f6368; --line:#dcd9d2; --card:#ffffff;
        --ok:#1a7f4b; --bad:#b42318; --warn:#8a5a00; --okbg:#e6f4ec; --badbg:#fdecea; --mono:#f1efe9; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16181b; --fg:#e7e5e0; --dim:#9aa0a6; --line:#2e3238; --card:#1d2024;
          --ok:#5fd38d; --bad:#ff8a80; --warn:#f2c26b; --okbg:#173225; --badbg:#3a1c1a; --mono:#24282d; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 28px 16px 60px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 34px 0 10px; }
p { margin: 6px 0; }
.dim { color: var(--dim); }
code, .mono { font: 13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace; }
code { background: var(--mono); padding: 1px 5px; border-radius: 4px; }
.verdict { display:inline-block; padding: 6px 14px; border-radius: 6px; font-weight: 600;
           margin: 14px 0 6px; }
.verdict.ok { background: var(--okbg); color: var(--ok); }
.verdict.bad { background: var(--badbg); color: var(--bad); }
.tiles { display:grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px;
         margin: 14px 0; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
.tile b { display:block; font-size: 20px; }
.tile.bad b { color: var(--bad); }
.wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: var(--card); }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td.msg { white-space: normal; min-width: 260px; }
td.msg code { white-space: nowrap; display: inline-block; margin-top: 3px; }
th { font-weight: 600; color: var(--dim); font-size: 13px; }
tr:last-child td { border-bottom: 0; }
.ok { color: var(--ok); } .bad { color: var(--bad); } .skip { color: var(--warn); }
details { margin: 8px 0; }
summary { cursor: pointer; color: var(--dim); }
.note { border-left: 3px solid var(--line); padding: 2px 12px; color: var(--dim); margin: 10px 0; }
"""


def _e(text):
    return html.escape(str(text))


def _status(c):
    if c["skipped"]:
        return '<span class="skip">skipped</span>'
    return '<span class="ok">pass</span>' if c["passed"] else '<span class="bad">FAIL</span>'


def _rows(report, cuts, with_repro):
    rows = []
    for c in cuts:
        note = c["message"] or (("runs " + c["image"]) if c["passed"] and c["image"] else "")
        cells = [_status(c), "<span class='mono'>%s</span>" % _e(c["cut"]),
                 "" if c["op_index"] is None else str(c["op_index"]),
                 "<span class='mono'>%s</span>" % _e(where(c)), "%.1f s" % c["seconds"]]
        row = "<tr>" + "".join("<td>%s</td>" % x for x in cells) + "<td class='msg'>%s" % _e(note)
        if with_repro:
            row += "<br><code>%s</code>" % _e(reproduce(report, c))
            if export_command(report, c):
                row += "<br><code>%s</code>" % _e(export_command(report, c))
        rows.append(row + "</td></tr>")
    return ("<div class='wrap'><table><tr><th>Result</th><th>Run</th><th>Op</th><th>Where</th>"
            "<th>Time</th><th>Finding</th></tr>%s</table></div>" % "".join(rows))


def _coverage(cov):
    rows = "".join(
        "<tr><td class='mono'>%d to %d</td><td>%s</td><td class='mono'>%s .. %s</td><td>%d</td>"
        "<td>%s</td></tr>" % (p["first"], p["last"], _e(p["kind"]), p["start"], p["end"],
                              p["distinct_states"],
                              "all" if p["cuts"] == p["distinct_states"] else "%d sampled" % p["cuts"])
        for p in cov["phases"])
    text = ("Every distinct flash state the update goes through was cut." if cov["exhaustive"] else
            "Some phases were sampled, not cut at every state. The table says which.")
    return ("<p>%d operations, %d distinct flash states, %d cut. %s</p><div class='wrap'><table>"
            "<tr><th>Operations</th><th>Kind</th><th>Addresses</th><th>Distinct states</th>"
            "<th>Cut</th></tr>%s</table></div>" % (
                cov["operations"], cov["distinct_states"], cov["cuts"], text, rows))


def _regulations(rows):
    marks = {"shown": "<span class='ok'>shown</span>", "not shown": "<span class='bad'>not shown</span>",
             "not tested": "<span class='skip'>not tested</span>"}
    body = "".join(
        "<tr><td><a href='%s'>%s</a><br><span class='mono'>%s</span></td><td class='msg'>%s</td>"
        "<td>%s</td><td class='msg'>%s%s</td><td class='msg'>%s</td></tr>" % (
            _e(r["url"]), _e(r["source"]), _e(r["clause"]), _e(r["asks"]), marks[r["status"]],
            _e(r["shows"]), ("<br><span class='dim'>This run: %s.</span>" % _e(r["detail"]))
            if r["detail"] else "", _e(r["not"])) for r in rows)
    return ("<h2>Where this evidence fits</h2>"
            "<p class='note'>A map, not a verdict. Whether a regulation is met is decided for a "
            "manufacturer's whole process by an authority or a notified body. The clause summaries "
            "are paraphrases; the published text is the one that counts.</p>"
            "<div class='wrap'><table><tr><th>Clause</th><th>What it asks</th><th>This run</th>"
            "<th>What a passing run shows</th><th>What it does not show</th></tr>%s</table></div>" % body)


def html_page(report):
    """One self-contained page: verdict, what was covered, failures first, then everything."""
    cuts = report["cuts"]
    failed = [c for c in cuts if not c["passed"] and not c["skipped"]]
    groups = {}
    for c in cuts:
        groups.setdefault(group(c), []).append(c)

    tiles = []
    for name, items in groups.items():
        ran = [c for c in items if not c["skipped"]]
        bad = sum(1 for c in ran if not c["passed"])
        label = {"baseline": "baseline", "cut": "clean cuts", "torn": "torn states"}.get(
            name, "after %s cuts in a row" % name.split("-")[-1])
        tiles.append("<div class='tile%s'><b>%d / %d</b>%s passed</div>" % (
            " bad" if bad else "", len(ran) - bad, len(ran), label))

    out = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width, initial-scale=1'>",
           "<title>BrickProof: %s</title><style>%s</style></head><body><main>" % (
               _e(report["adapter"]), STYLE),
           "<h1>BrickProof report: %s</h1>" % _e(report["adapter"]),
           "<p class='dim'>target <code>%s</code> &middot; %s &middot; brickproof %s &middot; %.0f s</p>" % (
               _e(report["target"]), _e(report["started"]), _e(report["brickproof"]),
               report["timings"].get("total_s", 0))]
    if report["passed"]:
        out.append("<div class='verdict ok'>PASS: every run recovered</div>")
    else:
        out.append("<div class='verdict bad'>FAIL: %d run(s) did not recover</div>" % len(failed))
    out.append("<div class='tiles'>%s</div>" % "".join(tiles))

    if failed:
        out.append("<h2>Failures</h2>")
        out.append(_rows(report, failed, with_repro=True))

    out.append("<h2>What was covered</h2>")
    if report["coverage"]:
        out.append(_coverage(report["coverage"]))
    else:
        out.append("<p>No plan: the update did not pass uninterrupted, or no golden run exists.</p>")
    if report.get("shard"):
        sh = report["shard"]
        out.append("<p><strong>Shard %d of %d.</strong> This run made %d of the campaign's %d cuts. "
                   "The whole campaign is covered only by all the shards together.</p>"
                   % (sh["index"], sh["of"], sh["cuts"], sh["all_cuts"]))
    if report.get("update"):
        out += ["<p>%s</p>" % _e(line[0].upper() + line[1:] + ".")
                for line in traces.describe_cost(report["update"], report["update"]["timing"])]
    if report["depth"]:
        d = report["depth"]
        out.append("<p>Cuts during recovery: up to %d in a row, %d new flash states tested, %d more "
                   "led to a state already tested%s.</p>" % (
                       min(d["levels"], d.get("deepest", d["levels"])), d["states"], d["skipped_known"],
                       ", stopped at the state limit" if d["capped"] else ""))

    out.append("<h2>How to read this</h2>")
    notes = [
        "A clean cut is power lost just before a flash operation. Only flash survives a power "
        "cut, so two cuts that leave the same flash are the same test, and only distinct flash "
        "states are cut.",
        "After each cut the emulated flash is compared, byte for byte, with what the "
        "uninterrupted run predicts for that point. A mismatch stops the run.",
    ]
    if report["oracle"]:
        notes.append("Each verdict is checked from outside the firmware: the installed bytes must "
                     "be exactly an approved image, and the CPU must be running inside it, not in "
                     "a fault handler. The finding column names the image.")
    else:
        notes.append("This adapter has no oracle section, so each verdict rests on what the "
                     "firmware reports about itself.")
    if "torn" in groups:
        notes.append("Torn states are shapes of a half-done erase or program. erase-early and "
                     "erase-late are measured on an STM32F103 whose erase was stopped by a reset; "
                     "the others follow what flash cells do but are not measured, and a real power "
                     "loss has not been measured yet.")
    notes.append("Not modelled: write protection, read protection, option bytes, flash timing, wear.")
    out.append("".join("<p class='note'>%s</p>" % _e(n) for n in notes))

    if report.get("regulations"):
        out.append(_regulations(report["regulations"]))

    out.append("<h2>Firmware tested</h2><div class='wrap'><table><tr><th>File</th><th>SHA-256</th></tr>")
    out.append("".join("<tr><td class='mono'>%s</td><td class='mono'>%s</td></tr>" % (
        _e(i["file"]), _e(i["sha256"])) for i in report["inputs"]))
    out.append("</table></div>")

    out.append("<h2>All runs</h2>")
    for name, items in groups.items():
        bad = sum(1 for c in items if not c["passed"] and not c["skipped"])
        out.append("<details%s><summary>%s: %d run(s), %d failed</summary>%s</details>" % (
            " open" if name == "baseline" or bad else "", _e(group_title(name)), len(items), bad,
            _rows(report, items, with_repro=False)))
    out.append("</main></body></html>")
    return "\n".join(out) + "\n"
