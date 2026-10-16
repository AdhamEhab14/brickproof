"""The storage driver's judgement: which values a store may hold after a cut."""
from types import SimpleNamespace

from brickproof import runner
from brickproof.drivers.storage import (Step, allowed_values, check_dump, parse_dump,
                                        parse_step)
from fake_device import FakeDevice, FakeDriver

# three steps: write key 1 gen 1 (ops 0-10), write key 2 gen 2 (10-20), delete key 1 (20-25)
STEPS = [Step(0, 10, 1, 1), Step(10, 20, 2, 2), Step(20, 25, 1, None)]


def test_lines_are_read_as_the_firmware_prints_them():
    assert parse_step("C 4 W 3 5") == (3, 5)
    assert parse_step("C 8 D 2\r") == (2, None)
    assert parse_step("E 4 -5") is None
    text = "STORE nvs\r\nMOUNT ok\r\nR 1 7\r\nR 2 -\r\nR 3 bad\r\nR 4 err -5\r\nREADY\r\n"
    assert parse_dump(text) == {1: 7, 2: None, 3: "bad", 4: "err -5"}


def test_a_finished_step_must_be_there_and_one_under_way_may_be():
    assert allowed_values(STEPS, 2, 0) == {1: {None, 1}, 2: {None}}
    assert allowed_values(STEPS, 2, 10) == {1: {1}, 2: {None, 2}}     # step 0 ended at 10
    assert allowed_values(STEPS, 2, 22) == {1: {1, None}, 2: {2}}     # the delete under way
    assert allowed_values(STEPS, 2, float("inf")) == {1: {None}, 2: {2}}


def test_what_a_correct_store_may_hold_passes():
    allowed = allowed_values(STEPS, 2, 15)
    assert check_dump({1: 1, 2: None, 3: None}, allowed, 3) == ""
    assert check_dump({1: 1, 2: 2, 3: None}, allowed, 3) == ""


def test_lost_old_mangled_or_unreadable_values_fail():
    allowed = allowed_values(STEPS, 2, 15)
    assert "key 1 holds nothing" in check_dump({1: None, 2: None, 3: None}, allowed, 3)
    assert "half-written" in check_dump({1: "bad", 2: None, 3: None}, allowed, 3)
    assert "reading it fails" in check_dump({1: 1, 2: "err -5", 3: None}, allowed, 3)
    assert "did not report" in check_dump({1: 1, 3: None}, allowed, 3)
    late = allowed_values(STEPS, 2, float("inf"))
    assert "key 1 holds generation 1" in check_dump({1: 1, 2: 2, 3: None}, late, 3)  # delete lost
    assert "probe key" in check_dump({1: None, 2: 2, 3: 9999}, late, 3)


class JudgedDriver(FakeDriver):
    def __init__(self, device):
        super().__init__(device)
        self.seen = []

    def judging(self, update_op):
        self.seen.append(update_op)


def test_the_runner_says_which_operation_each_result_was_cut_at():
    device = FakeDevice()
    driver = JudgedDriver(device)
    ad = SimpleNamespace(name="fake", flash=device.flash, check_states=True, cut_limit=0.03,
                         update_time=1.0, boot_settle=0.1, cuts=[], plan={"mode": "every"},
                         torn=None, torn_seed=0, depth=None, oracle=None)
    out = runner.campaign(device, driver, ad)
    assert driver.seen[0] is None                       # the baseline: the update finished
    assert driver.seen[1:] == [r.op_index for r in out.results[1:]]
