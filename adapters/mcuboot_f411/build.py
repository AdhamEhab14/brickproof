"""Build MCUboot and the test app for the Black Pill, and sign the images the adapter uses.

    python build.py <zephyr workspace> <output folder>

The workspace is a `west init` / `west update` of Zephyr with MCUboot in it (bootloader/mcuboot).
The output folder is what `--target` points at: mcuboot.elf, app_v1.img, app_v2_staged.img
and app_v2.img.

MCUboot is built with its defaults except the signature type: ECDSA-P256 instead of RSA-2048,
which with Ubuntu's arm-none-eabi-gcc does not fit the board's 32 KB bootloader partition.
"""
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = "blackpill_f411ce"
SLOT_SIZE = 0x20000


def west(ws, *args):
    subprocess.check_call(["west"] + list(args), cwd=ws)


def sign(ws, binary, out, version, staged=False):
    key = os.path.join(ws, "bootloader", "mcuboot", "root-ec-p256.pem")
    imgtool = os.path.join(ws, "bootloader", "mcuboot", "scripts", "imgtool.py")
    cmd = [sys.executable, imgtool, "sign", "--key", key, "--header-size", "0x200",
           "--align", "4", "--slot-size", hex(SLOT_SIZE), "--version", version]
    if staged:
        cmd += ["--pad", "--confirm"]       # a trailer that asks for a permanent upgrade
    subprocess.check_call(cmd + [binary, out])


def image_end(data):
    """Where the signed image ends: header, body, then the TLV areas."""
    hdr_size = struct.unpack_from("<H", data, 8)[0]
    img_size = struct.unpack_from("<I", data, 12)[0]
    off = hdr_size + img_size
    while off + 4 <= len(data):
        magic, length = struct.unpack_from("<HH", data, off)
        if magic not in (0x6907, 0x6908):
            break
        off += length
    return off


def main():
    ws, out = (os.path.abspath(a) for a in sys.argv[1:3])
    os.makedirs(out, exist_ok=True)
    build = os.path.join(out, "build")

    west(ws, "build", "-p", "-b", BOARD, "bootloader/mcuboot/boot/zephyr",
         "-d", os.path.join(build, "mcuboot"), "--",
         "-DCONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256=y",
         '-DCONFIG_BOOT_SIGNATURE_KEY_FILE="root-ec-p256.pem"')
    shutil.copy(os.path.join(build, "mcuboot", "zephyr", "zephyr.elf"),
                os.path.join(out, "mcuboot.elf"))

    for v in (1, 2):
        west(ws, "build", "-p", "-b", BOARD, os.path.join(HERE, "app"),
             "-d", os.path.join(build, "app%d" % v), "--", "-DCMAKE_C_FLAGS=-DAPP_VERSION=%d" % v)
    app = os.path.join(build, "app%d", "zephyr", "zephyr.bin")
    sign(ws, app % 1, os.path.join(out, "app_v1.img"), "1.0.0")
    staged = os.path.join(out, "app_v2_staged.img")
    sign(ws, app % 2, staged, "2.0.0", staged=True)

    # ECDSA signatures differ every time, so the approved v2 is cut out of the staged file
    data = open(staged, "rb").read()
    with open(os.path.join(out, "app_v2.img"), "wb") as f:
        f.write(data[:image_end(data)])
    print("built into", out)


if __name__ == "__main__":
    main()
