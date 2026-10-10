"""Build the folder a Renode run works in: models with the target's geometry, the
platform file, and copies of the firmware under paths without spaces."""
import os
import re
import shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(HERE, "models")
PLATFORMS = os.path.join(HERE, "platforms")

_GEOMETRY = {"PAGE": "page", "FLASH_BASE": "base", "FLASH_SIZE": "size"}
FAULT_REG_OFFSET = 0x118        # REG_FAULT_ADDR in session.py

# How each base platform names its memories and where they start. Renode's stock
# platforms are far bigger than the chips (the F103 gets 256 MB of RAM and 512 MB
# of flash), so the engine shrinks them to the adapter's real sizes.
MEMORIES = {
    "stm32f103": {"ram": ("sram", 0x20000000), "flash": ("flash", 0x00000000),
                  # where the address space is empty on the real chip: from the end of
                  # RAM to the bit-band alias, from the end of flash to system memory
                  "ram_hole_end": 0x22000000, "flash_hole_end": 0x1FFF0000},
}


def holes(adapter):
    """[(name, first address, size)] of the ranges that do not exist on the chip.
    Each gets a mem_guard, so an access there is a recorded fault, not a silent 0."""
    info = MEMORIES[adapter.platform]
    ram_end = adapter.ram_base + adapter.ram_size
    flash_end = adapter.flash.base + adapter.flash.size
    return [("ramGuard", ram_end, info["ram_hole_end"] - ram_end),
            ("flashGuard", flash_end, info["flash_hole_end"] - flash_end)]


def memory_sizes(adapter):
    """{Renode memory name: size it must have} for this adapter."""
    info = MEMORIES[adapter.platform]
    ram_name, ram_base = info["ram"]
    flash_name, region_base = info["flash"]
    if adapter.ram_base != ram_base:
        raise ValueError("ram.base 0x%X does not match the %s platform (0x%X)"
                         % (adapter.ram_base, adapter.platform, ram_base))
    # the flash region may start below the flash itself (boot alias at 0)
    return {ram_name: adapter.ram_size,
            flash_name: adapter.flash.base + adapter.flash.size - region_base}


def _set_const(model_text, const, value):
    """Rewrite one `NAME = ...` line of a model (they take no parameters in Renode)."""
    model_text, n = re.subn(r"^%s = .*$" % const, "%s = 0x%X" % (const, value),
                            model_text, count=1, flags=re.M)
    if n != 1:
        raise ValueError("model has no '%s = ...' line" % const)
    return model_text


def patch_geometry(model_text, flash):
    """Rewrite the PAGE / FLASH_BASE / FLASH_SIZE lines of a flash model."""
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
    models = os.path.join(workdir, "models")
    os.makedirs(models, exist_ok=True)
    for name in os.listdir(MODELS):
        if not name.endswith(".py") or name.startswith("_") or name == "mem_guard.py":
            continue
        text = open(os.path.join(MODELS, name)).read()
        if name.endswith("_flash.py"):
            text = patch_geometry(text, adapter.flash)
        with open(os.path.join(models, name), "w", newline="\n") as f:
            f.write(text)

    repl = platform_text(adapter.platform, models, adapter.platform_extra, adapter.folder,
                         memory_sizes(adapter))
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
