"""The cut planner: only distinct flash states, exhaustive or sampled, and honest about which."""
from types import SimpleNamespace

import pytest

from brickproof import adapter as adapters
from brickproof import plan as plans
from brickproof import runner
from brickproof.engine.session import FlashGeometry
from fake_device import FakeDevice, FakeDriver

BASE = 0x08000000
PAGE = 0x400
FLASH = FlashGeometry(base=BASE, size=8 * PAGE, page=PAGE)


def erase(i, addr):
    return {"index": i, "kind": "erase", "addr": addr}


def prog(i, addr, value):
    return {"index": i, "kind": "program", "addr": addr, "value": value}


def copy(first, start, values):
    return [prog(first + k, start + 2 * k, v) for k, v in enumerate(values)]


def blank():
    return bytes([0xFF]) * FLASH.size


def test_an_operation_that_changes_nothing_adds_no_state():
    pre = bytearray(blank())
    pre[PAGE:PAGE + 2] = b"\x34\x12"
    # erase a used page, erase an already-erased page, program data, program 0xFFFF over erased
    ops = [erase(0, BASE + PAGE), erase(1, BASE + 2 * PAGE),
           prog(2, BASE + PAGE, 0xBEEF), prog(3, BASE + PAGE + 2, 0xFFFF)]
    assert plans.changes(ops, bytes(pre), FLASH) == [True, False, True, False]


def test_refused_and_inferred_programs_change_nothing():
    ops = [{"index": 0, "kind": "refused", "addr": BASE, "value": 1, "old": 2},
           {"index": 1, "kind": "program", "addr": BASE + 2, "inferred": True}]
    assert plans.changes(ops, blank(), FLASH) == [False, False]


def test_every_cuts_each_distinct_state_and_nothing_else():
    # 6 halfwords, two of them 0xFFFF: cutting before the op after each of those shows
    # the same flash as the cut before it
    ops = [erase(0, BASE)] + copy(1, BASE, [1, 0xFFFF, 3, 0xFFFF, 5, 6])
    pre = bytes([0x00]) * FLASH.size
    plan = plans.make(ops, pre, FLASH, mode="every")
    assert plan.cuts == [0, 1, 2, 4, 6]         # not 3 (after op 2) and not 5 (after op 4)
    assert plan.distinct == 5 and plan.operations == 7 and plan.exhaustive
    assert "every state is cut" in plan.summary()


def test_op_0_is_always_a_state_even_if_nothing_precedes_it():
    plan = plans.make([prog(0, BASE, 0xFFFF)], blank(), FLASH, mode="every")
    assert plan.cuts == [0]


def test_a_long_phase_is_sampled_at_its_edges_and_in_between():
    ops = [erase(0, BASE)] + copy(1, BASE, range(1, 201))     # 200 distinct halfwords
    plan = plans.make(ops, bytes(FLASH.size), FLASH, mode="phases", per_phase=3, small=12)
    erase_phase, copy_phase = plan.phases
    assert erase_phase.cuts == [0] and erase_phase.complete
    assert copy_phase.distinct == 200 and not copy_phase.complete
    cuts = copy_phase.cuts
    assert cuts[:2] == [1, 2] and cuts[-2:] == [199, 200], "both ends, two deep"
    assert len(cuts) == 4 + 3 and cuts == sorted(set(cuts))
    assert not plan.exhaustive and "1 of 2 phases are sampled" in plan.summary()


def test_a_short_phase_is_cut_everywhere_even_when_sampling():
    ops = [erase(0, BASE)] + copy(1, BASE, range(1, 9))
    plan = plans.make(ops, bytes(FLASH.size), FLASH, mode="phases", per_phase=2, small=12)
    assert plan.cuts == list(range(9)) and plan.exhaustive


def test_sampling_never_picks_more_than_there_is():
    ops = copy(0, BASE, range(1, 15))                        # 14 states, small=4
    plan = plans.make(ops, blank(), FLASH, mode="phases", per_phase=50, small=4)
    assert plan.cuts == list(range(14))


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="mode"):
        plans.make([], blank(), FLASH, mode="random")


def test_the_report_names_what_was_sampled():
    ops = [erase(0, BASE)] + copy(1, BASE, range(1, 201))
    d = plans.make(ops, bytes(FLASH.size), FLASH, per_phase=3).as_dict()
    assert d["operations"] == 201 and d["distinct_states"] == 201 and d["exhaustive"] is False
    assert [p["cuts"] for p in d["phases"]] == [1, 7]
    assert d["phases"][1]["start"] == "0x08000000"


# ---- in a campaign ---------------------------------------------------------------

def run(device, plan, cuts=()):
    ad = SimpleNamespace(flash=device.flash, check_states=True, cut_limit=0.03, update_time=1.0,
                         boot_settle=0.1, cuts=list(cuts), plan=plan)
    return runner.campaign(device, FakeDriver(device), ad)


def test_a_planned_campaign_cuts_every_state_of_the_simulated_update():
    out = run(FakeDevice(), {"mode": "every"})
    cut = [r.op_index for r in out.results[1:]]
    assert cut == out.plan.cuts == list(range(10))
    assert all(r.passed for r in out.results) and out.plan.exhaustive
    assert runner.as_dict(out, SimpleNamespace(name="f", target="/f"))["coverage"]["cuts"] == 10


def test_a_listed_cut_is_not_run_twice_when_the_plan_also_has_it():
    out = run(FakeDevice(), {"mode": "every"}, cuts=[adapters.Cut(name="mine", at_op=3)])
    names = [r.cut for r in out.results[1:]]
    assert names.count("mine") == 1 and "op-3" not in names and len(names) == 10


def test_without_a_plan_only_the_listed_cuts_run_but_the_plan_is_still_reported():
    out = run(FakeDevice(), None, cuts=[adapters.Cut(name="mine", at_op=3)])
    assert [r.cut for r in out.results[1:]] == ["mine"]
    assert out.plan.distinct == 10, "what the trace offers is known either way"


def test_a_failed_baseline_has_no_plan():
    out = run(FakeDevice(fault_at=2), {"mode": "every"})
    assert out.plan is None and len(out.results) == 1 and not out.passed


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
"""


def load(tmp_path, plan_yaml):
    p = tmp_path / "adapter.yaml"
    p.write_text(YAML + plan_yaml)
    return adapters.load(str(p))


def test_plan_can_be_a_name_or_a_mapping(tmp_path):
    assert load(tmp_path, "  cut_limit: 1\n").plan is None
    assert load(tmp_path, "  plan: every\n").plan == {"mode": "every"}
    assert load(tmp_path, "  plan: {per_phase: 4}\n").plan == {"mode": "phases", "per_phase": 4}
    assert load(tmp_path, "  plan: {mode: phases, per_phase: 2, small: 6}\n").plan == {
        "mode": "phases", "per_phase": 2, "small": 6}


@pytest.mark.parametrize("bad", ["  plan: random\n", "  plan: {mode: every, depth: 2}\n",
                                 "  plan: {per_phase: -1}\n", "  plan: [every]\n"])
def test_a_bad_plan_is_rejected(tmp_path, bad):
    with pytest.raises(adapters.AdapterError, match="plan"):
        load(tmp_path, bad)


# ---- real_every: most cuts from the computed state, some made for real ---------------

def test_real_every_makes_some_cuts_for_real_and_computes_the_rest():
    out = run(FakeDevice(), {"mode": "every", "real_every": 4})
    cuts = out.results[1:]
    assert [r.op_index for r in cuts] == list(range(10)) and all(r.passed for r in cuts)
    real = [r.op_index for r in cuts if not r.computed]
    assert real == [0, 4, 8, 9], "every fourth, and always the last"
    assert all(r.kind in ("erase", "program") and r.addr for r in cuts)


def test_computed_cuts_fail_where_real_ones_would():
    real = run(FakeDevice(no_recovery=True), {"mode": "every"})
    mixed = run(FakeDevice(no_recovery=True), {"mode": "every", "real_every": 3})
    assert [r.passed for r in mixed.results] == [r.passed for r in real.results]
    assert any(r.computed and not r.passed for r in mixed.results)


def test_a_listed_cut_with_an_expectation_is_always_made_for_real():
    listed = [adapters.Cut(name="mine", at_op=3, expect=(2, 0))]
    out = run(FakeDevice(), {"mode": "every", "real_every": 100}, cuts=listed)
    mine = next(r for r in out.results if r.cut == "mine")
    assert not mine.computed and mine.passed


def test_real_every_is_read_from_the_adapter(tmp_path):
    assert load(tmp_path, "  plan: {mode: every, real_every: 25}\n").plan == {
        "mode": "every", "real_every": 25}


def test_word_programs_and_sector_erases_are_states_too():
    f4 = FlashGeometry(base=BASE, size=0x6000, write_unit=4,
                       sectors=[(0, 0x1000), (0x1000, 0x1000), (0x2000, 0x4000)])
    pre = bytes([0xFF]) * 0x2000 + bytes(0x4000)
    ops = [{"index": 0, "kind": "erase", "addr": BASE + 0x2000},              # wipes 16 KB of zeros
           {"index": 1, "kind": "erase", "addr": BASE + 0x1000},              # already erased
           {"index": 2, "kind": "program", "addr": BASE + 0x2000, "value": 0xFFFF0000, "size": 4},
           {"index": 3, "kind": "program", "addr": BASE + 0x2004, "value": 0xFFFFFFFF, "size": 4}]
    assert plans.changes(ops, pre, f4) == [True, False, True, False]
