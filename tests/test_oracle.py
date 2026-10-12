"""The oracle on its own, and inside a campaign against the simulated device."""
from types import SimpleNamespace

import pytest

from brickproof import adapter as adapters
from brickproof import oracle as oracles
from brickproof import runner
from brickproof.adapter import Cut
from brickproof.oracle import Image, Oracle
from fake_device import NEW_IMAGE, OLD_IMAGE, SLOT, FakeDevice, FakeDriver

OLD = Image("old", OLD_IMAGE, SLOT)
NEW = Image("new", NEW_IMAGE, SLOT)


def device_holding(image):
    d = FakeDevice()
    d.mem[SLOT - 0x08000000:SLOT - 0x08000000 + len(image)] = image
    return d


def test_it_names_the_installed_image():
    v = Oracle([OLD, NEW], accept=["old", "new"]).judge(device_holding(NEW_IMAGE))
    assert v.ok and v.image == "new"


def test_an_image_the_scenario_does_not_accept_fails_by_name():
    v = Oracle([OLD, NEW], accept=["new"]).judge(device_holding(OLD_IMAGE))
    assert not v.ok and v.image == "old"
    assert "installed image is old" in v.message and "accepts only new" in v.message


def test_one_wrong_byte_is_no_approved_image():
    torn = bytearray(NEW_IMAGE)
    torn[10] ^= 0xFF
    v = Oracle([OLD, NEW], accept=["new"]).judge(device_holding(bytes(torn)))
    assert not v.ok and v.image is None
    assert "no approved image" in v.message and "0x%08X" % (SLOT + 10) in v.message
    assert "closest is new" in v.message


def test_when_one_image_is_the_start_of_another_the_longer_one_wins():
    # an update that only appends: the old image matches the new one on its own length
    longer = Image("appended", OLD_IMAGE + bytes([0xC3] * 4), SLOT)
    oracle = Oracle([OLD, longer], accept=["old", "appended"])
    assert oracle.judge(device_holding(longer.data)).image == "appended"
    assert oracle.judge(device_holding(OLD_IMAGE + bytes([0xFF] * 4))).image == "old"


def test_the_right_bytes_but_parked_in_a_fault_handler_fails():
    d = device_holding(NEW_IMAGE)
    d.cpu = (SLOT + 8, 3)
    v = Oracle([NEW], accept=["new"]).judge(d)
    assert not v.ok and "HardFault" in v.message and v.image == "new"


def test_the_right_bytes_but_running_somewhere_else_fails():
    d = device_holding(NEW_IMAGE)
    d.cpu = (0x08000010, 0)                 # still in the bootloader
    v = Oracle([NEW], accept=["new"]).judge(d)
    assert not v.ok and "not running" in v.message and "0x08000010" in v.message


def test_run_in_overrides_where_the_pc_may_be():
    d = device_holding(NEW_IMAGE)
    d.cpu = (0x08000010, 0)
    assert Oracle([NEW], accept=["new"], run_in=(0x08000000, 0x08000400)).judge(d).ok


def test_an_interrupt_handler_is_not_a_fault():
    d = device_holding(NEW_IMAGE)
    d.cpu = (SLOT + 6, 15)                  # SysTick
    assert Oracle([NEW], accept=["new"]).judge(d).ok


@pytest.mark.parametrize("accept", [[], ["nope"]])
def test_accept_must_name_known_images(accept):
    with pytest.raises(ValueError, match="accept"):
        Oracle([OLD, NEW], accept=accept)


# ---- inside a campaign --------------------------------------------------------

def campaign(device, oracle, cuts, driver=None):
    ad = SimpleNamespace(flash=device.flash, check_states=True, cut_limit=0.03, update_time=1.0,
                         boot_settle=0.1, cuts=cuts)
    out = runner.campaign(device, driver or FakeDriver(device), ad, oracle=oracle)
    return out.results, out.trace


class TrustingDriver(FakeDriver):
    """A driver whose firmware always claims to be fine."""

    def alive(self):
        self.d.run_for(0.1)
        return True

    def check_recovered(self):
        return True, ""


def test_results_carry_the_image_the_oracle_found():
    results, _ = campaign(FakeDevice(), Oracle([OLD, NEW], accept=["new"]), [Cut(name="c", at_op=3)])
    assert [r.image for r in results] == ["new", "new"] and all(r.passed for r in results)


def test_the_oracle_overrules_a_driver_that_says_everything_is_fine():
    # no recovery after the cut: the slot is left half written, the driver is happy
    device = FakeDevice(no_recovery=True)
    results, _ = campaign(device, Oracle([OLD, NEW], accept=["old", "new"]),
                          [Cut(name="mid-copy", at_op=4)], driver=TrustingDriver(device))
    assert results[0].passed
    assert not results[1].passed and "no approved image" in results[1].message


def test_old_or_new_lets_a_cut_before_the_commit_keep_the_old_image():
    device = FakeDevice(no_recovery=True)
    both = Oracle([OLD, NEW], accept=["old", "new"])
    results, _ = campaign(device, both, [Cut(name="before-erase", at_op=0)],
                          driver=TrustingDriver(device))
    assert results[1].passed and results[1].image == "old"


def test_without_an_oracle_the_same_cut_slips_through():
    # the reason the oracle exists
    device = FakeDevice(no_recovery=True)
    results, _ = campaign(device, None, [Cut(name="mid-copy", at_op=4)], driver=TrustingDriver(device))
    assert results[1].passed and results[1].image is None


# ---- from an adapter ------------------------------------------------------------

YAML = """
name: demo
target: fw
platform: {base: stm32f103}
flash: {base: 0x08000000, size: 0x10000, page: 0x400}
ram: {size: 0x5000}
firmware:
  - file: app.elf
driver: {file: driver.py}
"""


def load(tmp_path, oracle_yaml):
    p = tmp_path / "adapter.yaml"
    p.write_text(YAML + oracle_yaml)
    return adapters.load(str(p))


def test_the_oracle_section_is_optional(tmp_path):
    assert load(tmp_path, "").oracle is None
    assert oracles.build(load(tmp_path, ""), driver=None) is None


def test_images_come_from_files_and_from_the_driver(tmp_path):
    (tmp_path / "fw").mkdir()
    (tmp_path / "fw" / "v1.img").write_bytes(OLD_IMAGE)
    ad = load(tmp_path, "oracle:\n  images:\n    v1: {file: v1.img, at: 0x08000400}\n"
                        "  accept: [v1, signed]\n  run_in: {start: 0x08000000, end: 0x08002000}\n")
    driver = SimpleNamespace(oracle_images=lambda: {"signed": (NEW_IMAGE, SLOT)})
    oracle = oracles.build(ad, driver)
    assert {(i.name, i.data, i.addr) for i in oracle.images} == {("v1", OLD_IMAGE, SLOT),
                                                                 ("signed", NEW_IMAGE, SLOT)}
    assert oracle.accept == ["v1", "signed"] and oracle.run_in == (0x08000000, 0x08002000)


@pytest.mark.parametrize("section,text", [
    ("oracle:\n  images:\n    v1: {at: 0x08000400}\n  accept: [v1]\n", "file"),
    ("oracle:\n  images:\n    v1: {file: a.img, at: 1}\n", "accept"),
    ("oracle:\n  images:\n    v1: {file: a.img, at: 1}\n  accept: []\n", "accept"),
    ("oracle:\n  accept: [v1]\n  run_in: {start: 9, end: 2}\n", "run_in"),
])
def test_a_bad_oracle_section_is_rejected(tmp_path, section, text):
    with pytest.raises(adapters.AdapterError, match=text):
        load(tmp_path, section)


# ---- a bootloader and the program it starts, side by side -----------------------

BOOT_AT = 0x08000000
BOOT_CODE = bytes(range(64))
BOOTLOADER = Image("bootloader", BOOT_CODE, BOOT_AT)
PROGRAM = Image("program", NEW_IMAGE, SLOT)


def device_with_bootloader(program=None, pc=BOOT_AT + 8, exc=0):
    d = FakeDevice()
    d.mem[0:len(BOOT_CODE)] = BOOT_CODE
    d.mem[SLOT - BOOT_AT:SLOT - BOOT_AT + len(NEW_IMAGE)] = program or bytes(len(NEW_IMAGE))
    d.cpu = (pc, exc)
    return d


def side_by_side(accept=("bootloader", "program")):
    return Oracle([BOOTLOADER, PROGRAM], accept=list(accept))


def test_with_only_the_bootloader_installed_the_core_must_be_in_it():
    assert side_by_side().judge(device_with_bootloader()).image == "bootloader"
    v = side_by_side().judge(device_with_bootloader(pc=SLOT + 4))
    assert not v.ok and "bootloader is installed but not running" in v.message


def test_with_both_installed_the_core_may_be_in_either():
    for pc, name in ((BOOT_AT + 8, "bootloader"), (SLOT + 4, "program")):
        v = side_by_side().judge(device_with_bootloader(NEW_IMAGE, pc=pc))
        assert v.ok and v.image == name


def test_with_both_installed_the_core_must_be_in_one_of_them():
    v = side_by_side().judge(device_with_bootloader(NEW_IMAGE, pc=0x20000100))
    assert not v.ok and "neither is running" in v.message
    v = side_by_side().judge(device_with_bootloader(NEW_IMAGE, pc=SLOT + 4, exc=3))
    assert not v.ok and "HardFault" in v.message


def test_running_an_installed_image_the_scenario_does_not_accept_fails():
    v = side_by_side(accept=["program"]).judge(device_with_bootloader(NEW_IMAGE))
    assert not v.ok and v.image == "bootloader" and "accepts only program" in v.message
