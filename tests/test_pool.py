"""Several emulators sharing the work must give exactly what one gives, in the same order."""
import threading
import time
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from brickproof import runner
from brickproof import torn
from brickproof.adapter import Cut
from brickproof.pool import Pool
from fake_device import FakeDevice, FakeDriver

DEPTH = {"levels": 2, "mode": "every", "per_phase": 2, "small": 6, "max_states": 2000, "torn": False}


def workers(n):
    return [(object(), object()) for _ in range(n)]


def test_results_come_back_in_item_order_whatever_finishes_first():
    def slow_first(session, driver, item):
        time.sleep(0.05 if item == 0 else 0)
        return item * 10

    seen = []
    out = Pool(workers(4)).run(slow_first, range(8), on_result=seen.append)
    assert out == seen == [0, 10, 20, 30, 40, 50, 60, 70]


def test_every_worker_takes_part():
    used = set()
    barrier = threading.Barrier(3, timeout=5)

    def fn(session, driver, item):
        used.add(id(session))
        barrier.wait()                  # only passes if three run at the same time
        return item

    pool = Pool(workers(3))
    assert pool.run(fn, range(3)) == [0, 1, 2] and len(used) == 3


def test_a_result_can_be_a_list_and_is_flattened_in_order():
    out = Pool(workers(3)).run(lambda s, d, i: [i, i + 0.5], range(3))
    assert out == [0, 0.5, 1, 1.5, 2, 2.5]


@pytest.mark.parametrize("n", [1, 4])
def test_stop_keeps_nothing_after_the_first_stopping_result(n):
    reported = []
    out = Pool(workers(n)).run(lambda s, d, i: i, range(50), on_result=reported.append,
                               stop=lambda r: r == 7)
    assert out == reported == list(range(8))


def test_stop_inside_a_list_drops_the_rest_of_that_list():
    out = Pool(workers(2)).run(lambda s, d, i: [i, i + 100], range(5), stop=lambda r: r == 101)
    assert out == [0, 100, 1, 101]


@pytest.mark.parametrize("n", [1, 3])
def test_an_error_in_a_worker_is_raised_to_the_caller(n):
    def fn(session, driver, item):
        if item == 4:
            raise RuntimeError("boom")
        return item

    with pytest.raises(RuntimeError, match="boom"):
        Pool(workers(n)).run(fn, range(20))


def test_nothing_to_do_is_fine():
    assert Pool(workers(3)).run(lambda s, d, i: i, []) == []


# ---- a whole campaign, one emulator against several ----------------------------

def campaign(jobs, device_options, fail_fast=False, **adapter):
    devices = [FakeDevice(**device_options) for _ in range(jobs)]
    ad = SimpleNamespace(flash=devices[0].flash, check_states=True, cut_limit=0.03, update_time=1.0,
                         boot_settle=0.1, cuts=[], plan={"mode": "every"}, torn=None, torn_seed=0,
                         depth=None)
    for k, v in adapter.items():
        setattr(ad, k, v)
    extra = [(d, FakeDriver(d)) for d in devices[1:]]
    return runner.campaign(devices[0], FakeDriver(devices[0]), ad, workers=extra, fail_fast=fail_fast)


def plain(out):
    rows = []
    for r in out.results:
        d = asdict(r)
        d.pop("seconds")
        rows.append(d)
    return rows


CASES = [
    ("clean", {}, {}),
    ("torn", {}, {"torn": list(torn.KINDS)}),
    ("failing", {"no_recovery": True}, {"torn": list(torn.KINDS)}),
    ("depth", {"retry_limit": True}, {"depth": DEPTH}),
    ("depth+torn", {"retry_limit": True}, {"depth": dict(DEPTH, torn=True), "torn": list(torn.KINDS)}),
    ("listed", {}, {"cuts": [Cut(name="mine", at_op=3), Cut(name="far", at_op=99, group=5)]}),
]


@pytest.mark.parametrize("name,device,adapter", CASES, ids=[c[0] for c in CASES])
def test_four_emulators_give_exactly_what_one_gives(name, device, adapter):
    one = campaign(1, device, **adapter)
    four = campaign(4, device, **adapter)
    assert plain(four) == plain(one)
    assert four.depth == one.depth and four.jobs == 4 and one.jobs == 1
    assert len(one.results) > 1


@pytest.mark.parametrize("device,adapter", [({"no_recovery": True}, {}),
                                            ({"retry_limit": True}, {"depth": DEPTH})])
def test_fail_fast_stops_at_the_same_place_with_any_number_of_emulators(device, adapter):
    one = campaign(1, device, fail_fast=True, **adapter)
    four = campaign(4, device, fail_fast=True, **adapter)
    assert plain(four) == plain(one)
    assert not one.results[-1].passed and sum(not r.passed for r in one.results) == 1


def test_torn_states_are_explored_at_depth_when_asked():
    out = campaign(1, {"retry_limit": True}, depth=dict(DEPTH, torn=True), torn=list(torn.KINDS))
    deep_torn = [r for r in out.results if r.depth > 1 and r.torn]
    assert deep_torn and all(" > " in r.cut and r.cut.split()[-1] == r.torn for r in deep_torn)
    without = campaign(1, {"retry_limit": True}, depth=DEPTH, torn=list(torn.KINDS))
    assert not [r for r in without.results if r.depth > 1 and r.torn]


def test_a_self_check_failure_in_any_emulator_stops_the_run():
    with pytest.raises(runner.SelfCheckFailed):
        campaign(3, {"nondeterministic": True}, cuts=[Cut(name="x%d" % i, at_op=3) for i in range(6)],
                 plan=None)
