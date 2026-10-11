"""JUnit and HTML reports, built from real campaigns against the simulated device."""
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from types import SimpleNamespace

from brickproof import report as reports
from brickproof import runner
from brickproof import torn
from brickproof.oracle import Image, Oracle
from fake_device import NEW_IMAGE, OLD_IMAGE, SLOT, FakeDevice, FakeDriver

DEPTH = {"levels": 2, "mode": "every", "per_phase": 2, "small": 6, "max_states": 2000}


def make_report(device, torn_kinds=None, depth=None, oracle=True, name="fake <target> & co"):
    ad = SimpleNamespace(name=name, path="adapters/fake/adapter.yaml", target="/x/fake",
                         flash=device.flash, check_states=True, cut_limit=0.03, update_time=1.0,
                         boot_settle=0.1, cuts=[], plan={"mode": "every"}, torn=torn_kinds,
                         torn_seed=0, depth=depth,
                         oracle={"accept": ["new"]} if oracle else None)
    images = [Image("old", OLD_IMAGE, SLOT), Image("new", NEW_IMAGE, SLOT)]
    judge = Oracle(images, ["new"]) if oracle else None
    out = runner.campaign(device, FakeDriver(device), ad, oracle=judge)
    out.started = "2026-10-11T12:00:00Z"
    out.inputs = [{"file": "boot.elf", "sha256": "ab" * 32}]
    out.timings = {"setup_s": 1.0, "total_s": 12.5, "rewound": 0}
    return runner.as_dict(out, ad)


def good():
    return make_report(FakeDevice(), torn_kinds=list(torn.KINDS))


def bad():
    return make_report(FakeDevice(retry_limit=True), depth=DEPTH)


# ---- JUnit ---------------------------------------------------------------------

def test_junit_is_well_formed_and_counts_match():
    rep = bad()
    suite = ET.fromstring(reports.junit(rep))
    cases = suite.findall("testcase")
    assert int(suite.get("tests")) == len(cases) == len(rep["cuts"])
    failed = [c for c in rep["cuts"] if not c["passed"] and not c["skipped"]]
    assert int(suite.get("failures")) == len(suite.findall("testcase/failure")) == len(failed) > 0
    assert suite.get("timestamp") == "2026-10-11T12:00:00Z" and suite.get("time") == "12.5"


def test_junit_groups_results_by_kind():
    suite = ET.fromstring(reports.junit(make_report(FakeDevice(retry_limit=True), depth=DEPTH,
                                                    torn_kinds=list(torn.KINDS), name="fake")))
    classes = {c.get("classname") for c in suite.findall("testcase")}
    assert classes == {"brickproof.fake.baseline", "brickproof.fake.cut", "brickproof.fake.torn",
                       "brickproof.fake.depth-2"}


def test_a_junit_failure_says_why_where_and_how_to_reproduce():
    rep = bad()
    failure = ET.fromstring(reports.junit(rep)).find("testcase/failure")
    assert failure.get("message")
    assert "reproduce: brickproof run adapters/fake/adapter.yaml --cut" in failure.text
    assert "--depth 2" in failure.text


def test_junit_carries_coverage_and_firmware_hashes():
    suite = ET.fromstring(reports.junit(good()))
    props = {p.get("name"): p.get("value") for p in suite.findall("properties/property")}
    assert props["firmware.boot.elf"] == "ab" * 32
    assert props["coverage.distinct_states"] == "10" and props["coverage.exhaustive"] == "True"


def test_junit_escapes_awkward_names():
    xml = reports.junit(good())
    assert "fake &lt;target&gt; &amp; co" in xml
    ET.fromstring(xml)


def test_a_skipped_range_cut_is_marked_skipped():
    device = FakeDevice()
    from brickproof.adapter import Cut
    ad = SimpleNamespace(name="f", path="a.yaml", target="/f", flash=device.flash, check_states=True,
                         cut_limit=0.03, update_time=1.0, boot_settle=0.1,
                         cuts=[Cut(name="op-99", at_op=99, group=0)])
    out = runner.campaign(device, FakeDriver(device), ad)
    out.started = "t"
    suite = ET.fromstring(reports.junit(runner.as_dict(out, ad)))
    assert suite.get("skipped") == "1" and suite.find("testcase/skipped") is not None
    assert suite.get("failures") == "0"


# ---- HTML ----------------------------------------------------------------------

class Outline(HTMLParser):
    """Checks tags are balanced and collects the text."""
    VOID = {"meta", "br"}

    def __init__(self):
        super().__init__()
        self.stack, self.text, self.problems = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.problems.append(tag)

    def handle_data(self, data):
        self.text.append(data)


def parse(page):
    o = Outline()
    o.feed(page)
    return o


def test_html_is_balanced_and_self_contained():
    page = reports.html_page(bad())
    o = parse(page)
    assert o.problems == [] and o.stack == []
    # nothing is loaded from outside: no scripts, stylesheets, images or fonts.
    # Links to the regulation texts are plain hyperlinks.
    for tag in ("<script", "<link", "<img", "<iframe", "@import", "url("):
        assert tag not in page, tag
    assert "<style>" in page
    assert "prefers-color-scheme: dark" in page and "viewport" in page


def test_a_passing_page_says_pass_and_counts_each_group():
    page = reports.html_page(good())
    text = " ".join(parse(page).text)
    assert "PASS: every run recovered" in text and "Failures" not in text
    assert "10 / 10" in text and "clean cuts passed" in text and "torn states passed" in text
    assert "Every distinct flash state the update goes through was cut." in text
    assert "not been calibrated against real hardware" in text
    assert "runs new" in text


def test_a_failing_page_puts_failures_first_with_a_command_to_reproduce():
    page = reports.html_page(bad())
    text = " ".join(parse(page).text)
    assert "FAIL:" in text and "did not recover" in text
    assert page.index("<h2>Failures</h2>") < page.index("<h2>What was covered</h2>")
    assert "brickproof run adapters/fake/adapter.yaml --cut" in text and "--depth 2" in text
    assert "Cuts during recovery: up to 2 in a row" in text


def test_html_escapes_what_it_shows():
    page = reports.html_page(good())
    assert "fake &lt;target&gt; &amp; co" in page and "<target>" not in page


def test_html_says_so_when_there_is_no_oracle():
    text = " ".join(parse(reports.html_page(make_report(FakeDevice(), oracle=False))).text)
    assert "has no oracle section" in text


def test_html_lists_the_firmware_hashes():
    assert "ab" * 32 in reports.html_page(good())


def test_a_failed_baseline_still_makes_a_page():
    rep = make_report(FakeDevice(fault_at=2))
    page = reports.html_page(rep)
    assert parse(page).problems == []
    assert "No plan" in page and "bus fault" in page
    ET.fromstring(reports.junit(rep))


# ---- reproduce -----------------------------------------------------------------

def test_reproduce_commands_per_kind():
    rep = {"adapter_file": "a.yaml"}
    base = dict(baseline=False, torn=None, depth=1, op_index=7, cut="op-7")
    assert reports.reproduce(rep, base) == "brickproof run a.yaml --cut 7"
    assert reports.reproduce(rep, dict(base, torn="erase-half", cut="op-7 erase-half")) == \
        "brickproof run a.yaml --cut 7 --torn"
    assert reports.reproduce(rep, dict(base, depth=2, op_index=3, cut="op-7 > op-3")) == \
        "brickproof run a.yaml --cut 7 --depth 2"
    assert reports.reproduce(rep, dict(base, baseline=True, op_index=10)) == "brickproof run a.yaml --cut 0"


# ---- where the evidence fits ---------------------------------------------------------

def rows(report):
    return {r["id"]: r for r in report["regulations"]}


def test_a_passing_run_with_an_oracle_shows_what_it_can_and_no_more():
    r = rows(good())
    assert r["r156-7.2.2.1.1"]["status"] == "shown" and r["cra-I-2-h"]["status"] == "shown"
    assert "10 of its 10 distinct flash states" in r["r156-7.2.2.1.1"]["detail"]
    assert "torn" in r["r156-7.2.2.1.1"]["detail"]
    assert r["r156-7.2.2.1.2"]["status"] == "not tested", "the power check is outside a run"
    assert all(x["not"] and x["asks"] and x["url"].startswith("https://") for x in r.values())


def test_a_failing_run_shows_nothing():
    r = rows(bad())
    assert {x["status"] for x in r.values()} == {"not shown", "not tested"}
    assert "run(s) failed" in r["r156-7.2.2.1.1"]["detail"]


def test_without_an_oracle_the_integrity_clauses_are_not_shown():
    r = rows(make_report(FakeDevice(), oracle=False))
    assert r["r156-7.2.2.1.1"]["status"] == "shown", "recovery does not need the oracle"
    assert r["r156-7.2.1.1"]["status"] == "not shown" and "no oracle" in r["r156-7.2.1.1"]["detail"]
    assert r["cra-I-2-f"]["status"] == "not shown"


def test_the_page_has_the_map_with_its_disclaimer_and_links():
    page = reports.html_page(good())
    text = " ".join(parse(page).text)
    assert "Where this evidence fits" in text and "A map, not a verdict" in text
    assert "7.2.2.1.1" in text and "Annex I, Part I, (2)(h)" in text
    assert "href='https://unece.org/" in page and "href='https://eur-lex.europa.eu/" in page
