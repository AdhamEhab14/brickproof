"""The adapter's keys, in adapter_keys.SCHEMA: every adapter uses only those, a typo is named
with the key it was meant to be, and the adapter reference documents every one."""
import glob
import os
import re

from brickproof import adapter as adapters
from brickproof import adapter_keys as keys
from brickproof import check as checks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTERS = sorted(glob.glob(os.path.join(ROOT, "examples", "demo_ab_bootloader", "*", "*.yaml"))
                  + glob.glob(os.path.join(ROOT, "adapters", "*", "*.yaml")))


def test_every_adapter_here_uses_only_known_keys():
    assert len(ADAPTERS) > 80
    for path in ADAPTERS:
        assert keys.unknown(adapters._read(path)) == [], path


def test_a_typo_is_named_with_the_key_it_was_meant_to_be():
    found = keys.unknown({"boot_setle": 1, "flash": {"write_units": 2, "base": 0},
                          "scenario": {"cuts": [{"at_opp": 3}]}})
    assert ("boot_setle", "boot_setle", "boot_settle") in found
    assert ("flash.write_units", "write_units", "write_unit") in found
    assert ("scenario.cuts[0].at_opp", "at_opp", "at_op") in found


def test_a_key_with_nothing_near_it_has_no_suggestion():
    assert keys.unknown({"colour": "blue"}) == [("colour", "colour", None)]


def test_the_users_own_names_and_short_forms_are_fine():
    assert keys.unknown({
        "pins": {"PC13": "high"}, "driver": {"builtin": "staged_slot", "options": {"anything": 1}},
        "oracle": {"images": {"v9": {"file": "a", "at": 0}}, "accept": ["v9"]},
        "scenario": {"plan": "phases", "torn": True, "link_cuts": True, "depth": 2},
    }) == []


def test_check_refuses_an_adapter_with_a_typo(tmp_path):
    demo = os.path.join(ROOT, "examples", "demo_ab_bootloader", "f103", "adapter.yaml")
    text = open(demo, encoding="utf-8").read().replace("boot_settle:", "boot_setle:")
    firmware = os.path.join(os.path.dirname(demo), "..", "firmware")
    text = text.replace("target: ../firmware", "target: %s" % firmware)
    path = tmp_path / "a.yaml"
    path.write_text(text)
    ad, rep = checks.check(str(path), emulator=False)
    assert not rep.passed
    assert any("boot_setle" in f.what and "boot_settle" in f.fix for f in rep.findings if not f.ok)
    assert ad.unknown_keys == [("boot_setle", "boot_setle", "boot_settle")]


def test_the_adapter_reference_documents_every_key():
    with open(os.path.join(ROOT, "docs", "reference", "adapter.md"), encoding="utf-8") as f:
        doc = f.read()
    missing = [p for p in keys.paths()
               if not re.search(r"(\b|`)%s(\b|:|`)" % re.escape(p.replace("[]", "").split(".")[-1]), doc)]
    assert missing == []
