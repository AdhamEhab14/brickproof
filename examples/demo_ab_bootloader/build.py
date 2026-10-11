"""Build the demo for both chips: the bootloader (correct, and one build per known bug)
and two app images. The STM32F411 files get an f411_ prefix.

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
CFLAGS = ["-mthumb", "-Os", "-g", "-Wall", "-Wextra", "-Werror",
          "-ffreestanding", "-nostdlib", "-ffunction-sections", "-Icommon"]
# per chip: file name prefix, compiler flags, linker script suffix, bugs that do not apply
CHIPS = [
    ("", ["-mcpu=cortex-m3"], "", ()),
    # an F4 lets a half-written cell be programmed again, so resuming a copy is fine there
    ("f411_", ["-mcpu=cortex-m4", "-DSTM32F4"], "_f411", ("bootloader_bug_resume_copy",)),
]
LDFLAGS = ["-Wl,--gc-sections", "-Lcommon", "-lgcc"]
COMMON = ["common/startup.c", "common/uart.c"]

BOOTLOADERS = {
    "bootloader": [],
    "bootloader_bug_consume_first": ["-DBUG_CONSUME_FIRST"],
    "bootloader_bug_trust_header": ["-DBUG_TRUST_HEADER"],
    "bootloader_bug_naive_floor": ["-DBUG_NAIVE_FLOOR"],
    "bootloader_bug_pop_after_switch": ["-DBUG_POP_AFTER_SWITCH"],
    "bootloader_bug_no_erase": ["-DBUG_NO_ERASE"],
    "bootloader_bug_no_unlock": ["-DBUG_NO_UNLOCK"],
    "bootloader_bug_resume_copy": ["-DBUG_RESUME_COPY"],
    "bootloader_bug_retry_limit": ["-DBUG_RETRY_LIMIT"],
    "bootloader_bug_self_lock": ["-DBUG_SELF_LOCK"],
}
APP_VERSIONS = (1, 2)
META_MAGIC = 0x4D455441


def floor_record(seq, floor):
    """A rollback-floor page as the bootloader writes it (seq, floor, magic)."""
    return struct.pack("<III", seq, floor, META_MAGIC)


def run(cmd):
    subprocess.run(cmd, cwd=HERE, check=True)


def outputs():
    """Every file a build leaves for the adapters to load."""
    names = ["meta_floor1.bin"]
    for prefix, _, _, skip in CHIPS:
        names += ["%s%s.elf" % (prefix, b) for b in BOOTLOADERS if b not in skip]
        names += ["%sapp_v%d.img" % (prefix, v) for v in APP_VERSIONS]
    return names


def build(out):
    os.makedirs(os.path.join(HERE, out), exist_ok=True)
    for prefix, flags, ld, skip in CHIPS:
        cc = [CC, *CFLAGS, *flags]
        for name, defs in BOOTLOADERS.items():
            if name in skip:
                continue
            run([*cc, *defs, "-Tbootloader/link%s.ld" % ld, "bootloader/main.c", *COMMON,
                 *LDFLAGS, "-o", "%s/%s%s.elf" % (out, prefix, name)])
        for v in APP_VERSIONS:
            stem = "%s/%sapp_v%d" % (out, prefix, v)
            run([*cc, "-DAPP_VERSION=%d" % v, "-Tapp/link%s.ld" % ld, "app/main.c", *COMMON,
                 *LDFLAGS, "-o", stem + ".elf"])
            run([OBJCOPY, "-O", "binary", stem + ".elf", stem + ".bin"])
            with open(os.path.join(HERE, stem + ".bin"), "rb") as f:
                body = f.read()
            with open(os.path.join(HERE, stem + ".img"), "wb") as f:
                f.write(make_image(body, v))
    # the device as shipped: v1 installed, floor already at 1
    with open(os.path.join(HERE, out, "meta_floor1.bin"), "wb") as f:
        f.write(floor_record(1, 1))


if __name__ == "__main__":
    build("build")
    if "--prebuilt" in sys.argv:
        dst = os.path.join(HERE, "prebuilt")
        os.makedirs(dst, exist_ok=True)
        for name in outputs():
            shutil.copyfile(os.path.join(HERE, "build", name), os.path.join(dst, name))
    print("built into", os.path.join(HERE, "build"))
