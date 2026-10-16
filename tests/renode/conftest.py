"""Tests of the flash models' chip rules, run in Renode. Skipped where Renode is not
installed (set RENODE_PATH, or put renode on PATH)."""
import os
import tempfile

import pytest

from brickproof import adapter as adapters
from brickproof.engine import workdir as wd
from brickproof.engine.session import RenodeSession, find_renode

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEMO = os.path.join(ROOT, "examples", "demo_ab_bootloader")


def pytest_collection_modifyitems(config, items):
    if find_renode():
        return
    skip = pytest.mark.skip(reason="Renode not found: set RENODE_PATH")
    for item in items:
        if "tests" + os.sep + "renode" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="module")
def chip(request):
    """A booted emulator for the demo adapter the test module names in ADAPTER, changed
    by the module's ADJUST(adapter) if it has one."""
    ad = adapters.load(os.path.join(DEMO, request.module.ADAPTER))
    adjust = getattr(request.module, "ADJUST", None)
    if adjust:
        adjust(ad)
    work = tempfile.mkdtemp(prefix="bp-rules-")
    s = RenodeSession(find_renode(), work, ad.flash, wd.prepare(work, ad), uart=ad.uart,
                      vector_table=ad.vector_table, mips=ad.mips, reset_cmds=ad.reset_cmds,
                      log=os.environ.get("BP_RENODE_LOG"), ram=wd.MEMORIES[ad.platform]["ram"][0],
                      memory_sizes=wd.memory_sizes(ad))
    s.adapter = ad
    s.factory = bytes(s.dump_flash())
    yield s
    s.close()
