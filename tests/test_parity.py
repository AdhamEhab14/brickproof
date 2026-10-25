"""The parity check (tools/parity.py): what counts as the same result, and what does not."""
import copy
import importlib.util
import json
import os

import pytest

spec = importlib.util.spec_from_file_location(
    "parity", os.path.join(os.path.dirname(__file__), "..", "tools", "parity.py"))
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)


def cut(name, passed=True, message="", **kw):
    c = dict(cut=name, fired=name != "baseline (no cut)", kind="program", addr=0x08000000,
             op_index=0, alive=passed, recovered=passed, passed=passed, skipped=False,
             baseline=name == "baseline (no cut)", rewound=False, image="v2" if passed else None,
             torn=None, depth=1, computed=False, content=None, link=None, bit_error=None,
             message=message, seconds=1.5, hung=False)
    c.update(kw)
    return c


def report(adapter="demo.yaml", cuts=None, passed=True, shard=None):
    return {"adapter_file": adapter, "passed": passed, "shard": shard, "depth": None,
            "coverage": {"mode": "every", "operations": 3, "distinct_states": 3, "cuts": 3,
                         "exhaustive": True, "phases": []},
            "timings": {"total_s": 12.0}, "started": "2026-10-25T00:00:00Z",
            "cuts": cuts if cuts is not None else [cut("baseline (no cut)"), cut("op-0"), cut("op-1")]}


def write(folder, reports):
    for i, r in enumerate(reports):
        d = folder / ("job%d" % i)
        d.mkdir()
        (d / "out.json").write_text(json.dumps(r))
    return str(folder)


def check(tmp_path, before, after):
    base = parity.collect(write(tmp_path / "a", before))
    return parity.compare(base, parity.collect(write(tmp_path / "b", after)))


@pytest.fixture(autouse=True)
def folders(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()


def test_the_same_results_with_other_timings_are_the_same(tmp_path):
    later = report()
    later["timings"]["total_s"] = 99.0
    for c in later["cuts"]:
        c["seconds"], c["hung"] = 40.0, True
    assert check(tmp_path, [report()], [later]) == ([], [])


def test_a_campaign_that_no_longer_runs_is_an_error(tmp_path):
    errors, _ = check(tmp_path, [report(), report("other.yaml")], [report()])
    assert errors == ["missing: other.yaml | plan every"]


def test_a_changed_verdict_is_an_error(tmp_path):
    after = report(cuts=[cut("baseline (no cut)"), cut("op-0"), cut("op-1", passed=False, message="bricked")],
                   passed=False)
    errors, _ = check(tmp_path, [report()], [after])
    assert any("passed was true, now false" in e for e in errors)
    assert any("op-1 changed" in e and "recovered" in e for e in errors)


def test_a_cut_added_or_lost_is_named_not_shifted(tmp_path):
    after = report(cuts=[cut("baseline (no cut)"), cut("op-0"), cut("op-5"), cut("op-1")])
    errors, _ = check(tmp_path, [report()], [after])
    assert errors == ["demo.yaml | plan every: op-5 is new"]


def test_another_failure_message_on_a_cut_that_fails_either_way_is_a_warning(tmp_path):
    def failing(msg):
        return report(passed=False, cuts=[cut("baseline (no cut)"), cut("op-9", passed=False, message=msg)])
    errors, warnings = check(tmp_path, [failing("locked up")], [failing("flash changed at 0x18")])
    assert errors == [] and len(warnings) == 1


def test_a_message_on_a_passing_cut_is_part_of_the_result(tmp_path):
    after = copy.deepcopy(report())
    after["cuts"][1]["message"] = "rewound"
    errors, _ = check(tmp_path, [report()], [after])
    assert len(errors) == 1


def test_shards_and_run_modes_are_separate_campaigns(tmp_path):
    torn = report(cuts=[cut("baseline (no cut)"), cut("op-0 erase-half", torn="erase-half")])
    one = report(shard={"index": 1, "of": 2, "all_cuts": 4, "cuts": 2})
    two = report(shard={"index": 2, "of": 2, "all_cuts": 4, "cuts": 2})
    found = parity.collect(write(tmp_path / "a", [report(), torn, one, two]))
    assert sorted(found) == ["demo.yaml | plan every", "demo.yaml | plan every | torn",
                             "demo.yaml | shard 1/2 | plan every", "demo.yaml | shard 2/2 | plan every"]


def test_the_baseline_file_reads_back_as_written(tmp_path):
    found = parity.collect(write(tmp_path / "a", [report(), report("other.yaml")]))
    path = str(tmp_path / "baseline.json")
    parity.dump(found, "a test", path)
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["scenarios"] == found


def test_files_that_are_not_reports_are_skipped(tmp_path):
    folder = tmp_path / "a"
    (folder / "sarif.json").write_text(json.dumps({"version": "2.1.0", "runs": []}))
    (folder / "broken.json").write_text("{")
    assert parity.collect(str(folder)) == {}


def test_the_committed_baseline_is_well_formed():
    path = os.path.join(os.path.dirname(__file__), "parity", "baseline.json")
    with open(path, encoding="utf-8") as f:
        base = json.load(f)
    assert base["source"] and len(base["scenarios"]) >= 80
    for k, s in base["scenarios"].items():
        assert set(s) == {"passed", "coverage", "depth", "shard", "cuts"}, k
        assert all(len(row) == len(parity.CUT_FIELDS) for row in s["cuts"]), k
