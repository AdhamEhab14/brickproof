"""brickproof check: each mistake below is one that was really made, and must be caught
before an emulator starts, with a fix a first-time user can follow."""
import os

import pytest

from brickproof import check as checks
from brickproof import content as contents
from brickproof import images
from brickproof.engine.session import find_renode
from demo_paths import FIRMWARE, all_demo_adapters, demo_adapter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCUBOOT = os.path.join(ROOT, "adapters", "mcuboot")


def adapter_text(source, target, **replace):
    """An adapter's text with its target made absolute, and lines swapped as asked."""
    text = open(source).read()
    for old, new in replace.items():
        assert old in text, old
        text = text.replace(old, new)
    lines = [("target: %s" % target.replace("\\", "/")) if line.startswith("target:") else line
             for line in text.splitlines()]
    return "\n".join(lines) + "\n"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return str(path)


def failures(rep):
    return [f for f in rep.findings if not f.ok]


def run(path):
    return checks.check(str(path), emulator=False)


def test_the_bundled_demo_passes():
    ad, rep = run(demo_adapter("adapter"))
    assert ad is not None and rep.passed, rep.lines()


def test_an_adapter_saved_in_the_wrong_folder_is_found_and_named(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / ".github" / "workflows" / "f411-overwrite.yaml", "name: x\n")
    ad, rep = run("adapters/mcuboot/f411-overwrite.yaml")
    assert ad is None
    (f,) = failures(rep)
    assert "no adapter at" in f.what
    assert os.path.join(".github", "workflows", "f411-overwrite.yaml") in f.fix
    assert "GitHub would take it for a workflow" in f.fix


def test_extends_a_file_that_is_not_next_to_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "adapters" / "mcuboot" / "f411.yaml", "name: base\n")
    path = write(tmp_path / "elsewhere" / "child.yaml", "extends: f411.yaml\nname: child\n")
    ad, rep = run(path)
    assert ad is None
    (f,) = failures(rep)
    assert "extends f411.yaml, which is not in its folder" in f.what
    assert os.path.join("adapters", "mcuboot", "f411.yaml") in f.fix


def test_broken_yaml_says_where(tmp_path):
    path = write(tmp_path / "a.yaml", "name: x\nflash:\n  base: 1\n size: 2\n")
    _, rep = run(path)
    (f,) = failures(rep)
    assert "not valid YAML" in f.what and "line" in f.what and "indentation" in f.fix


def test_ram_smaller_than_the_firmware_expects(tmp_path):
    path = write(tmp_path / "a.yaml", adapter_text(
        demo_adapter("adapter"), FIRMWARE,
        **{"  size: 0x5000 ": "  size: 0x4000 "}))
    _, rep = run(path)
    (f,) = failures(rep)
    assert "starts its stack at 0x20005000, outside the 16 KB of RAM" in f.what
    assert "ram.size" in f.fix


def test_firmware_that_is_not_built_yet(tmp_path):
    path = write(tmp_path / "a.yaml", adapter_text(
        demo_adapter("adapter"), str(tmp_path / "nowhere")))
    _, rep = run(path)
    assert any("firmware not found" in f.what and "--target" in f.fix for f in failures(rep))


def test_a_stale_image_size_inherited_from_another_build(tmp_path):
    # f411.yaml's image is 0x43D7 bytes; an adapter claiming 0x43AF (another build's) is wrong
    path = write(tmp_path / "a.yaml", adapter_text(
        os.path.join(MCUBOOT, "f411.yaml"), os.path.join(MCUBOOT, "prebuilt", "f411"),
        **{"content_faults: {keep: v1}": "content_faults: {keep: v1, image_size: 0x43AF}"}))
    _, rep = run(path)
    stale = [f for f in failures(rep) if "content_faults.image_size is 0x43AF" in f.what]
    assert stale and "0x43D7 bytes" in stale[0].what and "Remove image_size" in stale[0].fix


def test_the_image_layout_is_read_from_an_mcuboot_image():
    staged = open(os.path.join(MCUBOOT, "prebuilt", "f411", "app_v2_staged.img"), "rb").read()
    found = images.mcuboot_layout(staged)
    # what f411.yaml says by hand
    assert (found.size, found.header, found.body, found.tlv) == (
        0x43D7, (0, 0x20), (0x200, 0x4340), (0x4340, 0x43D7))
    size, regions = contents.layout(staged, {})
    assert size == 0x43D7 and regions == {"header": (0, 0x20), "body": (0x200, 0x4340),
                                          "tlv": (0x4340, 0x43D7)}
    # what the adapter gives still wins
    assert contents.layout(staged, {"image_size": 0x100})[0] == 0x100
    assert images.mcuboot_layout(b"\x00" * 64) is None


def test_elf_segments_are_read_at_their_load_addresses():
    data = open(os.path.join(FIRMWARE, "prebuilt", "bootloader.elf"), "rb").read()
    segs = images.elf_segments(data)
    assert segs and min(s.addr for s in segs) == 0x08000000
    sp, reset = images.first_words(segs, 0x08000000)
    assert sp == 0x20005000 and 0x08000000 < reset < 0x08002000


@pytest.mark.skipif(not find_renode(), reason="needs Renode to read the platform's UARTs")
def test_a_uart_the_chip_does_not_have(tmp_path):
    path = write(tmp_path / "a.yaml", adapter_text(
        demo_adapter("adapter"), FIRMWARE, **{"uart: usart2": "uart: usart9"}))
    _, rep = checks.check(path)
    (f,) = failures(rep)
    assert "no 'usart9'" in f.what and "usart2" in f.fix


ALL_ADAPTERS = sorted(
    all_demo_adapters()
    + [os.path.join(ROOT, "adapters", d, f) for d in os.listdir(os.path.join(ROOT, "adapters"))
       if os.path.isdir(os.path.join(ROOT, "adapters", d))
       for f in os.listdir(os.path.join(ROOT, "adapters", d)) if f.endswith(".yaml")])


@pytest.mark.parametrize("path", ALL_ADAPTERS, ids=lambda p: os.path.relpath(p, ROOT))
def test_every_adapter_in_the_repository_passes(path):
    # firmware that is built elsewhere (OpenBLT, Three-Tier, wolfBoot) may be missing here:
    # that is the only failure allowed
    _, rep = checks.check(path, emulator=False)
    wrong = [f.what for f in failures(rep) if "not found" not in f.what]
    assert not wrong, wrong


def test_a_report_name_from_the_adapter_stays_a_file_name():
    from brickproof.cli import _safe_stem
    assert _safe_stem("mcuboot_f411") == "mcuboot_f411"
    for evil in ("../../etc/x", r"..\..\x", r"C:\Windows\x", "/abs/x", "..", ""):
        stem = _safe_stem(evil)
        assert stem and "/" not in stem and "\\" not in stem and ":" not in stem
        assert not stem.startswith(".")
