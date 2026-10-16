"""Soak runs: random cuts and torn states until a deadline or the first failure."""
from types import SimpleNamespace

from brickproof import runner
from fake_device import FakeDevice, FakeDriver


def soak(device, seconds, seed=0):
    ad = SimpleNamespace(name="fake", flash=device.flash, check_states=True, cut_limit=0.03,
                         update_time=1.0, boot_settle=0.1, cuts=[], plan={"mode": "every"},
                         torn=None, torn_seed=0, depth=None, oracle=None, soak=(seconds, seed))
    return runner.campaign(device, FakeDriver(device), ad)


def test_a_soak_stops_at_the_first_failure():
    out = soak(FakeDevice(no_recovery=True), seconds=60)
    tests = out.results[1:]
    assert tests and not tests[-1].passed and all(r.passed for r in tests[:-1])
    assert all(r.cut.startswith("soak op-") for r in tests)


def test_a_soak_of_a_sound_updater_runs_until_the_deadline():
    out = soak(FakeDevice(), seconds=0.3)
    tests = out.results[1:]
    assert len(tests) > 1 and all(r.passed for r in tests)
    assert any(r.torn for r in tests) and any(not r.torn for r in tests)


def test_the_same_seed_draws_the_same_tests():
    a = [r.cut for r in soak(FakeDevice(no_recovery=True), 60, seed=5).results]
    b = [r.cut for r in soak(FakeDevice(no_recovery=True), 60, seed=5).results]
    assert a == b
