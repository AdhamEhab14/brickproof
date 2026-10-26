"""Build the folder a run works in: copies of the firmware under paths without spaces
and, for Renode, models with the target's geometry and the platform file."""
import os
import re
import shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(HERE, "models")
PLATFORMS = os.path.join(HERE, "platforms")

_GEOMETRY = {"FLASH_BASE": "base", "FLASH_SIZE": "size"}
FAULT_REG_OFFSET = 0x118        # REG_FAULT_ADDR in session.py
TRACE_NAME = "trace.txt"        # RenodeSession.TRACE_NAME
STATE_BASE = 0x90000000         # STATE in the flash models: op count, cut point, trace switch
SHADOW_BASE = 0x91000000        # SHADOW in the flash models
EXPECT_BASE = 0x92000000        # EXPECT in the flash models: an image to compare flash with

# How each base platform names its memories and where they start. Renode's stock
# platforms are far bigger than the chips (the F103 gets 256 MB of RAM and 512 MB
# of flash), so the engine shrinks them to the adapter's real sizes.
MEMORIES = {
    "stm32f103": {"ram": ("sram", 0x20000000), "flash": ("flash", 0x08000000),
                  # where the address space is empty on the real chip: from the end of
                  # RAM to the bit-band alias, from the end of flash to system memory
                  "ram_hole_end": 0x22000000, "flash_hole_end": 0x1FFF0000,
                  # room for the option bytes: up to whatever comes next on the bus
                  "ob_region": 0x800},
    "stm32f411": {"ram": ("sram", 0x20000000), "flash": ("flash", 0x08000000),
                  "ram_hole_end": 0x22000000, "flash_hole_end": 0x1FFF0000,
                  "ob_region": 0x400},
    # flash at 0x08000000 and at 0; SRAM2 at 0x10000000; system memory and option bytes from
    # 0x1FFF0000
    "stm32l476": {"ram": ("sram", 0x20000000), "flash": ("flash", 0x08000000), "ob_region": 0x800,
                  "holes": lambda flash_end, ram_end, ram_size: [
                      ("aliasGuard", flash_end - 0x08000000, 0x08000000 - (flash_end - 0x08000000)),
                      ("flashGuard", flash_end, 0x10000000 - flash_end),
                      ("sram2Guard", 0x10008000, 0x1FFF0000 - 0x10008000),
                      ("ramGuard", ram_end, 0x22000000 - ram_end)]},
    # flash at 0 with no alias; RAM also seen at 0x00800000 for code; FICR and UICR at
    # 0x10000000; peripherals from 0x40000000
    "nrf52840": {"ram": ("ram", 0x20000000), "flash": ("flash", 0x0), "ob_region": 0x1000,
                 "holes": lambda flash_end, ram_end, ram_size: [
                     ("flashGuard", flash_end, 0x800000 - flash_end),
                     ("codeRamGuard", 0x800000 + ram_size, 0x10000000 - 0x800000 - ram_size),
                     ("infoGuard", 0x10002000, 0x20000000 - 0x10002000),
                     ("ramGuard", ram_end, 0x40000000 - ram_end)]},
}


# Where USER is in each chip's option bytes and which of its bits are nRST_STOP and nRST_STDBY
PWR_USER = {"stm32f103": (2, 1, 2), "stm32f411": (0, 6, 7)}


def holes(adapter):
    """[(name, first address, size)] of the ranges that do not exist on the chip.
    Each gets a mem_guard, so an access there is a recorded fault, not a silent 0."""
    info = MEMORIES[adapter.platform]
    ram_end = adapter.ram_base + adapter.ram_size
    flash_end = adapter.flash.base + adapter.flash.size
    if "holes" in info:
        return info["holes"](flash_end, ram_end, adapter.ram_size)
    # flash is also seen at address 0 (the boot alias); between the end of that copy
    # and the flash itself there is nothing
    return [("ramGuard", ram_end, info["ram_hole_end"] - ram_end),
            ("flashGuard", flash_end, info["flash_hole_end"] - flash_end),
            ("aliasGuard", adapter.flash.size, adapter.flash.base - adapter.flash.size)]


def memory_sizes(adapter):
    """{Renode memory name: size it must have} for this adapter."""
    info = MEMORIES[adapter.platform]
    ram_name, ram_base = info["ram"]
    flash_name, region_base = info["flash"]
    if adapter.ram_base != ram_base:
        raise ValueError("ram.base 0x%X does not match the %s platform (0x%X)"
                         % (adapter.ram_base, adapter.platform, ram_base))
    sizes = {ram_name: adapter.ram_size,
             flash_name: adapter.flash.base + adapter.flash.size - region_base}
    if adapter.flash.ecc:
        sizes["bpEcc"] = adapter.flash.ecc_size
    return sizes


def _set_const(model_text, const, value):
    """Rewrite one `NAME = ...` line of a model (they take no parameters in Renode)."""
    model_text, n = re.subn(r"^%s = .*$" % const, "%s = 0x%X" % (const, value),
                            model_text, count=1, flags=re.M)
    if n != 1:
        raise ValueError("model has no '%s = ...' line" % const)
    return model_text


def _set_trace_file(model_text, path):
    """Tell a flash model where to log operations. The path is spliced in as plain
    text, not as a regex replacement, so a backslash in it stays a backslash."""
    lines = model_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("TRACE_FILE = "):
            lines[i] = 'TRACE_FILE = "%s"' % path
            return "\n".join(lines)
    raise ValueError("flash model has no 'TRACE_FILE = ...' line")


def _set_sectors(model_text, sectors):
    """Rewrite the `SECTORS = [...]` line of a flash model that erases by sector."""
    line = "SECTORS = [%s]" % ", ".join("(0x%X, 0x%X)" % s for s in sectors)
    model_text, n = re.subn(r"^SECTORS = .*$", line, model_text, count=1, flags=re.M)
    if n != 1:
        raise ValueError("model has no 'SECTORS = ...' line")
    return model_text


COMMON_MARK = re.compile(r"^# @FLASH_COMMON@.*\n(?:#.*\n)?", re.M)


def with_common(model_text):
    """The flash model with models/flash_common.py put in at its '# @FLASH_COMMON@' line:
    the helpers every model has, kept in one place. Renode cannot import it, so it goes in
    as text, like the geometry."""
    with open(os.path.join(MODELS, "flash_common.py")) as f:
        common = f.read()
    model_text, n = COMMON_MARK.subn(lambda m: common, model_text)
    if n != 1:
        raise ValueError("flash model has no '# @FLASH_COMMON@' line")
    return model_text


def patch_geometry(model_text, flash):
    """Rewrite a flash model's geometry lines: FLASH_BASE and FLASH_SIZE, and what an
    erase wipes there, one PAGE size or a list of SECTORS."""
    if flash.sectors:
        model_text = _set_sectors(model_text, flash.sectors)
    else:
        model_text = _set_const(model_text, "PAGE", flash.page)
    for const, attr in _GEOMETRY.items():
        model_text = _set_const(model_text, const, getattr(flash, attr))
    return model_text


def _slash(path):
    return os.path.abspath(path).replace("\\", "/")


def platform_text(platform, models_dir, extra_file=None, adapter_dir=None, sizes=None):
    """The base platform, real memory sizes, then an adapter's extra lines."""
    text = open(os.path.join(PLATFORMS, platform + ".repl")).read()
    text = text.replace("@MODELS@", _slash(models_dir))
    for name, size in (sizes or {}).items():
        # an existing memory is resized by name alone; redeclaring its type is rejected
        text += "\n%s:\n    size: 0x%X\n" % (name, size)
    if extra_file:
        extra = open(extra_file).read().replace("@ADAPTER@", _slash(adapter_dir))
        text += "\n" + extra
    return text


def prepare(workdir, adapter):
    """Fill `workdir` for `adapter`; return the firmware list as session-relative paths."""
    if adapter.emulator == "m33mu":
        return copy_firmware(workdir, adapter)      # m33mu brings its own chip
    models = os.path.join(workdir, "models")
    os.makedirs(models, exist_ok=True)
    for name in os.listdir(MODELS):
        if not name.endswith(".py") or name.startswith("_") or name in ("mem_guard.py", "flash_common.py"):
            continue
        if name.endswith("_flash.py") and name != adapter.flash.model:
            continue                            # another chip family's controller
        text = open(os.path.join(MODELS, name)).read()
        if name.endswith("_flash.py"):
            text = with_common(text)
            text = patch_geometry(text, adapter.flash)
            if adapter.flash.ob_base is not None:
                text = _set_const(text, "OB_BASE", adapter.flash.ob_base)
                text = _set_const(text, "OB_SIZE", adapter.flash.ob_size)
            if adapter.flash.wrp_unit:
                text = _set_const(text, "WRP_UNIT", adapter.flash.wrp_unit)
            text = _set_const(text, "TIMING", adapter.flash.timing)
            if adapter.flash.worn:
                text = _set_const(text, "WORN_FROM", adapter.flash.worn[0])
                text = _set_const(text, "WORN_TO", adapter.flash.worn[1])
            text = _set_trace_file(text, "%s/%s" % (_slash(workdir), TRACE_NAME))
        elif name.endswith("_rcc.py"):
            text = _set_const(text, "HSE_HZ", adapter.hse)
        elif name == "nrf52_power.py":
            if adapter.platform != "nrf52840":
                continue
            for const, value in (("RAM_BASE", adapter.ram_base), ("RAM_SIZE", adapter.ram_size),
                                 ("WAKE_AFTER_US", int(adapter.wake_after * 1e6))):
                text = _set_const(text, const, value)
        elif name == "stm32_pwr.py":
            if adapter.platform not in PWR_USER:
                continue                        # the F1 and F4's PWR only
            at, stop, standby = PWR_USER[adapter.platform]
            for const, value in (("RAM_BASE", adapter.ram_base), ("RAM_SIZE", adapter.ram_size),
                                 ("OB_USER", adapter.flash.ob_base + at), ("NRST_STOP_BIT", stop),
                                 ("NRST_STDBY_BIT", standby),
                                 ("WAKE_AFTER_US", int(adapter.wake_after * 1e6))):
                text = _set_const(text, const, value)
        with open(os.path.join(models, name), "w", newline="\n") as f:
            f.write(text)

    repl = platform_text(adapter.platform, models, adapter.platform_extra, adapter.folder,
                         memory_sizes(adapter))
    # the flash model's two private copies of the flash image (see its header): the
    # flash, with room after it for the option bytes
    for name, base in (("bpShadow", SHADOW_BASE), ("bpExpect", EXPECT_BASE)):
        repl += "\n%s: Memory.MappedMemory @ sysbus 0x%X\n    size: 0x%X\n" % (
            name, base, adapter.flash.size + 0x1000)
    # the option bytes themselves, at their real address
    if adapter.flash.ob_base is not None:
        repl += "\nbpOptionBytes: Memory.MappedMemory @ sysbus 0x%X\n    size: 0x%X\n" % (
            adapter.flash.ob_base, MEMORIES[adapter.platform]["ob_region"])
    # an external SPI NOR flash chip: its model, where it hangs, and its chip select
    f = adapter.flash
    if f.ext_size:
        shutil.copyfile(os.path.join(MODELS, "BpSpiNor.cs"), os.path.join(models, "BpSpiNor.cs"))
        repl += ('\nextflash: SPI.BpSpiNor @ %s\n    size: 0x%X\n    address: 0x%X\n    state: 0x%X\n'
                 '    traceFile: "%s/%s"\n    timing: %d\n    status1: 0x%X\n    status2: 0x%X\n'
                 '    status3: 0x%X\n' % (
                     f.ext_bus, f.ext_size, f.ext_base, STATE_BASE, _slash(workdir), TRACE_NAME, f.timing,
                     f.ext_status & 0xFF, (f.ext_status >> 8) & 0xFF, (f.ext_status >> 16) & 0xFF))
        lines = {f.ext_cs: 0}
        if f.ext_wp:
            lines[f.ext_wp] = 1                 # /WP is the chip's GPIO 1
        for port in sorted({pin[1] for pin in lines}):
            repl += "\ngpioPort%s:\n" % port + "".join(
                "    %d -> extflash@%d\n" % (int(pin[2:]), n) for pin, n in lines.items() if pin[1] == port)
    # an I2C EEPROM: its model and where it sits on the bus
    if f.eeprom_size:
        shutil.copyfile(os.path.join(MODELS, "BpI2cEeprom.cs"), os.path.join(models, "BpI2cEeprom.cs"))
        repl += ('\neeprom: I2C.BpI2cEeprom @ %s 0x%X\n    size: 0x%X\n    address: 0x%X\n    state: 0x%X\n'
                 '    traceFile: "%s/%s"\n    pageSize: %d\n    addressBytes: %d\n    timing: %d\n' % (
                     f.eeprom_bus, f.eeprom_i2c, f.eeprom_size, f.eeprom_base, STATE_BASE, _slash(workdir),
                     TRACE_NAME, f.eeprom_page, f.eeprom_address_bytes, f.timing))
    # the PWR controller's low-power modes (models/stm32_pwr.py), in place of Renode's
    if adapter.platform in PWR_USER:
        if adapter.platform == "stm32f411":
            repl += "\npwr: @ none\n"
        repl += ('\nlowPower: Python.PythonPeripheral @ sysbus 0x40007000\n    size: 0x400\n'
                 '    initable: true\n    filename: "%s/stm32_pwr.py"\n' % _slash(models))
    guard = open(os.path.join(MODELS, "mem_guard.py")).read()
    for name, base, size in holes(adapter):
        text = _set_const(guard, "GUARD_BASE", base)
        text = _set_const(text, "FAULT_REG", adapter.flash.controller + FAULT_REG_OFFSET)
        with open(os.path.join(models, name + ".py"), "w", newline="\n") as f:
            f.write(text)
        repl += ('\n%s: Python.PythonPeripheral @ sysbus 0x%X\n    size: 0x%X\n    initable: false\n'
                 '    filename: "%s/%s.py"\n' % (name, base, size, _slash(models), name))
    with open(os.path.join(workdir, "platform.repl"), "w", newline="\n") as f:
        f.write(repl)
    return copy_firmware(workdir, adapter)


def copy_firmware(workdir, adapter):
    """Copy the firmware into `workdir/fw`; return [(relative path, address)]."""
    fw_dir = os.path.join(workdir, "fw")
    os.makedirs(fw_dir, exist_ok=True)
    firmware = []
    for i, (src, addr) in enumerate(adapter.firmware):
        if not os.path.exists(src):
            raise FileNotFoundError("firmware file not found: %s (is the target built?)" % src)
        name = "%d_%s" % (i, re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(src)))
        shutil.copyfile(src, os.path.join(fw_dir, name))
        firmware.append(("fw/" + name, addr))
    return firmware
