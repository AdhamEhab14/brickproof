"""What BrickProof can tell from a firmware file on its own, without running it.

  elf_segments(data)    the parts of an ELF file that are loaded into memory, and where
  first_words(...)      the first two words of a vector table: the initial stack pointer
                        and the reset handler
  mcuboot_layout(data)  an MCUboot image's header, body and TLV area (hash, signature),
                        read from its header, so nobody has to type its size

Only what the checks and the damaged-image tests need; nothing here is used to load
firmware (the emulator does that itself).
"""
import struct
from dataclasses import dataclass

MCUBOOT_MAGIC = 0x96F3B83D
TLV_MAGICS = (0x6907, 0x6908)       # the unprotected and the protected TLV area


@dataclass
class Segment:
    addr: int                       # where it is loaded (the physical address)
    data: bytes

    @property
    def end(self):
        return self.addr + len(self.data)


def is_elf(data):
    return data[:4] == b"\x7fELF"


def elf_segments(data):
    """The loadable segments of a 32-bit little-endian ELF file, at their load (physical)
    addresses: initialised data sits in flash there, and is copied to RAM at start-up.
    Raises ValueError for anything else."""
    if not is_elf(data):
        raise ValueError("not an ELF file")
    if data[4] != 1 or data[5] != 1:
        raise ValueError("not a 32-bit little-endian ELF file")
    phoff, = struct.unpack_from("<I", data, 28)
    phentsize, phnum = struct.unpack_from("<HH", data, 42)
    out = []
    for i in range(phnum):
        p_type, p_offset, _vaddr, p_paddr, p_filesz = struct.unpack_from(
            "<IIIII", data, phoff + i * phentsize)
        if p_type == 1 and p_filesz:            # PT_LOAD, with bytes in the file
            out.append(Segment(p_paddr, bytes(data[p_offset:p_offset + p_filesz])))
    return out


def first_words(segments, addr):
    """(initial SP, reset handler) of the vector table at `addr`, or None if no segment
    holds it."""
    for s in segments:
        if s.addr <= addr and addr + 8 <= s.end:
            return struct.unpack_from("<II", s.data, addr - s.addr)
    return None


@dataclass
class McubootLayout:
    size: int                       # header + body + TLV areas: the image itself
    header: tuple                   # (start, end) offsets in the file
    body: tuple
    tlv: tuple


def mcuboot_layout(data):
    """An MCUboot image's layout, read from its header and TLV areas; None if `data`
    does not start with an MCUboot image header. A padded image (a whole slot, with the
    trailer that asks for the update at its end) gives the size of the image in it."""
    if len(data) < 32 or struct.unpack_from("<I", data, 0)[0] != MCUBOOT_MAGIC:
        return None
    hdr_size = struct.unpack_from("<H", data, 8)[0]
    img_size = struct.unpack_from("<I", data, 12)[0]
    body_end = hdr_size + img_size
    if not 32 <= hdr_size <= body_end <= len(data):
        return None
    end = body_end
    while end + 4 <= len(data):
        magic, length = struct.unpack_from("<HH", data, end)
        if magic not in TLV_MAGICS:
            break
        end += length
    return McubootLayout(end, (0, 32), (hdr_size, body_end), (body_end, end))
