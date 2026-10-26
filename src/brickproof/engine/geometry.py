"""The device's flash as BrickProof sees it: where it is, how it erases and programs, and
what comes with it (option bytes, an external chip, an EEPROM, the ECC map)."""
from dataclasses import dataclass

EXT_STATUS_BYTES = 3            # an external chip's status registers 1, 2 and 3, as stored


@dataclass
class FlashGeometry:
    base: int
    size: int
    page: int = None            # the erase unit, where it is the same everywhere
    write_unit: int = 2         # bytes a program usually writes
    # where erase units differ in size (an STM32F4's sectors): [(offset, size), ...]
    sectors: list = None
    controller: int = 0x40022000
    model: str = "stm32f1_flash.py"      # the flash controller model in models/
    timing: int = 0             # how long operations take: 0 none, 1 typical, 2 slowest
    # an external SPI NOR flash chip, if the board has one. It has no address on the
    # system bus; ext_base is only how its bytes are named in traces and images.
    ext_base: int = None
    ext_size: int = 0
    ext_bus: str = ""           # the SPI controller it hangs on, for example spi1
    ext_cs: str = ""            # its chip select pin, for example PA4
    ext_sector: int = 0x1000    # its smallest erase
    ext_endurance: int = 100000
    ext_status: int = 0         # its status registers as shipped: 1 | 2 << 8 | 3 << 16
    ext_wp: str = ""            # the pin wired to its /WP, if any (otherwise /WP reads high)
    # an I2C EEPROM (24-series), if the board has one. Like the external flash it has no
    # address on the system bus; eeprom_base names its bytes in traces and images.
    eeprom_base: int = None
    eeprom_size: int = 0
    eeprom_page: int = 32       # bytes one write can cover (it wraps inside the page)
    eeprom_bus: str = ""        # the I2C controller it hangs on, for example i2c1
    eeprom_i2c: int = 0x50      # its 7-bit bus address
    eeprom_address_bytes: int = 2
    eeprom_endurance: int = 1000000
    endurance: int = 0          # erase cycles the datasheet promises per unit (0: unknown)
    # Option bytes, where the chip has them: their address, and what they hold when a
    # test starts. A flash image is then the flash followed by these bytes, so a change
    # to them is saved, restored, replayed and compared like any other.
    ob_base: int = None
    mass_erase_ob: bool = False  # a mass erase wipes the option bytes too (the nRF52's UICR)
    option_bytes: bytes = b""
    wrp_unit: int = 0x1000      # how much flash one write-protection bit covers
    worn: tuple = None          # (from, to): pages whose programs no longer take (flash.worn)
    # ECC, where the chip has it (STM32L4): every 64 bits carry their own check bits, and a
    # program or erase cut short leaves them not matching. The image ends with a map, one
    # byte per double word, 1 where that is so.
    ecc: bool = False

    def unit_at(self, addr):
        """(first address, size) of the erase unit that holds `addr`."""
        if self.sectors:
            off = addr - self.base
            for start, size in self.sectors:
                if start <= off < start + size:
                    return self.base + start, size
            raise ValueError("0x%08X is not in any flash sector" % addr)
        return self.base + (addr - self.base) // self.page * self.page, self.page

    def units(self):
        """Every erase unit, in order: [(first address, size), ...]."""
        if self.sectors:
            return [(self.base + start, size) for start, size in self.sectors]
        return [(self.base + off, self.page) for off in range(0, self.size, self.page)]

    @property
    def ob_size(self):
        return len(self.option_bytes) if self.ob_base is not None else 0

    def external(self, addr):
        return self.ext_base is not None and self.ext_base <= addr < self.ext_base + self.ext_size

    def eeprom(self, addr):
        return self.eeprom_base is not None and self.eeprom_base <= addr < self.eeprom_base + self.eeprom_size

    @property
    def eeprom_offset(self):
        # where the EEPROM starts in a flash image: after everything else
        return self.size + self.ob_size + self.ext_size + (EXT_STATUS_BYTES if self.ext_size else 0)

    @property
    def ecc_offset(self):
        return self.eeprom_offset + self.eeprom_size

    @property
    def ecc_size(self):
        return self.size // 8 if self.ecc else 0

    @property
    def image_size(self):
        # the external chip's two status registers follow its contents: they are
        # non-volatile, so a power cut leaves them as they were, like the flash
        return self.ecc_offset + self.ecc_size
