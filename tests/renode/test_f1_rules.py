"""STM32F1 option bytes as the chip loads them at reset (RM0008, FLASH_OBR and FLASH_WRPR)."""
ADAPTER = "adapter.yaml"
FLASH_OBR = 0x4002201C
FLASH_WRPR = 0x40022020


def boot_with(chip, option_bytes):
    """Reset with these 16 option bytes (data and complement pairs), read OBR and WRPR."""
    f = chip.adapter.flash
    image = bytearray(chip.factory)
    image[f.size:f.size + 16] = option_bytes
    chip.restore_flash(bytes(image))
    chip.power_cycle(settle=0.01)
    return chip.read_words([FLASH_OBR, FLASH_WRPR])


def pairs(*data):
    out = bytearray()
    for b in data:
        out += bytes([b, b ^ 0xFF])
    return bytes(out)


def test_good_option_bytes_load_without_an_error(chip):
    # RDP unprotected, USER 0xFF, Data0 0x12, Data1 0x34, no write protection
    obr, wrpr = boot_with(chip, pairs(0xA5, 0xFF, 0x12, 0x34, 0xFF, 0xFF, 0xFF, 0xFF))
    assert obr & 1 == 0 and obr & 2 == 0               # no OPTERR, not read protected
    assert (obr >> 10) & 0xFF == 0x12 and (obr >> 18) & 0xFF == 0x34   # Data0, Data1
    assert wrpr == 0xFFFFFFFF


def test_a_wrong_complement_sets_opterr_and_the_byte_reads_as_ff(chip):
    good = bytearray(pairs(0xA5, 0xFF, 0x12, 0x34, 0xFE, 0xFF, 0xFF, 0xFF))
    obr, wrpr = boot_with(chip, bytes(good))
    assert obr & 1 == 0 and wrpr & 1 == 0              # WRP0 bit 0 cleared: page 0..3 protected
    bad = bytearray(good)
    bad[9] = 0x00                                      # WRP0's complement no longer matches
    obr, wrpr = boot_with(chip, bytes(bad))
    assert obr & 1 == 1                                # OPTERR
    assert wrpr & 0xFF == 0xFF                         # WRP0 read as 0xFF: not protected
    bad = bytearray(good)
    bad[5] = 0x00                                      # Data0's complement
    obr, _ = boot_with(chip, bytes(bad))
    assert obr & 1 == 1 and (obr >> 10) & 0xFF == 0xFF


def test_an_rdp_byte_with_a_bad_complement_means_read_protected(chip):
    obr, _ = boot_with(chip, bytes([0xA5, 0x00]) + pairs(0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF))
    assert obr & 1 == 1 and obr & 2 == 2               # OPTERR, and RDPRT


def test_erased_option_bytes_read_as_protected_with_opterr(chip):
    obr, wrpr = boot_with(chip, b"\xFF" * 16)
    assert obr & 3 == 3 and wrpr == 0xFFFFFFFF
