"""Build the demo: the bootloader (correct and three bug variants) and two app images.

Needs arm-none-eabi-gcc on PATH. Output goes to build/. Pass --prebuilt to also
refresh the committed copies in prebuilt/, which is what users without a
toolchain run.

    python build.py [--prebuilt]
"""
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))
from mkimage import make_image  # noqa: E402

CC = "arm-none-eabi-gcc"
OBJCOPY = "arm-none-eabi-objcopy"
CFLAGS = ["-mcpu=cortex-m3", "-mthumb", "-Os", "-g", "-Wall", "-Wextra", "-Werror",
          "-ffreestanding", "-nostdlib", "-ffunction-sections", "-Icommon"]
LDFLAGS = ["-Wl,--gc-sections", "-Lcommon", "-lgcc"]
COMMON = ["common/startup.c", "common/uart.c"]

BOOTLOADERS = {
    "bootloader": [],
    "bootloader_bug_consume_first": ["-DBUG_CONSUME_FIRST"],
    "bootloader_bug_trust_header": ["-DBUG_TRUST_HEADER"],
    "bootloader_bug_naive_floor": ["-DBUG_NAIVE_FLOOR"],
    "bootloader_bug_pop_after_switch": ["-DBUG_POP_AFTER_SWITCH"],
}
APP_VERSIONS = (1, 2)
META_MAGIC = 0x4D455441


def floor_record(seq, floor):
    """A rollback-floor page as the bootloader writes it (seq, floor, magic)."""
    return struct.pack("<III", seq, floor, META_MAGIC)


def run(cmd):
    subprocess.run(cmd, cwd=HERE, check=True)


def build(out):
    os.makedirs(os.path.join(HERE, out), exist_ok=True)
    for name, defs in BOOTLOADERS.items():
        run([CC, *CFLAGS, *defs, "-Tbootloader/link.ld", "bootloader/main.c", *COMMON,
             *LDFLAGS, "-o", "%s/%s.elf" % (out, name)])
    for v in APP_VERSIONS:
        elf, raw = "%s/app_v%d.elf" % (out, v), "%s/app_v%d.bin" % (out, v)
        run([CC, *CFLAGS, "-DAPP_VERSION=%d" % v, "-Tapp/link.ld", "app/main.c", *COMMON,
             *LDFLAGS, "-o", elf])
        run([OBJCOPY, "-O", "binary", elf, raw])
        with open(os.path.join(HERE, raw), "rb") as f:
            body = f.read()
        with open(os.path.join(HERE, out, "app_v%d.img" % v), "wb") as f:
            f.write(make_image(body, v))
    # the device as shipped: v1 installed, floor already at 1
    with open(os.path.join(HERE, out, "meta_floor1.bin"), "wb") as f:
        f.write(floor_record(1, 1))


if __name__ == "__main__":
    build("build")
    if "--prebuilt" in sys.argv:
        dst = os.path.join(HERE, "prebuilt")
        os.makedirs(dst, exist_ok=True)
        names = ["%s.elf" % b for b in BOOTLOADERS] + ["app_v%d.img" % v for v in APP_VERSIONS]
        for name in names + ["meta_floor1.bin"]:
            shutil.copyfile(os.path.join(HERE, "build", name), os.path.join(dst, name))
    print("built into", os.path.join(HERE, "build"))
