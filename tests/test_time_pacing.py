"""Renode must never pace virtual time against the host clock.

By default it does: when virtual time is ahead of host time, the CPU thread sleeps
until the host catches up. Host time only counts while emulation runs, and the flash
models skip a whole sector erase at once, so a fresh emulator is often "ahead". On CI
every first update spent two one-second slices asleep.

A fake Renode monitor plays the emulator here: it answers every command with an echo
and a prompt and keeps what it was sent, so these run without Renode.
"""
import re
import socket
import subprocess
import sys
import threading

import pytest

from brickproof.engine import session as S
from brickproof.engine.session import FlashGeometry, RenodeSession

FLASH = FlashGeometry(base=0x08000000, size=0x1000, page=0x400)
PACING_OFF = "emulation SetGlobalAdvanceImmediately true"


class FakeMonitor:
    """Renode's monitor as the session sees it, on the port the session chose."""
    cpsr = 0x01000000          # what `cpu CPSR` prints: Thumb state, as on any Cortex-M

    def __init__(self, port, sent):
        self.sent = sent
        self.server = socket.create_server(("127.0.0.1", port))
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.server.accept()
        conn.sendall(b"Renode, version 1.17.0\n(monitor) ")
        buf = b""
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode()
                if text == "quit":
                    conn.close()
                    return
                self.sent.append(text)
                m = re.search(r"CreateServerSocketTerminal (\d+)", text)
                if m:
                    # the UART the session connects to next
                    uart = socket.create_server(("127.0.0.1", int(m.group(1))))
                    threading.Thread(target=uart.accept, daemon=True).start()
                # one value per read, in the order asked
                values = b""
                for part in text.split(";"):
                    if "ReadDoubleWord" in part:
                        values += b"0x00000000\n"
                    elif part.strip() == "cpu CPSR":
                        values += b"0x%08X\n" % FakeMonitor.cpsr
                    elif part.strip() == "cpu PC":
                        values += b"0x08000100\n"
                conn.sendall(line + b"\n" + values + b"(target) ")


def fake_renode(monkeypatch):
    """Every Renode the session starts is a fake monitor and a process that just waits.
    Returns the list of commands each one was sent, in start order."""
    started = []
    real_popen = subprocess.Popen

    def popen(args, **kw):
        sent = []
        started.append(sent)
        FakeMonitor(int(args[args.index("--port") + 1]), sent)
        kw.pop("stdout", None)
        kw.pop("stderr", None)
        return real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kw)

    monkeypatch.setattr(S.subprocess, "Popen", popen)
    return started


class Quick(RenodeSession):
    QUIT_WAIT = 0.5

    def _drain_banner(self):
        self.mon.settimeout(0.3)
        try:
            self.mon.recv(4096)
        except OSError:
            pass


def test_every_emulator_runs_without_real_time_pacing(monkeypatch, tmp_path):
    started = fake_renode(monkeypatch)
    s = Quick("renode", str(tmp_path), FLASH, [])
    try:
        sent = started[0]
        assert PACING_OFF in sent
        # set on the machine before any firmware is loaded or run
        at = sent.index(PACING_OFF)
        assert at > sent.index('mach create "target"')
        assert not any("LoadBinary" in c or "RunFor" in c for c in sent[:at])

        s.run_for(1.0)
        assert any("RunFor" in c for c in sent[at:])
    finally:
        s.close()


def test_a_restarted_emulator_runs_without_real_time_pacing_too(monkeypatch, tmp_path):
    # a lock-up restarts Renode; the fresh one must not be paced either
    started = fake_renode(monkeypatch)
    s = Quick("renode", str(tmp_path), FLASH, [])
    try:
        s.restart()
        assert len(started) == 2
        assert PACING_OFF in started[1]
    finally:
        s.close()


def test_a_core_out_of_thumb_state_is_locked_up_at_once(monkeypatch, tmp_path):
    # Renode can leave a Cortex-M running with its T bit clear after a jump through an
    # erased vector; on the chip that is a fault and a dead device, whatever the pace
    fake_renode(monkeypatch)
    s = Quick("renode", str(tmp_path), FLASH, [])
    try:
        s.run_for(0.5)                              # Thumb state: runs on
        slowest = s._slowest
        monkeypatch.setattr(FakeMonitor, "cpsr", 0x00000000)
        with pytest.raises(S.MachineHung, match="Thumb"):
            s.run_for(0.5)
        assert s._slowest == slowest, "a slice spent there does not teach the pace"
        with pytest.raises(S.MachineHung, match="Thumb"):
            s.sample_cpu()
    finally:
        s.close()
