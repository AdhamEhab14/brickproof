"""The m33mu backend: adapters for the chips it emulates, its trace and addresses, and
(when an m33mu with the harness commands is installed) the demo run end to end."""
import os
import subprocess
import textwrap

import pytest

from brickproof import adapter as adapters
from brickproof import runner
from brickproof.engine import m33mu as m33mu_engine
from brickproof.engine.session import CUT_ERASE, CUT_PROGRAM, FlashGeometry

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(REPO, "examples", "demo_ab_bootloader")

H563 = """
name: h5
target: fw
platform: {base: stm32h563}
flash: {base: 0x0C000000, size: 0x200000}
ram: {base: 0x30000000, size: 0xA0000}
firmware:
  - file: boot.elf
uart: usart3
driver: {file: driver.py}
"""


def write(tmp_path, extra="", **replace):
    text = H563
    for k, v in replace.items():
        text = text.replace(k, v)
    p = tmp_path / "adapter.yaml"
    p.write_text(text + textwrap.dedent(extra))
    return str(p)


# ---- adapters ---------------------------------------------------------------

def test_an_m33mu_chip_loads_with_its_own_geometry(tmp_path):
    ad = adapters.load(write(tmp_path))
    assert ad.emulator == "m33mu" and ad.platform == "stm32h563"
    assert ad.flash.page == 0x2000 and ad.flash.write_unit == 16 and ad.flash.ob_base is None
    assert ad.uart == 0x40004800 and ad.optbytes == {} and ad.reset_cmds == []


def test_renode_chips_keep_renode(tmp_path):
    ad = adapters.load(os.path.join(DEMO, "f411.yaml"))
    assert ad.emulator == "renode" and ad.optbytes == {}


def test_write_protection_becomes_the_wrpsg_option_bytes(tmp_path):
    ad = adapters.load(write(tmp_path, """
        flash:
          base: 0x0C000000
          size: 0x200000
          write_protected:
            - {from: 0x0C000000, size: 0x8000}      # bank 1, group 0
            - {from: 0x0C010000, size: 0x10000}     # bank 1, groups 2 and 3
            - {from: 0x0C1F8000, size: 0x8000}      # bank 2, group 31
        """))
    assert ad.optbytes == {"WRPSG1": 0xFFFFFFF2, "WRPSG2": 0x7FFFFFFF}


def test_write_protection_must_cover_whole_groups(tmp_path):
    with pytest.raises(adapters.AdapterError, match="whole groups of 0x8000"):
        adapters.load(write(tmp_path, """
            flash:
              base: 0x0C000000
              size: 0x200000
              write_protected:
                - {from: 0x0C000000, size: 0x2000}
            """))


def test_option_bytes_are_given_by_name(tmp_path):
    ad = adapters.load(write(tmp_path, "option_bytes: {SWAP_BANK: 0, SECWM1: 0x007F0000}\n"))
    assert ad.optbytes == {"SWAP_BANK": 0, "SECWM1": 0x007F0000}


def test_option_bytes_and_write_protection_cannot_both_set_one(tmp_path):
    with pytest.raises(adapters.AdapterError, match="both set it"):
        adapters.load(write(tmp_path, """
            option_bytes: {WRPSG1: 0}
            flash:
              base: 0x0C000000
              size: 0x200000
              write_protected:
                - {from: 0x0C000000, size: 0x8000}
            """))


def test_option_bytes_are_for_m33mu_chips_only(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text(open(os.path.join(DEMO, "f411.yaml")).read() + "option_bytes: {WRPSG1: 0}\n")
    with pytest.raises(adapters.AdapterError, match="only for chips m33mu emulates"):
        adapters.load(str(p))


@pytest.mark.parametrize("extra, key", [
    ("reset: [gpioPortC OnGPIO 13 false]\n", "reset"),
    ("pins: {PC13: high}\n", "pins"),
    ("clock: {hse: 8000000}\n", "clock"),
    ("cpu: {mips: 100}\n", "cpu.mips"),
    ("external_flash: {bus: spi1, cs: PA4, size: 0x100000}\n", "external_flash"),
])
def test_renode_only_keys_are_refused(tmp_path, extra, key):
    with pytest.raises(adapters.AdapterError, match="^%s: " % key.replace(".", r"\.")):
        adapters.load(write(tmp_path, extra))


@pytest.mark.parametrize("replace, match", [
    ({"size: 0x200000": "size: 0x100000"}, "flash.size: stm32h563 has 0x200000"),
    ({"base: 0x0C000000": "base: 0x08004000"}, "flash.base: stm32h563 flash is at"),
    ({"size: 0xA0000": "size: 0x50000"}, "ram.size: stm32h563 has 0xA0000"),
    ({"uart: usart3": "uart: usart99"}, "uart: stm32h563 has"),
])
def test_the_chip_is_described_as_it_is(tmp_path, replace, match):
    with pytest.raises(adapters.AdapterError, match=match):
        adapters.load(write(tmp_path, **replace))


def test_a_uart_can_be_given_by_address(tmp_path):
    assert adapters.load(write(tmp_path, **{"uart: usart3": "uart: 0x40013800"})).uart == 0x40013800


# ---- the session's side of the protocol ---------------------------------------

class StubGdb:
    def __init__(self, replies):
        self.replies = replies
        self.sent = []

    def monitor(self, text, timeout=60):
        self.sent.append(text)
        return self.replies.get(text.split()[0] + " " + text.split()[1] if " " in text else text, "")


def session_with(tmp_path, base=0x08000000, replies=None):
    """A session that never started an emulator: just enough to test its parsing."""
    s = m33mu_engine.M33muSession.__new__(m33mu_engine.M33muSession)
    s.workdir = str(tmp_path)
    s.flash = FlashGeometry(base=base, size=0x200000, page=0x2000, write_unit=16)
    s.mbase = 0x0C000000
    s.gdb = StubGdb(replies or {})
    return s


def test_the_trace_is_read_at_the_adapters_address(tmp_path):
    s = session_with(tmp_path)
    (tmp_path / "trace.txt").write_text(
        "E 0x0C010000 #2000 @2000\n"
        "E 0x0C100000 #100000 @256000\n"
        "P 0x0C010200 0x11223344 @31\n"
        "X 0x0C010200 0x00000000 0x11223344\n"
        "W 0x0C000000\n"
        "M 0x0C000000 @512000\n")
    ops = s.trace_stop()
    assert [o["kind"] for o in ops] == ["erase", "erase", "program", "refused", "protected",
                                        "mass_erase"]
    assert [o["addr"] for o in ops][:3] == [0x08010000, 0x08100000, 0x08010200]
    assert "length" not in ops[0]                  # one sector: what the geometry says anyway
    assert ops[1]["length"] == 0x100000            # a bank erase says how much it took
    assert ops[2]["value"] == 0x11223344 and ops[2]["size"] == 4 and ops[2]["us"] == 31
    assert ops[3]["old"] == 0x11223344


def test_a_bank_swap_in_the_trace_is_refused(tmp_path):
    s = session_with(tmp_path)
    (tmp_path / "trace.txt").write_text("B 0x0C000000 #200000\n")
    with pytest.raises(m33mu_engine.M33muError, match="bank swap"):
        s.trace_stop()


def test_cut_status_and_violations_translate_addresses(tmp_path):
    s = session_with(tmp_path, replies={
        "flash cut": "flash cut 7 erase 0x0c010000 0x2000\n",
        "flash latches": "flash latches refused 2 0x0c010200 protected 0 0x00000000\n"})
    assert s.cut_status() == (CUT_ERASE, 0x08010000, 7)
    assert s.violations() == {"fault": None, "refused": (2, 0x08010200), "stray": None,
                              "protected": None}
    s.gdb.replies["flash cut"] = "flash cut 3 program 0x0c010200 0x4\n"
    assert s.cut_status() == (CUT_PROGRAM, 0x08010200, 3)
    s.gdb.replies["flash cut"] = "flash cut none\n"
    assert not s.cut_fired()


def test_a_cut_on_erase_is_armed_at_m33mus_address(tmp_path):
    s = session_with(tmp_path)
    s.set_cut_on_erase(0x08020000)
    assert s.gdb.sent == ["flash cut erase 0xC020000"]


# ---- end to end, with a real m33mu ----------------------------------------------

def _m33mu():
    exe = m33mu_engine.find_m33mu()
    if not exe:
        return None
    out = subprocess.run([exe, "--no-realtime"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, timeout=30).stdout
    return None if "unknown option" in out else exe


needs_m33mu = pytest.mark.skipif(_m33mu() is None, reason="no m33mu with the harness commands")


@needs_m33mu
def test_the_h563_demo_recovers_from_cuts():
    ad = adapters.load(os.path.join(DEMO, "h563.yaml"))
    ad.plan = None
    ad.cuts = [adapters.Cut(name="op-%d" % n, at_op=n) for n in (0, 2, 10, 24, 25)]
    out = runner.run(ad)
    assert out.passed, [(r.cut, r.message) for r in out.results if not r.passed]
    # one operation per 128-bit flash word: the floor record, the slot erase, 21 words
    # of app, the header, the consumed marker
    assert len(out.trace) == 26
    assert all(op.get("size", 16) == 16 for op in out.trace if op["kind"] == "program")
    cut = out.results[2]
    assert (cut.fired, cut.kind, cut.addr, cut.op_index) == (True, "erase", 0x0C010000, 2)
    assert not any(r.rewound for r in out.results)     # m33mu cuts before the operation


@needs_m33mu
def test_the_h563_demo_catches_a_bug():
    ad = adapters.load(os.path.join(DEMO, "h563-bug-consume_first.yaml"))
    ad.plan = None
    ad.cuts = [adapters.Cut(name="op-3", at_op=3)]     # Slot B consumed, Slot A erased
    out = runner.run(ad)
    assert out.results[0].passed and not out.results[1].passed
