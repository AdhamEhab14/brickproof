"""CI's own plumbing: the scenario manifest, how it is shared out, and how it is run."""
import glob
import importlib.util
import json
import os
import re
import shlex
import sys

import pytest
import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")
spec = importlib.util.spec_from_file_location("scenarios", os.path.join(ROOT, "tools", "scenarios.py"))
scenarios = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenarios)

ALL = scenarios.load()


def test_every_scenario_is_well_formed():
    ids = [s["id"] for s in ALL]
    assert len(ids) == len(set(ids)), "an id is used twice"
    for s in ALL:
        assert set(s) <= {"id", "adapter", "args", "expect", "emulator", "minutes"}, s["id"]
        assert os.path.isfile(os.path.join(ROOT, s["adapter"])), s["id"]
        assert s["expect"] in (0, 1), s["id"]
        assert s["emulator"] in scenarios.EMULATORS, s["id"]
        assert s["minutes"] > 0, s["id"]
        assert not re.search(r"--(json|junit|html|sarif)\b", s["args"]), "the runner adds the reports"
        if s["expect"] == 1:
            assert "--fail-fast" in s["args"], "%s: a bug build stops at the first failure" % s["id"]


def test_every_demo_adapter_is_run():
    demo = {os.path.relpath(p, ROOT).replace(os.sep, "/")
            for p in glob.glob(os.path.join(ROOT, "examples", "demo_ab_bootloader", "*.yaml"))}
    assert demo - {s["adapter"] for s in ALL} == set()


def test_the_m33mu_chips_are_run_on_m33mu():
    for s in ALL:
        if "/h563" in s["adapter"]:
            assert s["emulator"] == "m33mu", s["id"]


def test_every_campaign_in_the_parity_baseline_is_still_run():
    with open(os.path.join(ROOT, "tests", "parity", "baseline.json"), encoding="utf-8") as f:
        base = json.load(f)["scenarios"]
    run = {s["adapter"] for s in ALL}
    run.add("adapters/three_tier_f103/adapter.yaml")             # the e2e job
    run.add("examples/demo_ab_bootloader/adapter.yaml")          # the action job
    assert {k.split(" | ")[0] for k in base} - run == set()


@pytest.mark.parametrize("n", [1, 3, 8])
def test_the_parts_hold_every_scenario_once(n):
    parts = scenarios.share(ALL, n)
    got = [s["id"] for p in parts for s in p]
    assert sorted(got) == sorted(s["id"] for s in ALL)


def test_the_parts_are_balanced_and_always_the_same():
    parts = scenarios.share(ALL, 8)
    totals = [sum(s["minutes"] for s in p) for p in parts]
    longest = max(s["minutes"] for s in ALL)
    assert max(totals) - min(totals) <= longest
    assert [[s["id"] for s in p] for p in scenarios.share(ALL, 8)] == [[s["id"] for s in p] for p in parts]


def test_a_part_and_an_id_select_what_they_say():
    one = scenarios.select(ALL, ids=["demo-f411"])
    assert [s["id"] for s in one] == ["demo-f411"]
    m33mu = scenarios.select(ALL, emulator="m33mu")
    assert m33mu and all(s["emulator"] == "m33mu" for s in m33mu)
    with pytest.raises(SystemExit):
        scenarios.select(ALL, ids=["no-such-scenario"])


def test_the_m33mu_commit_is_the_same_for_ci_and_for_the_action():
    with open(os.path.join(ROOT, "action.yml"), encoding="utf-8") as f:
        public = yaml.safe_load(f)["inputs"]["m33mu-ref"]["default"]
    with open(os.path.join(ROOT, ".github", "actions", "setup", "action.yml"), encoding="utf-8") as f:
        assert f.read().count(public) == 2, "the cache key and the checkout"


FAKE = """
import json, sys, time
args = sys.argv[1:]
adapter = args[1]
if "slow" in adapter:
    time.sleep(30)
out = args[args.index("--json") + 1]
json.dump({"adapter_file": adapter, "cuts": []}, open(out, "w"))
sys.exit(1 if "bug" in adapter else 0)
"""


def manifest(tmp_path, entries):
    for e in entries:
        (tmp_path / e["adapter"]).write_text("name: x\n")
    path = tmp_path / "scenarios.yaml"
    path.write_text(yaml.safe_dump({"scenarios": entries}))
    fake = tmp_path / "fake_brickproof.py"
    fake.write_text(FAKE)
    return str(path), "%s %s" % (shlex.quote(sys.executable), shlex.quote(str(fake)))


def test_run_checks_each_exit_code_and_writes_the_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(scenarios, "ROOT", str(tmp_path))
    path, command = manifest(tmp_path, [
        {"id": "good", "adapter": "good.yaml", "args": "-j 3", "expect": 0, "minutes": 1},
        {"id": "bug", "adapter": "bug.yaml", "args": "--fail-fast", "expect": 1, "minutes": 1},
    ])
    out = tmp_path / "out"
    assert scenarios.main(["run", "--manifest", path, "--command", command, "--out", str(out)]) == 0
    assert (out / "good.json").exists() and (out / "bug.json").exists()


def test_a_wrong_exit_code_fails_the_run_but_the_rest_still_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(scenarios, "ROOT", str(tmp_path))
    path, command = manifest(tmp_path, [
        {"id": "bug", "adapter": "bug.yaml", "args": "--fail-fast", "expect": 0, "minutes": 1},
        {"id": "good", "adapter": "good.yaml", "args": "", "expect": 0, "minutes": 1},
    ])
    out = tmp_path / "out"
    assert scenarios.main(["run", "--manifest", path, "--command", command, "--out", str(out)]) == 1
    assert (out / "good.json").exists()


def test_a_campaign_past_its_time_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(scenarios, "ROOT", str(tmp_path))
    monkeypatch.setattr(scenarios, "time_limit", lambda s: 2.0)
    path, command = manifest(tmp_path, [
        {"id": "slow", "adapter": "slow.yaml", "args": "", "expect": 0, "minutes": 1},
    ])
    code, secs = scenarios.run_one(scenarios.load(path)[0], shlex.split(command), str(tmp_path))
    assert code is None and secs < 20
