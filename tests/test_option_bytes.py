"""Option bytes the adapter builds: PCROP and read protection level 2 on the STM32F4."""
import struct

import pytest

from brickproof import adapter as adapters
from brickproof.engine.session import FlashGeometry

F411 = FlashGeometry(base=0x08000000, size=0x80000,
                     sectors=[(0, 0x4000), (0x4000, 0x4000), (0x8000, 0x4000), (0xC000, 0x4000),
                              (0x10000, 0x10000), (0x20000, 0x20000), (0x40000, 0x20000),
                              (0x60000, 0x20000)])


def halves(ob):
    user_rdp, comp1 = struct.unpack_from("<HH", ob, 0)
    wrp, comp2 = struct.unpack_from("<HH", ob, 8)
    assert comp1 == ~user_rdp & 0xFFFF and comp2 == ~wrp & 0xFFFF
    return user_rdp, wrp


def test_plain_option_bytes_are_unchanged():
    user_rdp, wrp = halves(adapters.stm32f4_option_bytes(F411, [], 0))
    assert user_rdp == 0xAAEF and wrp == 0xFFFF


def test_pcrop_sets_sprmod_and_only_its_sectors():
    ob = adapters.stm32f4_option_bytes(F411, [], 0, pcrop=[{"from": 0x08060000, "size": 0x20000}])
    _, wrp = halves(ob)
    assert not wrp & 0x8000                     # SPRMOD = 1, stored inverted
    assert wrp & 0xFFF == 1 << 7


def test_level_2_is_0xcc():
    user_rdp, _ = halves(adapters.stm32f4_option_bytes(F411, [], 2))
    assert user_rdp >> 8 == 0xCC


def test_pcrop_and_write_protection_cannot_be_mixed():
    with pytest.raises(adapters.AdapterError, match="share the nWRP bits"):
        adapters.stm32f4_option_bytes(F411, [{"from": 0x08000000, "size": 0x4000}], 0,
                                      pcrop=[{"from": 0x08060000, "size": 0x20000}])


def test_pcrop_goes_by_whole_sectors():
    with pytest.raises(adapters.AdapterError, match="whole sectors"):
        adapters.stm32f4_option_bytes(F411, [], 0, pcrop=[{"from": 0x08060000, "size": 0x1000}])
