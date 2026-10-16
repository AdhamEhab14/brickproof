"""brickproof export: the flash a cut leaves, as files for a real board."""
from types import SimpleNamespace

import pytest

from brickproof import export
from brickproof import runner
from brickproof import torn
from brickproof import trace as traces
from brickproof.engine.session import FlashGeometry
from fake_device import FakeDevice, FakeDriver

BASE = 0x08000000
PAGE = 0x400
FLASH = FlashGeometry(base=BASE, size=4 * PAGE, page=PAGE)

OPS = [
    {"index": 0, "kind": "erase", "addr": BASE + PAGE},
    {"index": 1, "kind": "program", "addr": BASE + PAGE, "value": 0x1234},
    {"index": 2, "kind": "program", "addr": BASE + PAGE + 2, "value": 0x5678},
]


def pre():
    return bytes([0xFF]) * PAGE + bytes([0x00]) * PAGE + bytes([0xFF]) * (2 * PAGE)


def adapter(platform="stm32f103", flash=FLASH):
    return SimpleNamespace(name="demo", path="adapters/demo.yaml", platform=platform,
                           flash=flash, torn_seed=0)


def test_a_clean_state_is_the_golden_run_replayed_to_that_operation():
    for n in range(len(OPS) + 1):
        assert export.state_image(pre(), OPS, FLASH, n) == bytes(traces.Replay(pre(), OPS, FLASH).at(n))
    # before the erase the old page is there; before the second program, only the first landed
    assert export.state_image(pre(), OPS, FLASH, 0)[PAGE:PAGE + 4] == b"\x00\x00\x00\x00"
    assert export.state_image(pre(), OPS, FLASH, 2)[PAGE:PAGE + 4] == b"\x34\x12\xFF\xFF"


def test_a_torn_state_is_the_one_a_run_powers_up_from():
    before = export.state_image(pre(), OPS, FLASH, 0)
    want = {s.kind: s.image for s in torn.states(OPS[0], before, FLASH, torn.KINDS, 0)}
    for kind, image in want.items():
        assert export.state_image(pre(), OPS, FLASH, 0, kind) == image


def test_a_state_that_does_not_exist_is_refused():
    with pytest.raises(ValueError, match="0 to 3"):
        export.state_image(pre(), OPS, FLASH, 4)
    with pytest.raises(ValueError, match="no program-low state"):
        export.state_image(pre(), OPS, FLASH, 0, "program-low")      # an erase is not a program
    with pytest.raises(ValueError, match="no operation 3"):
        export.state_image(pre(), OPS, FLASH, 3, "erase-early")


def test_option_bytes_and_an_external_chip_get_files_of_their_own(tmp_path):
    flash = FlashGeometry(base=BASE, size=4 * PAGE, page=PAGE, ob_base=0x1FFFF800,
                          option_bytes=bytes(16), ext_base=0x90000000, ext_size=0x2000)
    image = bytes([1]) * flash.size + bytes([2]) * 16 + bytes([3]) * 0x2000 + bytes([4]) * 2
    split = {name: (addr, data) for name, addr, data in export.parts(image, flash)}
    assert split["flash"] == (BASE, bytes([1]) * flash.size)
    assert split["option bytes"] == (0x1FFFF800, bytes([2]) * 16)
    assert split["external flash"] == (0, bytes([3]) * 0x2000)
    assert split["external status registers"] == (None, bytes([4]) * 2)


def test_write_leaves_the_image_and_how_to_program_it(tmp_path):
    out = str(tmp_path / "op-2.bin")
    files = export.write(adapter(), pre(), OPS, out, 2)
    with open(files["flash"], "rb") as f:
        assert f.read() == export.state_image(pre(), OPS, FLASH, 2)
    with open(files["readme"], encoding="utf-8") as f:
        text = f.read()
    assert "brickproof export adapters/demo.yaml --cut 2" in text
    assert "ST-LINK_CLI -c SWD -ME -P op-2.bin 0x08000000 -V -Rst" in text
    assert "STM32_Programmer_CLI" in text


def test_an_nrf52_state_comes_with_nrfjprog_commands(tmp_path):
    flash = FlashGeometry(base=0, size=4 * PAGE, page=PAGE)
    ops = [dict(op, addr=op["addr"] - BASE) for op in OPS]
    files = export.write(adapter("nrf52840", flash), pre(), ops, str(tmp_path / "s.bin"), 1)
    with open(files["readme"], encoding="utf-8") as f:
        text = f.read()
    assert "nrfjprog --program s.hex --chiperase --verify --reset" in text
    assert "--change-addresses 0x0 s.bin s.hex" in text


def test_a_campaign_keeps_the_flash_it_started_from():
    device = FakeDevice()
    ad = SimpleNamespace(name="fake", flash=device.flash, check_states=True, cut_limit=0.03,
                         update_time=1.0, boot_settle=0.1, cuts=[], plan={"mode": "every"},
                         torn=None, torn_seed=0, depth=None, oracle=None)
    out = runner.campaign(device, FakeDriver(device), ad, baseline_only=True)
    assert out.pre is not None and len(out.pre) == device.flash.image_size
    assert export.state_image(out.pre, out.trace, device.flash, 0) == out.pre
