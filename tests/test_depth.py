"""Cuts during recovery: a second power loss while the device recovers from the first."""
from types import SimpleNamespace

import pytest

from brickproof import adapter as adapters
from brickproof import runner
from fake_device import FakeDevice, FakeDriver

DEPTH = {"levels": 2, "mode": "every", "per_phase": 2, "small": 6, "max_states": 2000}


def run(device, depth=DEPTH, **kw):
    ad = SimpleNamespace(flash=device.flash, check_states=True, cut_limit=0.03, update_time=1.0,
                         boot_settle=0.1, cuts=[], plan={"mode": "every"}, depth=depth)
    return runner.campaign(device, FakeDriver(device), ad, **kw)


def deep(out):
    return [r for r in out.results if r.depth > 1]


def test_a_restartable_updater_has_no_new_state_at_depth_2():
    # this updater recovers by doing the whole update again from the start, so a cut
    # during recovery lands on a flash state a first cut already produced
    out = run(FakeDevice())
    assert deep(out) == []
    assert out.depth["states"] == 0 and out.depth["skipped_known"] > 0
    assert all(r.passed for r in out.results)


def test_a_retry_limit_survives_one_cut_and_fails_on_two():
    out = run(FakeDevice(retry_limit=True))
    first = [r for r in out.results[1:] if r.depth == 1]
    assert first and all(r.passed for r in first), "any single cut recovers"
    second = deep(out)
    assert second, "counting attempts makes new states"
    failed = [r for r in second if not r.passed]
    assert failed, "two interrupted attempts and it gives up with no image"
    assert all(" > " in r.cut and r.depth == 2 for r in second)


def test_without_depth_the_retry_limit_bug_is_invisible():
    out = run(FakeDevice(retry_limit=True), depth=None)
    assert out.depth is None and all(r.passed for r in out.results)


def test_deep_results_name_their_lineage_and_where_they_cut():
    out = run(FakeDevice(retry_limit=True))
    r = deep(out)[0]
    parent, child = r.cut.split(" > ")
    assert parent.startswith("op-") and child == "op-%d" % r.op_index
    assert r.kind in ("erase", "program") and r.addr


def test_the_first_new_cut_of_each_recovery_is_made_for_real():
    device = FakeDevice(retry_limit=True)
    armed = []
    set_cut = device.set_cut

    def spy(n):
        armed.append(n)
        set_cut(n)

    device.set_cut = spy
    out = run(device)
    clean = len([r for r in out.results[1:] if r.depth == 1])
    real_deep = len(armed) - clean
    parents = {r.cut.split(" > ")[0] for r in deep(out)}
    assert real_deep == len(parents), "one real cut per recovery that had something new"
    assert len(deep(out)) > real_deep, "the rest are powered up from the computed state"


def test_a_recovery_that_differs_from_its_trace_trips_the_self_check():
    device = FakeDevice(retry_limit=True)
    ad = SimpleNamespace(flash=device.flash, check_states=True, cut_limit=0.03, update_time=1.0,
                         boot_settle=0.1, cuts=[], plan={"mode": "every"}, depth=DEPTH)
    verify = runner.Golden.verify
    calls = {"n": 0}

    def scribble_then_verify(self, session, n, what):
        if what.startswith("recovery cut"):
            calls["n"] += 1
            session.mem[5] ^= 0xFF              # flash is no longer what the replay says
        return verify(self, session, n, what)

    runner.Golden.verify = scribble_then_verify
    try:
        with pytest.raises(runner.SelfCheckFailed, match="recovery cut"):
            runner.campaign(device, FakeDriver(device), ad)
    finally:
        runner.Golden.verify = verify
    assert calls["n"] == 1


def test_fail_fast_stops_at_the_first_deep_failure():
    out = run(FakeDevice(retry_limit=True), fail_fast=True)
    assert [r.passed for r in deep(out)].count(False) == 1 and not deep(out)[-1].passed


def test_max_states_caps_the_exploration_and_says_so():
    out = run(FakeDevice(retry_limit=True), depth=dict(DEPTH, max_states=3))
    assert len(deep(out)) == 3 and out.depth["capped"] is True


def test_three_levels_go_deeper_than_two():
    two = run(FakeDevice(retry_limit=True))
    three = run(FakeDevice(retry_limit=True), depth=dict(DEPTH, levels=3))
    assert three.depth["states"] >= two.depth["states"]
    assert max(r.depth for r in three.results) <= 3


def test_the_report_carries_what_was_explored():
    out = run(FakeDevice(retry_limit=True))
    d = runner.as_dict(out, SimpleNamespace(name="f", target="/f"))
    assert d["depth"]["levels"] == 2 and d["depth"]["states"] == len(deep(out))
    assert any(c["depth"] == 2 for c in d["cuts"])


# ---- from an adapter -------------------------------------------------------------

YAML = """
name: demo
target: fw
platform: {base: stm32f103}
flash: {base: 0x08000000, size: 0x10000, page: 0x400}
ram: {size: 0x5000}
firmware:
  - file: app.elf
driver: {file: driver.py}
scenario:
  plan: every
"""


def load(tmp_path, extra):
    p = tmp_path / "adapter.yaml"
    p.write_text(YAML + extra)
    return adapters.load(str(p))


def test_depth_is_off_by_default_and_at_1(tmp_path):
    assert load(tmp_path, "").depth is None
    assert load(tmp_path, "  depth: 1\n").depth is None


def test_depth_as_a_number_gets_the_defaults(tmp_path):
    assert load(tmp_path, "  depth: 2\n").depth == dict(adapters.DEPTH_DEFAULTS, levels=2)


def test_depth_as_a_mapping_overrides_them(tmp_path):
    d = load(tmp_path, "  depth: {levels: 3, per_phase: 0, max_states: 50}\n").depth
    assert (d["levels"], d["per_phase"], d["max_states"], d["mode"]) == (3, 0, 50, "phases")


@pytest.mark.parametrize("bad", ["  depth: deep\n", "  depth: {levels: 2, width: 3}\n",
                                 "  depth: {levels: 0}\n", "  depth: {mode: all}\n"])
def test_a_bad_depth_is_rejected(tmp_path, bad):
    with pytest.raises(adapters.AdapterError, match="depth"):
        load(tmp_path, bad)
