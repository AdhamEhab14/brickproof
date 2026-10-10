"""The runner's logic, against a simulated device (see fake_device.py). No emulator."""
from types import SimpleNamespace

import pytest

from brickproof import runner
from brickproof.adapter import Cut
from fake_device import MARKER, NEW_IMAGE, SLOT, FakeDevice, FakeDriver

UPDATE_OPS = 10          # 1 erase, 8 halfwords, 1 marker clear


def every_op(to=UPDATE_OPS + 5):
    return [Cut(name="op-%d" % n, at_op=n, group=0) for n in range(to + 1)]


def campaign(device, cuts=None, check_states=True, **kw):
    ad = SimpleNamespace(flash=device.flash, check_states=check_states, cut_limit=0.03,
                         update_time=1.0, boot_settle=0.1, cuts=every_op() if cuts is None else cuts)
    out = runner.campaign(device, FakeDriver(device), ad, **kw)
    return out.results, out.trace


def test_a_correct_updater_survives_a_cut_at_every_operation():
    results, trace = campaign(FakeDevice())
    base, cuts, skipped = results[0], results[1:-1], results[-1]
    assert base.baseline and base.passed and base.op_index == UPDATE_OPS
    assert len(trace) == UPDATE_OPS
    assert [r.op_index for r in cuts] == list(range(UPDATE_OPS))
    assert all(r.passed and r.fired for r in cuts)
    assert skipped.skipped and not skipped.fired


def test_a_range_stops_at_the_first_cut_past_the_end():
    results, _ = campaign(FakeDevice(), cuts=every_op(to=UPDATE_OPS + 50))
    assert sum(r.skipped for r in results) == 1
    assert len(results) == 1 + UPDATE_OPS + 1


def test_cut_results_carry_the_address_from_the_golden_run():
    results, _ = campaign(FakeDevice())
    assert (results[1].kind, results[1].addr) == ("erase", SLOT)
    assert (results[2].kind, results[2].addr) == ("program", SLOT)
    assert (results[UPDATE_OPS].kind, results[UPDATE_OPS].addr) == ("program", MARKER)


def test_a_program_that_landed_is_put_back_so_the_cut_is_before_it():
    device = FakeDevice(lands_after=True)
    seen = []

    class Spy(FakeDriver):
        def alive(self):
            seen.append(device.read_bytes(SLOT, 4))     # flash as the device powers up
            return super().alive()

    ad = SimpleNamespace(flash=device.flash, check_states=True, cut_limit=0.03, update_time=1.0,
                         boot_settle=0.0, cuts=[Cut(name="first-halfword", at_op=1)])
    results = runner.campaign(device, Spy(device), ad).results
    assert results[1].rewound and results[1].passed
    # seen[0] is the baseline. For the cut: op 1 is the first halfword, and just
    # before it the slot is erased and empty
    assert seen[1] == b"\xFF\xFF\xFF\xFF"


def test_no_rewind_when_the_cut_already_lands_before_the_write():
    results, _ = campaign(FakeDevice(lands_after=False))
    assert not any(r.rewound for r in results)
    assert all(r.passed or r.skipped for r in results)


def test_a_device_that_does_not_recover_fails_its_cuts():
    results, _ = campaign(FakeDevice(no_recovery=True))
    cuts = [r for r in results if r.fired]
    # cut before the erase: the old image still runs, but the update was lost
    assert not cuts[0].passed and cuts[0].alive and "not the new image" in cuts[0].message
    # cut after the erase: nothing valid is left
    assert not cuts[1].passed and not cuts[1].alive and "did not come back" in cuts[1].message
    assert results[0].passed, "the baseline itself is fine"


def test_fail_fast_stops_at_the_first_failure():
    results, _ = campaign(FakeDevice(no_recovery=True), fail_fast=True)
    assert len(results) == 2 and not results[1].passed


def test_a_failing_baseline_ends_the_run_before_any_cut():
    results, _ = campaign(FakeDevice(fault_at=3))
    assert len(results) == 1
    assert not results[0].passed and "bus fault" in results[0].message
    assert "0x20005000" in results[0].message


@pytest.mark.parametrize("option,text", [("refuse", "flash rule broken: 2 program(s)"),
                                         ("stray", "with no flash operation behind it")])
def test_flash_rule_violations_fail_the_baseline(option, text):
    results, _ = campaign(FakeDevice(**{option: True}))
    assert len(results) == 1 and not results[0].passed
    assert text in results[0].message


def test_a_lock_up_is_a_failed_cut_and_the_emulator_is_restarted():
    device = FakeDevice(hang_on_boot=True)
    results, _ = campaign(device, cuts=[Cut(name="a", at_op=2), Cut(name="b", at_op=3)])
    assert not results[1].passed and "locked up" in results[1].message
    assert device.restarts == 1
    assert results[2].passed, "the run carries on after the restart"


def test_an_update_that_differs_between_runs_trips_the_self_check():
    with pytest.raises(runner.SelfCheckFailed, match="check_states: false"):
        campaign(FakeDevice(nondeterministic=True), cuts=[Cut(name="x", at_op=3)])


def test_the_self_check_can_be_turned_off():
    results, _ = campaign(FakeDevice(nondeterministic=True), cuts=[Cut(name="x", at_op=3)],
                          check_states=False)
    assert results[1].fired


def test_baseline_only_runs_no_cuts():
    results, trace = campaign(FakeDevice(), baseline_only=True)
    assert len(results) == 1 and results[0].passed and len(trace) == UPDATE_OPS


def test_a_cut_on_an_erase_page_reports_that_page():
    results, _ = campaign(FakeDevice(), cuts=[Cut(name="e", on_erase=SLOT, expect=(1, SLOT))])
    assert results[1].passed and (results[1].kind, results[1].addr, results[1].op_index) == ("erase", SLOT, 0)


def test_a_cut_landing_somewhere_unexpected_fails():
    results, _ = campaign(FakeDevice(), cuts=[Cut(name="e", at_op=0, expect=(2, 0))])
    assert not results[1].passed and "expected program" in results[1].message


def test_as_dict_needs_every_cut_to_pass():
    good, _ = campaign(FakeDevice())
    bad, _ = campaign(FakeDevice(no_recovery=True))
    ad = SimpleNamespace(name="fake", target="/x/fake")
    assert runner.as_dict(runner.Outcome(good, []), ad)["passed"] is True
    assert runner.as_dict(runner.Outcome(bad, []), ad)["passed"] is False


def test_the_fake_really_installs_the_new_image():
    device = FakeDevice()
    campaign(device, baseline_only=True)
    assert device.read_bytes(SLOT, 16) == NEW_IMAGE


def test_a_stray_write_is_blamed_on_the_firmware_not_on_the_self_check():
    # flash that differs from the replay because of a stray write must fail the
    # baseline (exit 1), not raise SelfCheckFailed (exit 3)
    device = FakeDevice(stray=True)
    device_boot = device._boot

    def boot_and_scribble():
        device_boot()
        device._put(SLOT + 8, 0x1234)

    device._boot = boot_and_scribble
    results, _ = campaign(device)
    assert len(results) == 1 and "no flash operation behind it" in results[0].message
