"""Bad update content: damaged images the bootloader must refuse."""
from types import SimpleNamespace

import pytest

from brickproof import adapter as adapters
from brickproof import content, runner
from brickproof.oracle import Image, Oracle
from fake_device import NEW_IMAGE, OLD_IMAGE, SLOT, STAGED, FakeDevice, FakeDriver


def test_each_mutation_damages_only_the_image_and_keeps_the_rest():
    staged = bytes(range(32)) + b"TRAILER!"
    cfg = {"image_size": 32, "regions": {"header": (0, 8), "body": (8, 32)}}
    out = dict(content.mutations(staged, cfg))
    assert set(out) == {"truncate-8", "truncate-16", "truncate-24", "truncate-28",
                        "flip-header@0x4", "flip-body@0x14", "erased"}
    for data in out.values():
        assert len(data) == len(staged) and data.endswith(b"TRAILER!") and data != staged
    assert out["truncate-16"][:32] == bytes(range(16)) + b"\xFF" * 16
    assert out["flip-header@0x4"][4] == 4 ^ 1 and out["erased"][:32] == b"\xFF" * 32


def test_images_made_elsewhere_are_staged_as_they_are():
    staged = bytes(16) + b"TRAIL"
    out = dict(content.mutations(staged, {"image_size": 16, "mutations": []},
                                 {"older": b"\x01" * 8, "huge": b"\x02" * 64}))
    assert out["older"] == b"\x01" * 8 + b"\xFF" * 8 + b"TRAIL"   # in the image's place
    assert out["huge"] == b"\x02" * 64                               # bigger: whole


class StagingDriver(FakeDriver):
    def staged(self):
        return STAGED, NEW_IMAGE


def campaign(device):
    ad = SimpleNamespace(name="fake", flash=device.flash, check_states=True, cut_limit=0.03,
                         update_time=1.0, boot_settle=0.1, cuts=[], plan={"mode": "every"},
                         torn=None, torn_seed=0, depth=None, oracle={"accept": ["new"]},
                         content_faults={"keep": "old", "image_size": None, "mutations": ["flip", "erased"],
                                         "regions": {}, "images": {}})
    judge = Oracle([Image("old", OLD_IMAGE, SLOT), Image("new", NEW_IMAGE, SLOT)], ["new"])
    return runner.campaign(device, StagingDriver(device), ad, oracle=judge)


def test_a_bootloader_that_checks_keeps_the_old_image():
    out = campaign(FakeDevice(verify=True))
    bad = [r for r in out.results if r.content]
    assert [r.content for r in bad] == ["flip-image@0x8", "erased"]
    assert all(r.passed and r.image == "old" for r in bad), [r.message for r in bad]


def test_a_bootloader_that_does_not_check_is_caught():
    out = campaign(FakeDevice())
    bad = [r for r in out.results if r.content]
    assert bad and not any(r.passed for r in bad)
    assert all("did not refuse" in r.message for r in bad)


def test_content_faults_need_an_oracle_and_a_known_image(tmp_path):
    base = {"name": "x", "platform": {"base": "stm32f103"},
            "flash": {"base": 0x08000000, "size": 0x20000, "page": 0x400},
            "ram": {"size": 0x5000}, "firmware": [{"file": "a.elf"}],
            "driver": {"builtin": "staged_slot"}}
    import yaml

    def load(extra):
        p = tmp_path / "a.yaml"
        p.write_text(yaml.safe_dump(dict(base, **extra)))
        return adapters.load(str(p), target=str(tmp_path))

    with pytest.raises(adapters.AdapterError, match="needs an oracle"):
        load({"scenario": {"content_faults": {"keep": "v1"}}})
    oracle = {"images": {"v1": {"file": "v1.img", "at": 0}}, "accept": ["v1"]}
    with pytest.raises(adapters.AdapterError, match="not one of the oracle"):
        load({"oracle": oracle, "scenario": {"content_faults": {"keep": "v9"}}})
    with pytest.raises(adapters.AdapterError, match="mutations"):
        load({"oracle": oracle, "scenario": {"content_faults": {"keep": "v1", "mutations": ["melt"]}}})
    ad = load({"oracle": oracle, "scenario": {"content_faults": {
        "keep": "v1", "regions": {"header": [0, 32]}, "images": {"older": "old.img"}}}})
    assert ad.content_faults["regions"] == {"header": (0, 32)}
    assert ad.content_faults["images"]["older"].endswith("old.img")
