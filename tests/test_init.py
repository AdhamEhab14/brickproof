"""brickproof init: the adapter it writes must pass the checks, with nothing typed by hand
but the answers. The emulator is not needed here (probe_device=False); the probe is run on
real firmware by hand and in the e2e job."""
import os
import shutil

import pytest

from brickproof import check as checks
from brickproof import init as inits
from demo_paths import FIRMWARE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCUBOOT_F411 = os.path.join(ROOT, "adapters", "mcuboot", "prebuilt", "f411")
DEMO = os.path.join(FIRMWARE, "prebuilt")


@pytest.fixture
def mcuboot(tmp_path, monkeypatch):
    for name in os.listdir(MCUBOOT_F411):
        shutil.copy(os.path.join(MCUBOOT_F411, name), tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def staged_answers(**over):
    a = dict(chip="stm32f411", kind="staged", firmware="mcuboot.elf", app="app_v1.img",
             app_at="0x08020000", new="app_v2_staged.img", slot="0x08040000")
    a.update(over)
    return a


def test_an_mcuboot_adapter_from_answers_alone(mcuboot):
    said = []
    path = inits.run(staged_answers(), interactive=False, say=said.append, probe_device=False)
    assert os.path.basename(path) == "brickproof.yaml"
    ad, rep = checks.check(path, emulator=False)
    assert rep.passed, rep.lines()
    assert ad.platform == "stm32f411" and ad.flash.sectors and ad.ram_size == 0x20000
    # the padded staged image gives an approved copy the size of the image in it
    assert os.path.getsize(mcuboot / "approved_new.bin") == 0x43D7
    assert ad.oracle["accept"] == ["new"] and ad.content_faults["keep"] == "old"
    assert ad.plan["real_every"] == "auto"
    assert any("Next: brickproof run brickproof.yaml --full" in s for s in said)


def test_questions_are_asked_and_bad_answers_asked_again(mcuboot):
    replies = iter(["9", "2",                       # a chip that is not on the list, then F411
                    "1",                            # staged
                    "nope.elf", "mcuboot.elf",      # a file that is not there, then the right one
                    "",                             # the default adapter name
                    "app_v1.img", "somewhere", "0x08020000",
                    "app_v2_staged.img", "0x08040000"])
    said = []
    path = inits.run({}, interactive=True, ask=lambda _q: next(replies), say=said.append,
                     probe_device=False)
    assert checks.check(path, emulator=False)[1].passed
    assert any("from 1 to 5" in s for s in said)
    assert any("no file at nope.elf" in s for s in said)
    assert any("an address" in s for s in said)


def test_without_a_terminal_a_missing_answer_says_which_flag(mcuboot):
    with pytest.raises(ValueError, match="--slot"):
        inits.run(staged_answers(slot=None), interactive=False, say=lambda _s: None,
                  probe_device=False)


def test_a_storage_workload_gets_its_program_as_the_approved_image(tmp_path, monkeypatch):
    shutil.copy(os.path.join(DEMO, "bootloader.elf"), tmp_path / "workload.elf")
    monkeypatch.chdir(tmp_path)
    path = inits.run(dict(chip="stm32f103", kind="storage", firmware="workload.elf"),
                     interactive=False, say=lambda _s: None, probe_device=False)
    ad, rep = checks.check(path, emulator=False)
    assert rep.passed, rep.lines()
    assert ad.driver_builtin == "storage" and ad.oracle["images"]["app"][1] == 0x08000000


def test_a_protocol_update_gets_a_driver_to_fill_in(tmp_path, monkeypatch):
    shutil.copy(os.path.join(DEMO, "bootloader.elf"), tmp_path / "boot.elf")
    monkeypatch.chdir(tmp_path)
    path = inits.run(dict(chip="stm32f103", kind="protocol", firmware="boot.elf"),
                     interactive=False, say=lambda _s: None, probe_device=False)
    assert checks.check(path, emulator=False)[1].passed
    assert "TODO" in (tmp_path / "driver.py").read_text()


def test_banners_become_patterns():
    assert inits.generalise("APP v1") == "APP v[0-9]+"
    assert inits.generalise("fw 2.10.3 up (ok)") == "fw [0-9]+\\.[0-9]+\\.[0-9]+ up \\(ok\\)"
    assert inits.literal("a.b*c") == "a\\.b\\*c"
    import re
    for banner in ("APP v2", "fw 2.10.3 up (ok)", "x[1]+y?"):
        assert re.fullmatch(inits.literal(banner), banner)
        assert re.fullmatch(inits.generalise(banner), banner)
    assert inits.last_line("BL\r\nAPP v1\r\n\r\n") == "APP v1"


def test_without_renode_the_next_step_is_setup(mcuboot, monkeypatch):
    from brickproof import runner
    monkeypatch.setattr(runner, "find_renode", lambda: None)
    said = []
    inits.run(staged_answers(), interactive=False, say=said.append, probe_device=False)
    nxt = [s for s in said if s.startswith("Next:")]
    assert len(nxt) == 2 and "brickproof setup" in nxt[0] and "--full" in nxt[1]
