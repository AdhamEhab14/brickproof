"""Wrap a raw app binary in the demo's image format: a 16-byte header
(magic, version, size, CRC-32), padding up to 0x200, then the app.

    python mkimage.py app.bin 2 app_v2.img
"""
import struct
import sys
import zlib

IMG_MAGIC = 0x494D4250
IMG_OFFSET = 0x200


def make_image(body, version):
    header = struct.pack("<IIII", IMG_MAGIC, version, len(body), zlib.crc32(body))
    return header + b"\xFF" * (IMG_OFFSET - len(header)) + body


if __name__ == "__main__":
    src, version, dst = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    with open(src, "rb") as f:
        body = f.read()
    with open(dst, "wb") as f:
        f.write(make_image(body, version))
