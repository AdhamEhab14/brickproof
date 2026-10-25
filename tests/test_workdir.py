import os

import pytest

from brickproof import adapter as adapters
from brickproof.engine import workdir as wd
from brickproof.engine.session import FlashGeometry
from demo_paths import demo_adapter

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


def test_a_sector_model_gets_its_sectors():
    text = open(os.path.join(wd.MODELS, "stm32f4_flash.py")).read()
    flash = FlashGeometry(base=0x08000000, size=0x6000, sectors=[(0, 0x2000), (0x2000, 0x4000)])
    text = wd.patch_geometry(text, flash)
    assert "\nSECTORS = [(0x0, 0x2000), (0x2000, 0x4000)]\n" in text
    assert "\nFLASH_SIZE = 0x6000\n" in text
    with pytest.raises(ValueError, match="SECTORS"):
        wd.patch_geometry(flash_model(), flash)       # the F1 model erases by page


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


def test_platform_gets_the_chips_real_memory_sizes(tmp_path):
    ad = adapters.load(demo_adapter("adapter"))
    assert wd.memory_sizes(ad) == {"sram": 0x5000, "flash": 0x20000}
    wd.prepare(str(tmp_path), ad)
    repl = (tmp_path / "platform.repl").read_text()
    assert "\nsram:\n    size: 0x5000\n" in repl
    assert "iwdg: Timers.STM32_IndependentWatchdog" in repl, "the F103 gets a real watchdog"
    assert "\nflash:\n    size: 0x20000\n" in repl
    assert "sysbus 0x08000000;\n        sysbus 0x00000000" in repl, "flash is also at the boot alias"


def test_ram_base_must_match_the_platform():
    ad = adapters.load(THREE_TIER)
    ad.ram_base = 0x10000000
    with pytest.raises(ValueError, match="ram.base"):
        wd.memory_sizes(ad)


def test_every_hole_in_the_address_space_gets_a_guard(tmp_path):
    ad = adapters.load(demo_adapter("adapter"))
    assert wd.holes(ad) == [("ramGuard", 0x20005000, 0x22000000 - 0x20005000),
                            ("flashGuard", 0x08020000, 0x1FFF0000 - 0x08020000),
                            ("aliasGuard", 0x20000, 0x08000000 - 0x20000)]
    wd.prepare(str(tmp_path), ad)
    repl = (tmp_path / "platform.repl").read_text()
    assert "ramGuard: Python.PythonPeripheral @ sysbus 0x20005000" in repl
    assert "flashGuard: Python.PythonPeripheral @ sysbus 0x8020000" in repl
    guard = (tmp_path / "models" / "ramGuard.py").read_text()
    assert "\nGUARD_BASE = 0x20005000\n" in guard
    assert "\nFAULT_REG = 0x40022118\n" in guard         # the flash model's fault latch
    assert not (tmp_path / "models" / "mem_guard.py").exists()   # only the patched copies


def test_the_flash_model_gets_a_shadow_as_big_as_the_flash(tmp_path):
    ad = adapters.load(demo_adapter("adapter"))
    wd.prepare(str(tmp_path), ad)
    repl = (tmp_path / "platform.repl").read_text()
    # room for the flash and, after it, the option bytes
    assert "bpShadow: Memory.MappedMemory @ sysbus 0x91000000\n    size: 0x21000\n" in repl
    assert "bpState: Memory.MappedMemory @ sysbus 0x90000000" in repl
    assert "bpOptionBytes: Memory.MappedMemory @ sysbus 0x1FFFF800" in repl
    model = (tmp_path / "models" / "stm32f1_flash.py").read_text()
    assert "\nOB_BASE = 0x1FFFF800\n" in model and "\nWRP_UNIT = 0x1000\n" in model
    assert "\nTIMING = 0x1\n" in model, "operations take their typical time unless told otherwise"
    assert not (tmp_path / "models" / "stm32f4_flash.py").exists(), "only this chip's controller"
    rcc = (tmp_path / "models" / "stm32f1_rcc.py").read_text()
    assert "\nHSE_HZ = 0x7A1200\n" in rcc, "the board's crystal reaches the clock model"
    assert 'TRACE_FILE = "%s/trace.txt"' % str(tmp_path).replace("\\", "/") in model


def test_an_external_flash_chip_is_put_on_its_bus_with_its_chip_select(tmp_path):
    ad = adapters.load(demo_adapter("f411-ext"))
    wd.prepare(str(tmp_path), ad)
    repl = (tmp_path / "platform.repl").read_text()
    assert "extflash: SPI.BpSpiNor @ spi1\n    size: 0x100000\n    address: 0xA0000000\n" in repl
    assert "    state: 0x90000000\n" in repl and "    timing: 1\n" in repl
    assert "    status1: 0x0\n    status2: 0x0\n" in repl      # no block protection as shipped
    assert 'traceFile: "%s/trace.txt"' % str(tmp_path).replace("\\", "/") in repl
    assert "gpioPortA:\n    4 -> extflash@0\n" in repl
    assert (tmp_path / "models" / "BpSpiNor.cs").exists()


def test_without_an_external_flash_chip_nothing_of_it_is_there(tmp_path):
    ad = adapters.load(demo_adapter("f411"))
    wd.prepare(str(tmp_path), ad)
    assert "extflash" not in (tmp_path / "platform.repl").read_text()
    assert not (tmp_path / "models" / "BpSpiNor.cs").exists()


def _nrf_adapter(tmp_path):
    p = tmp_path / "nrf.yaml"
    p.write_text("name: nrf\ntarget: .\nplatform: {base: nrf52840}\n"
                 "flash: {base: 0x0, size: 0x100000, page: 0x1000}\nram: {size: 0x40000}\n"
                 "firmware:\n  - file: app.elf\ndriver: {file: driver.py}\nuart: uart0\n")
    return adapters.load(str(p))


def test_an_nrf52840_is_guarded_where_it_has_no_memory(tmp_path):
    ad = _nrf_adapter(tmp_path)
    # flash at 0 has no alias; RAM is also seen at 0x00800000; FICR and UICR are left open
    assert wd.holes(ad) == [("flashGuard", 0x100000, 0x800000 - 0x100000),
                            ("codeRamGuard", 0x840000, 0x10000000 - 0x840000),
                            ("infoGuard", 0x10002000, 0x20000000 - 0x10002000),
                            ("ramGuard", 0x20040000, 0x40000000 - 0x20040000)]
    assert wd.memory_sizes(ad) == {"ram": 0x40000, "flash": 0x100000}


def test_an_nrf52840_gets_its_own_flash_controller_and_no_svd_download(tmp_path):
    ad = _nrf_adapter(tmp_path)
    (tmp_path / "app.elf").write_bytes(b"\x7fELF")
    work = tmp_path / "work"
    wd.prepare(str(work), ad)
    repl = (work / "platform.repl").read_text()
    assert "flashctl: Python.PythonPeripheral @ sysbus 0x4001E000" in repl
    assert "ApplySVD" not in repl and "using " not in repl     # nothing fetched at start-up
    model = (work / "models" / "nrf52_flash.py").read_text()
    assert "\nPAGE = 0x1000\n" in model and "\nFLASH_SIZE = 0x100000\n" in model
    assert not (work / "models" / "stm32f4_flash.py").exists()
    assert "bpOptionBytes: Memory.MappedMemory @ sysbus 0x10001000" in repl       # the UICR
