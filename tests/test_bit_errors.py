"""Bit errors at rest: bits flipped in a stored image while the device is off."""
from types import SimpleNamespace

from brickproof import bit_errors, runner
from brickproof.oracle import Image, Oracle
from fake_device import BASE, NEW_IMAGE, OLD_IMAGE, SLOT, FakeDevice, FakeDriver


def test_flips_land_inside_the_region_and_repeat_with_the_seed():
    image = bytes(64)
    a = bit_errors.cases(image, 0x1000, {"img": (0x1010, 0x1020)}, flips=2, runs=3, seed=7)
    b = bit_errors.cases(image, 0x1000, {"img": (0x1010, 0x1020)}, flips=2, runs=3, seed=7)
    assert [c[0] for c in a] == [c[0] for c in b] and len(a) == 3
    for _name, img, region in a:
        changed = [i for i in range(64) if img[i] != image[i]]
        assert changed and all(0x10 <= i < 0x20 for i in changed) and region == (0x1010, 0x1020)
        assert sum(bin(x).count("1") for x in img) <= 2           # one bit per flip


def campaign(device):
    ad = SimpleNamespace(name="fake", flash=device.flash, check_states=True, cut_limit=0.03,
                         update_time=0.1, boot_settle=0.1, cuts=[], plan={"mode": "every"},
                         torn=None, torn_seed=0, depth=None, oracle={"accept": ["new"]},
                         bit_errors={"regions": None, "flips": 1, "runs": 2, "seed": 0})
    judge = Oracle([Image("old", OLD_IMAGE, SLOT), Image("new", NEW_IMAGE, SLOT)], ["new"])
    return runner.campaign(device, FakeDriver(device), ad, oracle=judge)


def test_running_the_damaged_image_fails():
    out = campaign(FakeDevice())                    # the fake runs its slot, checked or not
    flipped = [r for r in out.results if r.bit_error]
    assert len(flipped) == 2 and all(r.bit_error.startswith("new 0x") for r in flipped)
    assert not any(r.passed for r in flipped)
    assert all("damaged image is running" in r.message for r in flipped)


class CheckingDevice(FakeDevice):
    """Runs the slot only if it holds an intact image; otherwise stays in its bootloader."""

    def sample_cpu(self, n=4, interval=0.02):
        self.run_for(n * interval)
        intact = self.read_bytes(SLOT, 16) in (OLD_IMAGE, NEW_IMAGE)
        return [self.cpu if intact else (BASE + 0x40, 0)] * n


def test_staying_out_of_the_damaged_image_passes():
    out = campaign(CheckingDevice())
    flipped = [r for r in out.results if r.bit_error]
    assert flipped and all(r.passed for r in flipped)
