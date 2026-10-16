"""nRF52 flash in the trace: the UICR after the code area, ERASEALL wiping both, and partial
erase (ERASEPAGEPARTIAL) adding up to a page erase."""
from brickproof import trace as traces
from brickproof.engine.session import FlashGeometry

PAGE = 0x1000
UICR = 0x10001000
FLASH = FlashGeometry(base=0x0, size=4 * PAGE, page=PAGE, write_unit=4, ob_base=UICR,
                      option_bytes=bytes([0xFF]) * 0x400, mass_erase_ob=True, endurance=10000)


def image(fill=0x00):
    return bytes([fill]) * (4 * PAGE) + bytes([fill]) * 0x400


def test_eraseall_wipes_the_uicr_too():
    ops = [{"index": 0, "kind": "mass_erase", "addr": 0x0}]
    assert traces.Replay(image(), ops, FLASH).at(1) == bytes([0xFF]) * (4 * PAGE + 0x400)
    # and a word written to the UICR before it reads as erased again
    ops = [{"index": 0, "kind": "program", "addr": UICR + 0x304, "value": 5, "size": 4},
           {"index": 1, "kind": "mass_erase", "addr": 0x0},
           {"index": 2, "kind": "program", "addr": UICR + 0x304, "value": 4, "size": 4}]
    assert traces.value_before(ops, 2, image(), FLASH) == 0xFFFFFFFF


def test_an_stm32_mass_erase_keeps_its_option_bytes():
    f1 = FlashGeometry(base=0x08000000, size=4 * 0x400, page=0x400, ob_base=0x1FFFF800,
                       option_bytes=bytes(16))
    out = traces.Replay(bytes(4 * 0x400 + 16), [{"index": 0, "kind": "mass_erase", "addr": 0x08000000}],
                        f1).at(1)
    assert out[-16:] == bytes(16)


def test_erasing_the_uicr_wipes_all_of_it():
    assert traces.locate(UICR + 0x208, FLASH) == (4 * PAGE + 0x208, 0x400)
    ops = [{"index": 0, "kind": "erase", "addr": UICR}]
    out = traces.Replay(image(), ops, FLASH).at(1)
    assert out[4 * PAGE:] == bytes([0xFF]) * 0x400 and out[:4 * PAGE] == bytes(4 * PAGE)


def test_partial_erase_only_turns_bits_on_and_finishes_at_the_page_erase_time():
    page = bytes((i * 37) & 0xFF for i in range(PAGE))
    steps = [traces.partially_erased(page, t) for t in (0, 10000, 40000, 70000, 85000)]
    assert steps[0] == page
    for before, after in zip(steps, steps[1:], strict=False):
        assert all(a & b == b for a, b in zip(after, before, strict=True)), "a 1 went back to 0"
    ones = [sum(bin(b).count("1") for b in s) for s in steps]
    assert ones == sorted(ones) and ones[1] < ones[2] < ones[3]
    assert steps[-1] == bytes([0xFF]) * PAGE
    assert steps[3] != steps[-1]                    # 70 of 85 ms: some bits still 0


def test_replay_of_partial_erases():
    pre = image()
    ops = [{"index": i, "kind": "partial_erase", "addr": PAGE, "total_us": 10000 * (i + 1)}
           for i in range(9)]
    r = traces.Replay(pre, ops, FLASH)
    assert r.at(3)[PAGE:2 * PAGE] == traces.partially_erased(bytes(PAGE), 30000)
    assert r.at(9)[PAGE:2 * PAGE] == bytes([0xFF]) * PAGE
    assert r.at(9)[:PAGE] == bytes(PAGE) and r.at(9)[2 * PAGE:] == pre[2 * PAGE:]
    # a program after part of an erase starts from what the partial erases left
    ops2 = ops[:2] + [{"index": 2, "kind": "program", "addr": PAGE + 8, "value": 0, "size": 4}]
    want = int.from_bytes(traces.partially_erased(bytes(PAGE), 20000)[8:12], "little")
    assert traces.value_before(ops2, 2, pre, FLASH) == want


def test_partial_erases_wear_the_page_once_they_add_up():
    ops = [{"index": i, "kind": "partial_erase", "addr": PAGE, "total_us": 10000 * (i + 1)}
           for i in range(9)]
    c = traces.cost(ops, FLASH)
    assert c["erases"] == 1 and c["most_erased"]["addr"] == PAGE
