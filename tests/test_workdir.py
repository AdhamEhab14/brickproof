import os

import pytest

from brickproof import adapter as adapters
from brickproof.engine import workdir as wd
from brickproof.engine.session import FlashGeometry

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THREE_TIER = os.path.join(REPO, "adapters", "three_tier_f103", "adapter.yaml")


def flash_model():
    return open(os.path.join(wd.MODELS, "stm32f1_flash.py")).read()


def test_geometry_is_rewritten():
    text = wd.patch_geometry(flash_model(), FlashGeometry(base=0x08000000, size=0x80000, page=0x800))
    assert "\nPAGE = 0x800\n" in text
    assert "\nFLASH_SIZE = 0x80000\n" in text
    assert "\nFLASH_BASE = 0x8000000\n" in text


def test_default_geometry_matches_the_f103rb():
    # rewriting with the F103RB's own numbers must not change the model's behaviour
    text = wd.patch_geometry(flash_model(), FlashGeometry(base=0x08000000, size=0x20000, page=0x400))
    assert "PAGE = 0x400" in text and "FLASH_SIZE = 0x20000" in text


def test_patch_fails_loudly_on_a_model_without_geometry():
    with pytest.raises(ValueError, match="PAGE"):
        wd.patch_geometry("x = 1\n", FlashGeometry(base=0, size=0x400, page=0x400))


def test_prepare_builds_a_space_free_work_folder(tmp_path):
    target = tmp_path / "my firmware"           # a space, like "D:\Embedded projects"
    (target / "build-test").mkdir(parents=True)
    for name in ("boot_manager.elf", "fbl.elf"):
        (target / "build-test" / name).write_bytes(b"\x7fELF")
    ad = adapters.load(THREE_TIER, target=str(target))
    work = tmp_path / "work"
    work.mkdir()

    firmware = wd.prepare(str(work), ad)

    assert [f for f, _ in firmware] == ["fw/0_boot_manager.elf", "fw/1_fbl.elf"]
    assert all(" " not in f for f, _ in firmware)
    repl = (work / "platform.repl").read_text()
    assert "@MODELS@" not in repl and "@ADAPTER@" not in repl
    assert "stm32f1_flash.py" in repl and "can_stub.py" in repl
    assert (work / "models" / "stm32f1_flash.py").exists()


def test_prepare_names_the_missing_firmware(tmp_path):
    ad = adapters.load(THREE_TIER, target=str(tmp_path))
    with pytest.raises(FileNotFoundError, match="boot_manager.elf"):
        wd.prepare(str(tmp_path), ad)
