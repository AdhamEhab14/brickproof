"""Reading and writing the device's memories: words, whole flash images, the external
flash chip and the EEPROM, and comparing what is there with what should be."""
import os
import re
from brickproof.engine.flash_regs import (ECC_MAP,
    EXPECT_BASE,
    REG_CMP_FROM,
    REG_CMP_LEN,
    REG_COMPARE,
    REG_ECC_BROKEN,
    REG_RESYNC)
from brickproof.engine.geometry import EXT_STATUS_BYTES




class Memory:
    """One part of RenodeSession (engine/session.py): what the module docstring says."""

    def read_word(self, addr):
        return self.read_words([addr])[0]

    def read_unit(self, addr, size):
        """`size` bytes at addr as a number, least significant byte first."""
        return int.from_bytes(self.read_bytes(addr, size), "little")

    def write_unit(self, addr, value, size, name="unit.bin"):
        """Change `size` bytes of flash from outside, and tell the flash model."""
        if self.flash.external(addr):
            self.ext_load(value.to_bytes(size, "little"), addr - self.flash.ext_base, name)
            return
        if self.flash.eeprom(addr):
            self.ee_load(value.to_bytes(size, "little"), addr - self.flash.eeprom_base, name)
            return
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(value.to_bytes(size, "little"))
        self.cmd_batch(["sysbus LoadBinary @%s 0x%X" % (name, addr), self._set(REG_RESYNC, 1)])

    def write_word(self, addr, value):
        self.cmd("sysbus WriteDoubleWord 0x%X 0x%X" % (addr, value))

    def load_binary(self, rel_path, addr):
        """Put a file straight into memory. Path is relative to the work folder. The
        flash model is told, in case the file went into flash."""
        if self.flash.external(addr):
            self.cmd('%s LoadAt "%s" 0x%X' % (self._ext, self._path(rel_path), addr - self.flash.ext_base))
            return
        if self.flash.eeprom(addr):
            self.cmd('%s LoadAt "%s" 0x%X' % (self._ee, self._path(rel_path), addr - self.flash.eeprom_base))
            return
        self.cmd_batch(["sysbus LoadBinary @%s 0x%X" % (rel_path, addr), self._set(REG_RESYNC, 1)])

    @property
    def _ext(self):
        return "sysbus.%s.extflash" % self.flash.ext_bus

    def _path(self, name):
        """A work-folder file as the chip model wants it: a full path with forward slashes."""
        return os.path.abspath(os.path.join(self.workdir, name)).replace("\\", "/")

    @property
    def _ee(self):
        return "sysbus.%s.eeprom" % self.flash.eeprom_bus

    def ee_dump(self, name="ee_dump.bin"):
        """Everything in the I2C EEPROM."""
        self.cmd('%s SaveTo "%s"' % (self._ee, self._path(name)))
        with open(os.path.join(self.workdir, name), "rb") as f:
            return f.read()

    def ee_load(self, data, offset=0, name="ee_load.bin"):
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        self.cmd('%s LoadAt "%s" 0x%X' % (self._ee, self._path(name), offset))

    def ee_mismatch(self, data, offset=0, name="ee_expect.bin"):
        """First address where the EEPROM differs from `data` laid at `offset`, or None."""
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        reply = self.cmd('%s Mismatch "%s" 0x%X' % (self._ee, self._path(name), offset))
        found = re.findall(r"0x[0-9A-Fa-f]+|-?\d+", reply.split(name)[-1])
        at = int(found[-1], 0) if found else -1
        if at >= 1 << 62:
            at = -1
        return None if at < 0 else self.flash.eeprom_base + at

    def ext_dump(self, name="ext_dump.bin"):
        """Everything in the external flash chip."""
        self.cmd('%s SaveTo "%s"' % (self._ext, self._path(name)))
        with open(os.path.join(self.workdir, name), "rb") as f:
            return f.read()

    def ext_status(self):
        """The external chip's status registers as stored: 1 | 2 << 8 | 3 << 16."""
        reply = self.cmd("%s GetStatus" % self._ext)
        return int(re.findall(r"^\s*(0x[0-9A-Fa-f]+|\d+)\s*$", reply, re.M)[-1], 0)

    def ext_load(self, data, offset=0, name="ext_load.bin"):
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        self.cmd('%s LoadAt "%s" 0x%X' % (self._ext, self._path(name), offset))

    def ext_mismatch(self, data, offset=0, name="ext_expect.bin"):
        """First address where the chip differs from `data` laid at `offset`, or None."""
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        reply = self.cmd('%s Mismatch "%s" 0x%X' % (self._ext, self._path(name), offset))
        # the answer is the last number on the reply's own line: 0x... or -1 (as 0xFFFF...)
        found = re.findall(r"0x[0-9A-Fa-f]+|-?\d+", reply.split(name)[-1])
        at = int(found[-1], 0) if found else -1
        if at >= 1 << 62:
            at = -1
        return None if at < 0 else self.flash.ext_base + at

    def read_bytes(self, addr, n):
        """n bytes of memory. Slow, about 100 ms per KB: it comes back as text."""
        if self.flash.external(addr):
            off = addr - self.flash.ext_base
            return self.ext_dump()[off:off + n]
        if self.flash.eeprom(addr):
            off = addr - self.flash.eeprom_base
            return self.ee_dump()[off:off + n]
        out = self.cmd("sysbus ReadBytes 0x%X 0x%X" % (addr, n), timeout=600)
        out = out[out.find("["):]
        data = bytes(int(t, 16) for t in re.findall(r"0x[0-9A-Fa-f]{2}", out))
        if len(data) != n:
            raise RuntimeError("read of 0x%X bytes at 0x%X returned %d" % (n, addr, len(data)))
        return data

    def dump_flash(self):
        """The whole flash image as bytes: the flash, then the option bytes if the chip
        has them (slow: a few seconds for 128 KB)."""
        image = self.read_bytes(self.flash.base, self.flash.size)
        if self.flash.ob_size:
            image += self.read_bytes(self.flash.ob_base, self.flash.ob_size)
        if self.flash.ext_size:
            image += self.ext_dump() + self.ext_status().to_bytes(EXT_STATUS_BYTES, "little")
        if self.flash.eeprom_size:
            image += self.ee_dump()
        if self.flash.ecc:
            image += self.ecc_map()
        return image

    def ecc_map(self):
        """The ECC map: all sound unless the flash model counts a broken double word, and
        only then read back (128 KB of it takes a while)."""
        if not self.read_word(self._ctl(REG_ECC_BROKEN)):
            return bytes(self.flash.ecc_size)
        return self.read_bytes(ECC_MAP, self.flash.ecc_size)

    def restore_flash(self, data, name="flash_restore.bin"):
        """Replace the whole flash with `data` and forget what the flash checks had seen.
        Renode snapshots crash with Python peripherals, so this is how a run goes back
        to a known state."""
        f = self.flash
        with open(os.path.join(self.workdir, name), "wb") as out:
            out.write(data[:f.size])
        lines = ["sysbus LoadBinary @%s 0x%X" % (name, f.base)]
        if f.ob_size and len(data) > f.size:
            with open(os.path.join(self.workdir, "ob_" + name), "wb") as out:
                out.write(data[f.size:f.size + f.ob_size])
            lines.append("sysbus LoadBinary @ob_%s 0x%X" % (name, f.ob_base))
        if f.ecc:
            # before the resync, which counts what is broken in it
            ecc = data[f.ecc_offset:f.ecc_offset + f.ecc_size]
            with open(os.path.join(self.workdir, "ecc_" + name), "wb") as out:
                out.write(ecc if len(ecc) == f.ecc_size else bytes(f.ecc_size))
            lines.append("sysbus LoadBinary @ecc_%s 0x%X" % (name, ECC_MAP))
        self.cmd_batch(lines + [self._set(REG_RESYNC, 1)] + self._clear_checks())
        inner = f.size + f.ob_size
        if f.ext_size and len(data) > inner:
            self.ext_load(data[inner:inner + f.ext_size])
        status = data[inner + f.ext_size:inner + f.ext_size + EXT_STATUS_BYTES]
        if f.ext_size and len(status) == EXT_STATUS_BYTES:
            self.cmd("%s SetStatus 0x%X" % (self._ext, int.from_bytes(status, "little")))
        if f.eeprom_size and len(data) > f.eeprom_offset:
            self.ee_load(data[f.eeprom_offset:f.eeprom_offset + f.eeprom_size])

    def flash_mismatch(self, expected, name="flash_expect.bin"):
        """First address where flash differs from `expected` (a whole-flash image), or
        None. The comparison runs inside the flash model, on the whole flash: loading
        a file is fast, reading memory back as text is not."""
        f = self.flash
        addr = self.image_mismatch(expected[:f.size], f.base, name, whole=True)
        if addr is None and f.ob_size and len(expected) > f.size:
            now = self.read_bytes(f.ob_base, f.ob_size)
            for i in range(f.ob_size):
                if now[i] != expected[f.size + i]:
                    return f.ob_base + i
        inner = f.size + f.ob_size
        if addr is None and f.ext_size and len(expected) > inner:
            addr = self.ext_mismatch(expected[inner:inner + f.ext_size])
        if addr is None and f.eeprom_size and len(expected) > f.eeprom_offset:
            addr = self.ee_mismatch(expected[f.eeprom_offset:f.eeprom_offset + f.eeprom_size])
        if addr is None and f.ecc and len(expected) > f.ecc_offset:
            want = expected[f.ecc_offset:f.ecc_offset + f.ecc_size]
            now = self.ecc_map()
            for i in range(min(len(want), len(now))):
                if want[i] != now[i]:
                    return f.base + 8 * i          # the double word whose ECC differs
        return addr

    def image_mismatch(self, data, addr, name="image_expect.bin", whole=False):
        """First address where flash at `addr` differs from `data`, or None if that
        image is exactly what is there."""
        if self.flash.external(addr):
            return self.ext_mismatch(data, addr - self.flash.ext_base)
        if self.flash.eeprom(addr):
            return self.ee_mismatch(data, addr - self.flash.eeprom_base)
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        reply = self.cmd_batch(
            ["sysbus LoadBinary @%s 0x%X" % (name, addr - self.flash.base + EXPECT_BASE),
             self._set(REG_CMP_FROM, addr), self._set(REG_CMP_LEN, 0 if whole else len(data)),
             self._set(REG_COMPARE, 1), self._get(REG_COMPARE)])
        return self._values(reply)[-1] or None
