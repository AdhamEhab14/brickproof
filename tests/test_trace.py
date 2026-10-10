import json

from brickproof import trace as traces

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


FLASH = 0x08000000


def test_value_before_comes_from_the_page_erase():
    ops = [op(0, "erase", 0x08002000)] + copy(1, 0x08002200, 3)
    pre = bytes([0xAB]) * 0x4000
    assert traces.value_before(ops, 2, pre, FLASH, PAGE) == 0xFFFF


def test_value_before_comes_from_an_earlier_program_of_the_same_halfword():
    # the staged magic is written once, then cleared to 0 later
    ops = [op(0, "erase", 0x08002000), op(1, "program", 0x08002000, value=0x4250),
           op(2, "program", 0x08002000, value=0x0000)]
    assert traces.value_before(ops, 2, bytes(0x4000), FLASH, PAGE) == 0x4250


def test_value_before_falls_back_to_the_image_before_the_update():
    # clearing a magic that was in flash before the update began: no erase, no earlier program
    pre = bytearray(b"\xFF" * 0x4000)
    pre[0x2000:0x2002] = b"\x50\x42"
    ops = [op(0, "erase", 0x08001000), op(1, "program", 0x08002000, value=0)]
    assert traces.value_before(ops, 1, bytes(pre), FLASH, PAGE) == 0x4250


def test_an_erase_of_another_page_does_not_count():
    pre = bytearray(b"\xFF" * 0x4000)
    pre[0x2400:0x2402] = b"\x34\x12"
    ops = [op(0, "erase", 0x08002000), op(1, "program", 0x08002400, value=0)]
    assert traces.value_before(ops, 1, bytes(pre), FLASH, PAGE) == 0x1234
