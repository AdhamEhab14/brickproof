"""tools/torn_fit.py: the measured torn shapes in torn.py come out of the committed results."""
import importlib.util
import os

from brickproof import torn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "hardware", "torn_f103", "results", "nucleo-f103rb-v2.txt")


def load_tool():
    spec = importlib.util.spec_from_file_location("torn_fit", os.path.join(ROOT, "tools", "torn_fit.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def results():
    with open(RESULTS, encoding="utf-8") as f:
        return load_tool().parse(f)


def test_the_measured_shapes_in_torn_py_are_what_the_board_gave():
    tool, data = load_tool(), results()
    _, early = tool.still_zero_at(data["erase"], 0)
    _, late = tool.still_zero_at(data["erase"], 15)
    assert round(early, 3) == torn.ERASE_MEASURED["erase-early"]
    assert round(late, 4) == torn.ERASE_MEASURED["erase-late"]


def test_each_bit_stays_zero_on_its_own():
    # the share of bytes showing a 0 is what the bit share predicts for independent bits
    for _delay, _share, left, predicted in load_tool().erase_rows(results()["erase"]):
        assert abs(left - predicted) < 0.01


def test_a_program_was_never_seen_half_done():
    last, first, other = load_tool().program_edges(results()["program"])
    assert (last, first, other) == (4, 5, [])      # 0.5 us untouched, 0.625 us complete


def test_parse_reads_every_kind_of_line():
    data = load_tool().parse([
        "CAL erase_cycles=176154 program_cycles=441",
        "E 0 0 r0 704 7817 xx#x H 0,1 B 0xFF",
        "E 0 0 r1 1024 8192 ####",
        "P 3 3 r0 0xFFFF 0xFFFF",
        "noise",
    ])
    assert data["cal"] == {"erase_cycles": 176154, "program_cycles": 441}
    assert data["erase"] == {0: [(704, 7817), (1024, 8192)]}
    assert data["program"] == {3: [0xFFFF]}
