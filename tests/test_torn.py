"""Torn states: shapes of a half-done erase or program that obey what flash cells do."""
from types import SimpleNamespace

import pytest

from brickproof import adapter as adapters
from brickproof import runner
from brickproof import torn
from brickproof.engine.session import FlashGeometry
from fake_device import MARKER, SLOT, FakeDevice, FakeDriver

BASE = 0x08000000
PAGE = 0x400
FLASH = FlashGeometry(base=BASE, size=4 * PAGE, page=PAGE)


def image_with(page_bytes):
    return bytes([0xFF]) * PAGE + bytes(page_bytes) + bytes([0xFF]) * (2 * PAGE)


def used_page():
    return bytes((i * 7 + 3) & 0xFF for i in range(PAGE))


ERASE = {"index": 5, "kind": "erase", "addr": BASE + PAGE}


def page_of(state):
    return state.image[PAGE:2 * PAGE]


def test_a_torn_erase_only_ever_turns_bits_on():
    old = used_page()
    states = torn.states(ERASE, image_with(old), FLASH)
    assert [s.kind for s in states] == list(torn.ERASE_KINDS)
    for s in states:
        new = page_of(s)
        assert all(n & o == o for n, o in zip(new, old, strict=True)), "a 1 bit went back to 0"
        assert new != old and new != bytes([0xFF]) * PAGE, "must be strictly between before and after"
        assert s.image[:PAGE] == bytes([0xFF]) * PAGE and len(s.image) == FLASH.size
        assert (s.op_index, s.addr) == (5, BASE + PAGE)


def test_the_erase_shapes_are_what_their_names_say():
    old = used_page()
    by_kind = {s.kind: page_of(s) for s in torn.states(ERASE, image_with(old), FLASH)}
    half = by_kind["erase-half"]
    assert half[:PAGE // 2] == bytes([0xFF]) * (PAGE // 2) and half[PAGE // 2:] == old[PAGE // 2:]
    almost = by_kind["erase-almost"]
    assert sum(1 for b in almost if b != 0xFF) <= PAGE // 64 + 1
    partial = by_kind["erase-partial"]
    assert partial not in (half, almost)


def test_erasing_an_erased_page_has_no_torn_state():
    assert torn.states(ERASE, image_with([0xFF] * PAGE), FLASH) == []


def program(value, index=9, addr=BASE + PAGE):
    return {"index": index, "kind": "program", "addr": addr, "value": value}


def halfword(state, addr=BASE + PAGE):
    off = addr - BASE
    return state.image[off] | (state.image[off + 1] << 8)


def test_a_torn_program_only_clears_bits_the_target_clears():
    before = image_with([0xFF] * PAGE)
    states = torn.states(program(0x1234), before, FLASH)
    assert {s.kind for s in states} <= set(torn.PROGRAM_KINDS) and states
    for s in states:
        v = halfword(s)
        assert v & 0x1234 == 0x1234, "cleared a bit the finished value keeps"
        assert v not in (0xFFFF, 0x1234), "must be strictly between before and after"
    by_kind = {s.kind: halfword(s) for s in states}
    assert by_kind["program-low"] == 0xFF34 and by_kind["program-high"] == 0x12FF


def test_a_torn_program_over_existing_data_starts_from_that_data():
    # clearing a magic to 0 (allowed without an erase): torn = some of its bits gone
    page = bytearray([0xFF] * PAGE)
    page[0:2] = b"\x50\x42"
    for s in torn.states(program(0x0000), image_with(page), FLASH):
        v = halfword(s)
        assert v & ~0x4250 & 0xFFFF == 0, "set a bit that was already 0"
        assert v not in (0x4250, 0x0000)


def test_a_program_with_a_single_bit_to_clear_cannot_be_torn():
    assert torn.states(program(0xFFFE), image_with([0xFF] * PAGE), FLASH) == []


def test_programs_that_changed_nothing_or_were_refused_have_no_torn_state():
    before = image_with([0xFF] * PAGE)
    inferred = {"index": 1, "kind": "program", "addr": BASE, "inferred": True}
    refused = {"index": 1, "kind": "refused", "addr": BASE, "value": 1, "old": 2}
    assert torn.states(inferred, before, FLASH) == [] and torn.states(refused, before, FLASH) == []


def test_the_same_seed_gives_the_same_states_and_another_seed_others():
    before = image_with(used_page())
    a = [s.image for s in torn.states(ERASE, before, FLASH, seed=1)]
    assert a == [s.image for s in torn.states(ERASE, before, FLASH, seed=1)]
    assert a != [s.image for s in torn.states(ERASE, before, FLASH, seed=2)]


def test_kinds_can_be_limited():
    states = torn.states(ERASE, image_with(used_page()), FLASH, kinds=["erase-half"])
    assert [s.kind for s in states] == ["erase-half"]


# ---- in a campaign ---------------------------------------------------------------

def run(device, kinds=torn.KINDS, **kw):
    ad = SimpleNamespace(flash=device.flash, check_states=True, cut_limit=0.03, update_time=1.0,
                         boot_settle=0.1, cuts=[], plan={"mode": "every"}, torn=list(kinds), torn_seed=0)
    return runner.campaign(device, FakeDriver(device), ad, **kw)


def test_a_correct_updater_survives_its_torn_states():
    out = run(FakeDevice())
    torn_results = [r for r in out.results if r.torn]
    assert torn_results and all(r.passed for r in torn_results)
    # the erase of the slot, the eight data halfwords, the marker clear
    assert {r.op_index for r in torn_results} == set(range(10))
    kinds = {r.torn for r in torn_results}
    # the slot's old image sits in the first few bytes of its page, so "half" and
    # "almost" erased are the same as fully erased here, and are rightly left out
    assert "erase-partial" in kinds and "program-partial" in kinds
    assert "erase-half" not in kinds
    clean = [r for r in out.results[1:] if not r.torn]
    assert out.results.index(torn_results[0]) > out.results.index(clean[-1]), "clean cuts come first"


def test_torn_results_say_where_and_what():
    out = run(FakeDevice(), kinds=["erase-partial"])
    (r,) = [r for r in out.results if r.torn]
    assert (r.cut, r.kind, r.addr, r.op_index) == ("op-0 erase-partial", "erase-partial", SLOT, 0)


def test_a_device_that_does_not_recover_fails_its_torn_states():
    out = run(FakeDevice(no_recovery=True), kinds=["program-low"])
    torn_results = [r for r in out.results if r.torn]
    assert torn_results and not any(r.passed for r in torn_results if r.addr != MARKER)


def test_fail_fast_stops_before_the_torn_states_when_a_clean_cut_fails():
    out = run(FakeDevice(no_recovery=True), fail_fast=True)
    assert not any(r.torn for r in out.results)


def test_no_torn_states_without_the_option():
    ad = SimpleNamespace(flash=FakeDevice().flash, check_states=True, cut_limit=0.03, update_time=1.0,
                         boot_settle=0.1, cuts=[], plan={"mode": "every"})
    device = FakeDevice()
    out = runner.campaign(device, FakeDriver(device), ad)
    assert not any(r.torn for r in out.results)


# ---- from an adapter -------------------------------------------------------------

YAML = """
name: demo
target: fw
platform: {base: stm32f103}
flash: {base: 0x08000000, size: 0x10000, page: 0x400}
ram: {size: 0x5000}
firmware:
  - file: app.elf
driver: {file: driver.py}
scenario:
  plan: every
"""


def load(tmp_path, extra):
    p = tmp_path / "adapter.yaml"
    p.write_text(YAML + extra)
    return adapters.load(str(p))


def test_torn_is_off_by_default_true_means_all_and_a_list_is_kept(tmp_path):
    assert load(tmp_path, "").torn is None
    assert load(tmp_path, "  torn: true\n").torn == list(torn.KINDS)
    ad = load(tmp_path, "  torn: [erase-half, program-low]\n  torn_seed: 7\n")
    assert ad.torn == ["erase-half", "program-low"] and ad.torn_seed == 7


@pytest.mark.parametrize("bad", ["  torn: [erase-quarter]\n", "  torn: yes-please\n"])
def test_a_bad_torn_option_is_rejected(tmp_path, bad):
    with pytest.raises(adapters.AdapterError, match="torn"):
        load(tmp_path, bad)
