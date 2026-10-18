"""Build the demo for every chip: the bootloader (correct, and one build per known bug)
and two app images. The files of each chip but the F103 get a prefix: f411_, l476_, h563_
and nrf52_.

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
    # an F1 page erase is far shorter than the watchdog's timeout: no bug to show there
    ("", ["-mcpu=cortex-m3"], "", ("bootloader_bug_watchdog", "bootloader_bug_boot_loop", "bootloader_ext",
                                   "bootloader_ext_bug_consume_first", "bootloader_bug_nwrite",
                                   "bootloader_ee", "bootloader_ee_bug_no_invalidate",
                                   "bootloader_bug_no_ecc_nmi")),
    # an F4 lets a half-written cell be programmed again, so resuming a copy is fine there
    ("f411_", ["-mcpu=cortex-m4", "-DSTM32F4"], "_f411", ("bootloader_bug_resume_copy",
                                                         "bootloader_bug_boot_loop",
                                                         "bootloader_bug_nwrite",
                                                         "bootloader_bug_no_ecc_nmi")),
    # the nRF52 has no flash keys to forget, a 4 KB page erase is far shorter than any
    # watchdog timeout, a half-written word may be written once more, and its protection
    # (the ACL) is set at run time, not in option bytes a cut can leave half rewritten
    ("nrf52_", ["-mcpu=cortex-m4", "-DNRF52"], "_nrf52", ("bootloader_bug_resume_copy",
                                                         "bootloader_bug_no_unlock",
                                                         "bootloader_bug_self_lock",
                                                         "bootloader_bug_watchdog",
                                                         "bootloader_ext",
                                                         "bootloader_ext_bug_consume_first",
                                                         "bootloader_ee",
                                                         "bootloader_ee_bug_no_invalidate",
                                                         "bootloader_bug_no_ecc_nmi",
                                                         "bootloader_standby",
                                                         "bootloader_bug_standby_ram")),
    # the L4: double words with ECC. A 2 KB page erase is far shorter than the watchdog's
    # timeout, the option-byte bug is F-series code, and the external memories are wired
    # up on the F411 only
    ("l476_", ["-mcpu=cortex-m4", "-DSTM32L4"], "_l476", ("bootloader_bug_self_lock",
                                                         "bootloader_bug_boot_loop",
                                                         "bootloader_bug_watchdog",
                                                         "bootloader_bug_nwrite",
                                                         "bootloader_ext",
                                                         "bootloader_ext_bug_consume_first",
                                                         "bootloader_ee",
                                                         "bootloader_ee_bug_no_invalidate",
                                                         "bootloader_standby",
                                                         "bootloader_bug_standby_ram")),
    # the H563 (on m33mu): the option-byte and watchdog bugs are F-series code, and the
    # external memories are wired up on the F411 only
    ("h563_", ["-mcpu=cortex-m33", "-DSTM32H5"], "_h563",
     ("bootloader_bug_self_lock", "bootloader_bug_watchdog", "bootloader_bug_nwrite",
      "bootloader_bug_boot_loop",
      "bootloader_ext", "bootloader_ext_bug_consume_first", "bootloader_ee",
      "bootloader_ee_bug_no_invalidate", "bootloader_bug_no_ecc_nmi",
     "bootloader_standby", "bootloader_bug_standby_ram")),
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
    "bootloader_bug_watchdog": ["-DBUG_WATCHDOG"],
    "bootloader_bug_early_unpg": ["-DBUG_EARLY_UNPG"],
    "bootloader_bug_nwrite": ["-DBUG_NWRITE"],
    "bootloader_bug_boot_loop": ["-DBUG_BOOT_LOOP"],    # the nRF52840 only
    "bootloader_hold_pg": ["-DHOLD_PG"],        # not a bug: PG held over a run of cells
    # not bugs: the staged image and the rollback floor in an external SPI NOR flash chip
    "bootloader_ext": ["-DEXT_FLASH"],
    "bootloader_ext_bug_consume_first": ["-DEXT_FLASH", "-DBUG_CONSUME_FIRST"],
    # not a bug: the rollback floor in an I2C EEPROM
    "bootloader_ee": ["-DEEPROM_FLOOR"],
    "bootloader_ee_bug_no_invalidate": ["-DEEPROM_FLOOR", "-DBUG_EE_NO_INVALIDATE"],
    # an ECC error's NMI left to the default handler (the L4 only)
    "bootloader_bug_no_ecc_nmi": ["-DBUG_NO_ECC_NMI"],
    # not a bug: an install paused once in Standby (the F1 and the F4); and its bug
    "bootloader_standby": ["-DSTANDBY_PAUSE"],
    "bootloader_bug_standby_ram": ["-DSTANDBY_PAUSE", "-DBUG_STANDBY_RAM"],
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
    names = ["meta_floor1.bin", "meta_floor1_seq2.bin"]
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
    # and one that has been updated before: both floor records written, the newer second
    with open(os.path.join(HERE, out, "meta_floor1_seq2.bin"), "wb") as f:
        f.write(floor_record(2, 1))


if __name__ == "__main__":
    build("build")
    if "--prebuilt" in sys.argv:
        dst = os.path.join(HERE, "prebuilt")
        os.makedirs(dst, exist_ok=True)
        for name in outputs():
            shutil.copyfile(os.path.join(HERE, "build", name), os.path.join(dst, name))
    print("built into", os.path.join(HERE, "build"))
