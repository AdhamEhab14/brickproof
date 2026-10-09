"""End to end on the real Three-Tier bootloader: real power cuts in Renode, real recovery.

Needs Renode and a build-test build of the bootloader. Point BRICKPROOF_THREE_TIER at
the bootloader repo (default: the adapter's 'target', next to this repo).

    python -m pytest -m renode
"""
import os

import pytest

from brickproof import adapter as adapters
from brickproof import runner
from brickproof.engine.session import find_renode

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTER = os.path.join(REPO, "adapters", "three_tier_f103", "adapter.yaml")

pytestmark = pytest.mark.renode


@pytest.fixture(scope="module")
def results():
    ad = adapters.load(ADAPTER, target=os.environ.get("BRICKPROOF_THREE_TIER"))
    if not find_renode():
        pytest.skip("Renode not found (set RENODE_PATH)")
    if not os.path.exists(os.path.join(ad.target, "build-test", "fbl.elf")):
        pytest.skip("bootloader not built in %s/build-test" % ad.target)
    res, _ = runner.run(ad)
    return {r.cut: r for r in res}


def test_first_sbl_erase_is_op_7(results):
    r = results["first-sbl-erase"]
    assert r.fired and r.op_index == 7, r


def test_every_cut_fires_where_expected(results):
    for r in results.values():
        assert r.fired and "expected" not in r.message, r


def test_device_recovers_from_every_cut(results):
    failed = [r for r in results.values() if not r.passed]
    assert not failed, failed
