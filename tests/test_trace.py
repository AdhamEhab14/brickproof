import json

from brickproof import trace as traces
from brickproof.engine.session import FlashGeometry

PAGE = 0x400


def op(i, kind, addr, **extra):
    return dict(index=i, kind=kind, addr=addr, **extra)


def copy(first_index, start, n):
    return [op(first_index + k, "program", start + 2 * k, value=k) for k in range(n)]


def test_a_sequential_copy_is_one_phase():
    ops = [op(0, "erase", 0x08002000)] + copy(1, 0x08002200, 150)
    ph = traces.phases(ops, PAGE)
    assert [(p.first, p.last, p.kind, p.count) for p in ph] == [(0, 0, "erase", 1), (1, 150, "program", 150)]
    assert (ph[1].start, ph[1].end) == (0x08002200, 0x08002200 + 2 * 149)


def test_erases_group_page_by_page():
    ops = [op(i, "erase", 0x08004000 + i * PAGE) for i in range(40)]
    ph = traces.phases(ops, PAGE)
    assert len(ph) == 1 and ph[0].count == 40 and ph[0].end == 0x08004000 + 39 * PAGE


def test_a_jump_in_address_starts_a_new_phase():
    # body first, then the header in front of it: two phases, though both are programs
    ops = copy(0, 0x08002200, 4) + copy(4, 0x08002000, 2)
    assert [(p.first, p.last) for p in traces.phases(ops, PAGE)] == [(0, 3), (4, 5)]


def test_rewriting_the_same_address_is_not_a_run():
    ops = [op(0, "program", 0x08010000, value=0), op(1, "program", 0x08010000, value=0)]
    assert len(traces.phases(ops, PAGE)) == 2


def test_the_write_unit_sets_the_program_step():
    ops = [op(k, "program", 0x08000000 + 4 * k, value=0) for k in range(3)]
    assert len(traces.phases(ops, PAGE, unit=4)) == 1
    assert len(traces.phases(ops, PAGE, unit=2)) == 3


def test_describe_shows_single_and_ranged_phases():
    ops = [op(0, "erase", 0x0801E400)] + copy(1, 0x0801E400, 6)
    lines = traces.describe(ops, PAGE)
    assert lines[0].split() == ["op", "0", "erase", "1", "0x0801E400"]
    assert lines[1].split() == ["ops", "1-6", "program", "6", "0x0801E400", "..", "0x0801E40A"]


def test_jsonl_is_one_readable_operation_per_line(tmp_path):
    ops = [op(0, "erase", 0x08002000), op(1, "program", 0x08002200, value=0x5000),
           op(2, "program", 0x08002202, inferred=True)]
    path = tmp_path / "t.jsonl"
    traces.write_jsonl(ops, str(path))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows == [
        {"index": 0, "kind": "erase", "addr": "0x08002000"},
        {"index": 1, "kind": "program", "addr": "0x08002200", "value": "0x5000"},
        {"index": 2, "kind": "program", "addr": "0x08002202", "inferred": True},
    ]


def test_an_empty_trace_has_no_phases():
    assert traces.phases([], PAGE) == [] and traces.describe([], PAGE) == []


GEOMETRY = FlashGeometry(base=0x08000000, size=0x4000, page=PAGE)


def test_value_before_comes_from_the_page_erase():
    ops = [op(0, "erase", 0x08002000)] + copy(1, 0x08002200, 3)
    pre = bytes([0xAB]) * 0x4000
    assert traces.value_before(ops, 2, pre, GEOMETRY) == 0xFFFF


def test_value_before_comes_from_an_earlier_program_of_the_same_halfword():
    # the staged magic is written once, then cleared to 0 later
    ops = [op(0, "erase", 0x08002000), op(1, "program", 0x08002000, value=0x4250),
           op(2, "program", 0x08002000, value=0x0000)]
    assert traces.value_before(ops, 2, bytes(0x4000), GEOMETRY) == 0x4250


def test_value_before_falls_back_to_the_image_before_the_update():
    # clearing a magic that was in flash before the update began: no erase, no earlier program
    pre = bytearray(b"\xFF" * 0x4000)
    pre[0x2000:0x2002] = b"\x50\x42"
    ops = [op(0, "erase", 0x08001000), op(1, "program", 0x08002000, value=0)]
    assert traces.value_before(ops, 1, bytes(pre), GEOMETRY) == 0x4250


def test_an_erase_of_another_page_does_not_count():
    pre = bytearray(b"\xFF" * 0x4000)
    pre[0x2400:0x2402] = b"\x34\x12"
    ops = [op(0, "erase", 0x08002000), op(1, "program", 0x08002400, value=0)]
    assert traces.value_before(ops, 1, bytes(pre), GEOMETRY) == 0x1234


# ---- option bytes sit after the flash in an image ----------------------------------

WITH_OB = FlashGeometry(base=0x08000000, size=0x4000, page=PAGE, ob_base=0x1FFFF800,
                        option_bytes=bytes([0xA5, 0x5A] + [0xFF, 0x00] * 7))


def image_with_ob():
    return bytes(0x4000) + WITH_OB.option_bytes


def test_an_option_byte_address_is_located_after_the_flash():
    assert traces.locate(0x08000400, WITH_OB) == (0x400, PAGE)
    assert traces.locate(0x1FFFF800, WITH_OB) == (0x4000, 16)
    assert traces.locate(0x1FFFF808, WITH_OB) == (0x4008, 16)
    assert traces.erase_start(0x1FFFF80A, WITH_OB) == 0x1FFFF800
    assert traces.erase_start(0x08000456, WITH_OB) == 0x08000400


def test_replay_applies_option_byte_operations():
    ops = [op(0, "erase", 0x1FFFF800), op(1, "program", 0x1FFFF800, value=0x5AA5),
           op(2, "program", 0x1FFFF808, value=0x03FC)]
    r = traces.Replay(image_with_ob(), ops, WITH_OB)
    assert bytes(r.at(1))[0x4000:] == bytes([0xFF]) * 16, "erasing them wipes all sixteen"
    assert bytes(r.at(1))[:0x4000] == bytes(0x4000), "and leaves the flash alone"
    done = bytes(r.at(3))
    assert done[0x4000:0x4002] == bytes([0xA5, 0x5A]) and done[0x4008:0x400A] == bytes([0xFC, 0x03])


def test_value_before_for_an_option_byte():
    ops = [op(0, "erase", 0x1FFFF800), op(1, "program", 0x1FFFF800, value=0x5AA5)]
    assert traces.value_before(ops, 1, image_with_ob(), WITH_OB) == 0xFFFF
    assert traces.value_before(ops, 0, image_with_ob(), WITH_OB) == 0x5AA5, "from the image before"


def test_a_mass_erase_does_not_touch_the_option_bytes():
    ops = [op(0, "mass_erase", 0x08000000)]
    done = bytes(traces.Replay(image_with_ob(), ops, WITH_OB).at(1))
    assert done[:0x4000] == bytes([0xFF]) * 0x4000 and done[0x4000:] == WITH_OB.option_bytes


def test_protected_and_refused_operations_change_nothing_in_a_replay():
    ops = [op(0, "protected", 0x08000400), op(1, "refused", 0x08000000, value=1, old=2)]
    assert bytes(traces.Replay(image_with_ob(), ops, WITH_OB).at(2)) == image_with_ob()
