"""Build the folder a Renode run works in: models with the target's geometry, the
platform file, and copies of the firmware under paths without spaces."""
import os
import re
import shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(HERE, "models")
PLATFORMS = os.path.join(HERE, "platforms")

_GEOMETRY = {"PAGE": "page", "FLASH_BASE": "base", "FLASH_SIZE": "size"}


def patch_geometry(model_text, flash):
    """Rewrite the PAGE / FLASH_BASE / FLASH_SIZE lines of a flash model."""
    for const, attr in _GEOMETRY.items():
        model_text, n = re.subn(r"^%s = .*$" % const, "%s = 0x%X" % (const, getattr(flash, attr)),
                                model_text, count=1, flags=re.M)
        if n != 1:
            raise ValueError("flash model has no '%s = ...' line" % const)
    return model_text


def _slash(path):
    return os.path.abspath(path).replace("\\", "/")


def platform_text(platform, models_dir, extra_file=None, adapter_dir=None):
    """The base platform with an adapter's extra lines appended."""
    text = open(os.path.join(PLATFORMS, platform + ".repl")).read()
    text = text.replace("@MODELS@", _slash(models_dir))
    if extra_file:
        extra = open(extra_file).read().replace("@ADAPTER@", _slash(adapter_dir))
        text += "\n" + extra
    return text


def prepare(workdir, adapter):
    """Fill `workdir` for `adapter`; return the firmware list as session-relative paths."""
    models = os.path.join(workdir, "models")
    os.makedirs(models, exist_ok=True)
    for name in os.listdir(MODELS):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        text = open(os.path.join(MODELS, name)).read()
        if name.endswith("_flash.py"):
            text = patch_geometry(text, adapter.flash)
        with open(os.path.join(models, name), "w", newline="\n") as f:
            f.write(text)

    with open(os.path.join(workdir, "platform.repl"), "w", newline="\n") as f:
        f.write(platform_text(adapter.platform, models, adapter.platform_extra, adapter.folder))

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
