"""What `brickproof run` prints around the results: progress in a terminal, and the commands
that go with a failure."""
import io
import sys

from brickproof import cli
from brickproof.campaign.results import CutResult


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_progress_after_each_clean_cut_in_a_terminal_only(monkeypatch):
    monkeypatch.setattr(cli, "_progress", {"total": 4, "done": 0, "t0": 0.0})
    monkeypatch.setattr(cli.time, "time", lambda: 40.0)      # 40 s for the first of 4
    monkeypatch.setattr(sys, "stdout", Terminal())
    assert cli._progress_line(CutResult(cut="op-0")) == "  cut 1 of 4, about 2 min left"
    assert cli._progress_line(CutResult(cut="baseline (no cut)", baseline=True)) is None
    assert cli._progress_line(CutResult(cut="op-3 erase-half", torn="erase-half")) is None
    monkeypatch.setattr(sys, "stdout", io.StringIO())          # a log file: no progress lines
    assert cli._progress_line(CutResult(cut="op-1")) is None


def test_times_read_as_a_person_would_say_them():
    assert cli._duration(5) == "5 s"
    assert cli._duration(600) == "10 min"
    assert cli._duration(3 * 3600) == "3.0 h"


def test_a_failure_ends_with_how_to_see_it_again_and_put_it_on_a_board(capsys):
    cut = {"cut": "op-9", "passed": False, "skipped": False, "message": "the device did not come back",
           "baseline": False, "torn": None, "depth": 1, "op_index": 9, "fired": True}
    report = {"adapter_file": "my.yaml", "cuts": [cut]}
    out = type("Out", (), {"passed": False})()
    cli._print_verdict(out, report, "report.html")
    text = capsys.readouterr().out
    assert "run it alone:  brickproof run my.yaml --cut 9" in text
    assert "for a board:   brickproof export my.yaml --cut 9 -o op-9.bin" in text


def test_quick_keeps_only_a_sampled_plan():
    import os
    from brickproof import adapter as adapters
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ad = adapters.load(os.path.join(root, "examples", "demo_ab_bootloader", "f103", "adapter.yaml"))
    assert ad.content_faults and ad.bit_errors and ad.plan["mode"] == "every"
    cli.quick(ad)
    assert ad.plan == {"mode": "phases", "per_phase": 1}
    assert not (ad.torn or ad.depth or ad.content_faults or ad.link_cuts or ad.bit_errors)


def test_quick_and_full_together_are_refused(capsys):
    assert cli.main(["run", "anything.yaml", "--quick", "--full"]) == 2
    assert "pick one" in capsys.readouterr().err
