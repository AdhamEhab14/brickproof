"""Drive one Renode instance in lock step with BrickProof, so runs are deterministic.

Renode is started with a monitor port. Virtual time only advances when we call
run_for(), and UART input is injected while the machine is paused. That removes
every wall-clock race between the host side and the emulated firmware.

Everything Renode needs is copied into a work folder first and referenced by
relative path, because the monitor breaks on paths with spaces.

Ported from the Three-Tier bootloader's tests/renode/renode_session.py.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass

PROMPT_RE = re.compile(rb"\([^)\r\n]*\) $")

# test-only registers of the BrickProof flash models (see models/stm32f1_flash.py)
REG_OPCOUNT = 0x100
REG_CUTPOINT = 0x104
REG_CUT_FIRED = 0x108
REG_CUT_KIND = 0x10C
REG_CUT_ADDR = 0x110
REG_CUT_PAGE = 0x114
REG_FAULT_ADDR = 0x118
REG_FAULT_PC = 0x11C
REG_TRACE = 0x120
TRACE_KINDS = {"E": "erase", "M": "mass_erase", "P": "program", "P?": "program"}
NEVER = 0xFFFFFFFF

CUT_ERASE = 1
CUT_PROGRAM = 2


class MachineHung(RuntimeError):
    """Emulated time stopped advancing: the firmware locked up (for example a fault
    while fetching the fault vector). On silicon that is a dead device too."""


@dataclass
class FlashGeometry:
    base: int
    size: int
    page: int
    write_unit: int = 2
    controller: int = 0x40022000


def find_renode():
    exe = os.environ.get("RENODE_PATH") or shutil.which("renode")
    if not exe and sys.platform == "win32" and os.path.exists("D:/Tools/renode/renode.exe"):
        exe = "D:/Tools/renode/renode.exe"
    return exe


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def connect(port, wait):
    end = time.time() + wait
    while True:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=5)
        except OSError:
            if time.time() > end:
                raise
            time.sleep(0.2)


class RenodeSession:
    """One emulated machine.

    workdir     folder that already holds platform.repl and the firmware files
    firmware    list of (relative path, address or None); ELFs load at their own
                addresses, anything else is loaded raw at `address`
    reset_cmds  monitor commands run after every reset (for example a held button)
    """

    def __init__(self, exe, workdir, flash, firmware, uart="usart2",
                 vector_table=0x08000000, mips=72, reset_cmds=(), ram="sram", log=None,
                 memory_sizes=None):
        self.exe = exe
        self.workdir = workdir
        self.flash = flash
        self.mips = mips
        self.vector_table = vector_table
        self.reset_cmds = list(reset_cmds)
        self.ram = ram
        self.uart_name = uart
        self.firmware = list(firmware)
        self.memory_sizes = dict(memory_sizes or {})
        self.log = log
        self.virtual_time = 0.0
        self.rx = bytearray()
        self._start()

    def _start(self):
        self.mon_port = free_port()
        self.uart_port = free_port()
        self.proc = subprocess.Popen(
            [self.exe, "--disable-xwt", "--plain", "--port", str(self.mon_port)],
            cwd=self.workdir, stdin=subprocess.PIPE,
            stdout=open(self.log, "ab") if self.log else subprocess.DEVNULL, stderr=subprocess.STDOUT)
        self.mon = connect(self.mon_port, 90)
        self._buf = b""
        self._drain_banner()
        self.cmd("logLevel 3")
        self.cmd('emulation CreateServerSocketTerminal %d "term" false' % self.uart_port)
        self.cmd('mach create "target"')
        self.cmd("machine LoadPlatformDescription @platform.repl")
        self._check_memory_sizes()
        # Renode's flash starts as 0x00; real erased flash reads 0xFF
        self.restore_flash(b"\xFF" * self.flash.size, "erased.bin")
        for rel, addr in self.firmware:
            if rel.lower().endswith(".elf"):
                self.cmd("sysbus LoadELF @%s" % rel)
            else:
                self.cmd("sysbus LoadBinary @%s 0x%X" % (rel, addr))
        self.cmd("cpu VectorTableOffset 0x%X" % self.vector_table)
        self.cmd("cpu PerformanceInMips %d" % self.mips)
        self.cmd("connector Connect sysbus.%s term" % self.uart_name)
        self.uart = connect(self.uart_port, 10)
        for c in self.reset_cmds:
            self.cmd(c)

    def _check_memory_sizes(self):
        """Refuse to run on a machine whose RAM or flash is not the size the adapter
        says the chip has: every result would be about a different device."""
        for name, want in self.memory_sizes.items():
            text = "sysbus.%s Size" % name
            out = self.cmd(text)
            got = [int(t, 16) for t in out[out.find(text) + len(text):].split() if t.startswith("0x")]
            if not got or got[0] != want:
                raise RuntimeError("memory '%s' is %s in Renode, the adapter says 0x%X"
                                   % (name, hex(got[0]) if got else "unreadable", want))

    def restart(self):
        """Throw this Renode away and start a fresh one with the same machine.
        Flash comes back as first loaded; callers restore what they need."""
        self.close()
        self.rx.clear()
        self._start()

    def _drain_banner(self):
        self.mon.settimeout(2)
        try:
            while True:
                if not self.mon.recv(4096):
                    break
        except OSError:
            pass

    # ---- monitor ----------------------------------------------------------

    def cmd(self, text, timeout=300):
        """Run one monitor command; raise if Renode reports an error."""
        self.mon.sendall(text.encode() + b"\n")
        self.mon.settimeout(timeout)
        buf = self._buf
        while True:
            i = buf.find(text.encode())
            if i >= 0 and PROMPT_RE.search(buf, i + len(text)):
                break
            chunk = self.mon.recv(4096)
            if not chunk:
                raise RuntimeError("Renode monitor closed")
            buf += chunk
        self._buf = b""
        out = buf.decode(errors="replace")
        low = out.lower()
        if "error" in low or "no such command" in low:
            raise RuntimeError("Renode rejected %r:\n%s" % (text, out))
        return out

    def cmd_batch(self, lines, timeout=300):
        """Send many monitor commands in one write; wait for all their prompts."""
        self.mon.sendall(("\n".join(lines) + "\n").encode())
        self.mon.settimeout(timeout)
        buf = self._buf
        want = len(lines)
        while len(re.findall(rb"\([^)\r\n]*\) ", buf)) < want:
            chunk = self.mon.recv(65536)
            if not chunk:
                raise RuntimeError("Renode monitor closed")
            buf += chunk
        self._buf = b""
        out = buf.decode(errors="replace")
        if "error" in out.lower():
            raise RuntimeError("Renode rejected a batch:\n%s" % out[-400:])

    # ---- time and UART ----------------------------------------------------

    def run_for(self, seconds):
        # RunFor wants fixed-point text; scientific notation is rejected. If it does
        # not come back in generous wall-clock time, the emulated CPU is stuck.
        try:
            self.cmd('emulation RunFor "%.7f"' % seconds, timeout=60 + 120 * seconds)
        except TimeoutError:
            raise MachineHung("emulated time stopped advancing") from None
        self.virtual_time += seconds
        self._pull()

    def _pull(self, wait=0.03):
        self.uart.settimeout(wait if wait else 0.001)
        try:
            while True:
                chunk = self.uart.recv(4096)
                if not chunk:
                    break
                self.rx += chunk
        except OSError:
            pass

    def idle(self, seconds, mips=4):
        """Let virtual time pass while the firmware sits in a polling loop. A slower
        emulated CPU makes that cheap in wall-clock time; timers follow virtual time."""
        self.cmd("cpu PerformanceInMips %d" % mips)
        try:
            self.run_for(seconds)
        finally:
            self.cmd("cpu PerformanceInMips %d" % self.mips)

    def uart_write(self, data, baud=115200, port=None):
        """Inject bytes one at a time at wire speed. An STM32 USART holds a single
        received byte, so a burst would overrun it, as on hardware."""
        port = port or self.uart_name
        per_byte = "%.7f" % max(10.0 / baud, 0.0001)   # never finer than one 100 us quantum
        lines = []
        for b in data:
            lines.append("%s WriteChar %d" % (port, b))
            lines.append('emulation RunFor "%s"' % per_byte)
        self.cmd_batch(lines)
        self.virtual_time += float(per_byte) * len(data)
        self._pull(0.0)

    # ---- memory -----------------------------------------------------------

    def read_word(self, addr):
        text = "sysbus ReadDoubleWord 0x%X" % addr
        out = self.cmd(text)
        for tok in out[out.find(text) + len(text):].split():
            if tok.startswith("0x"):
                return int(tok, 16)
        return None

    def read_half(self, addr):
        text = "sysbus ReadWord 0x%X" % addr
        out = self.cmd(text)
        for tok in out[out.find(text) + len(text):].split():
            if tok.startswith("0x"):
                return int(tok, 16)
        return None

    def write_half(self, addr, value):
        self.cmd("sysbus WriteWord 0x%X 0x%X" % (addr, value))

    def write_word(self, addr, value):
        self.cmd("sysbus WriteDoubleWord 0x%X 0x%X" % (addr, value))

    def load_binary(self, rel_path, addr):
        """Put a file straight into memory. Path is relative to the work folder."""
        self.cmd("sysbus LoadBinary @%s 0x%X" % (rel_path, addr))

    def read_bytes(self, addr, n):
        """n bytes of memory (about 40 ms per KB: it comes back as text)."""
        out = self.cmd("sysbus ReadBytes 0x%X 0x%X" % (addr, n), timeout=600)
        out = out[out.find("["):]
        data = bytes(int(t, 16) for t in re.findall(r"0x[0-9A-Fa-f]{2}", out))
        if len(data) != n:
            raise RuntimeError("read of 0x%X bytes at 0x%X returned %d" % (n, addr, len(data)))
        return data

    def dump_flash(self):
        """The whole flash as bytes (slow: about 5 s for 128 KB)."""
        return self.read_bytes(self.flash.base, self.flash.size)

    def restore_flash(self, data, name="flash_restore.bin"):
        """Replace the whole flash with `data`. Renode snapshots crash with Python
        peripherals, so this is how a run goes back to a known state."""
        open(os.path.join(self.workdir, name), "wb").write(data)
        self.load_binary(name, self.flash.base)

    # ---- the flash model's cut controls ----------------------------------

    def _ctl(self, reg):
        return self.flash.controller + reg

    def flash_ops(self):
        """Flash operations started since the counter was last cleared."""
        return self.read_word(self._ctl(REG_OPCOUNT))

    def set_cut(self, opcount):
        """Cut power when the flash model is about to start operation number `opcount`."""
        self.write_word(self._ctl(REG_CUTPOINT), opcount)

    def set_cut_on_erase(self, page_addr):
        """Cut power when the firmware is about to erase the page at page_addr."""
        self.write_word(self._ctl(REG_CUT_PAGE), page_addr)

    def cut_fired(self):
        return self.read_word(self._ctl(REG_CUT_FIRED)) == 1

    def cut_info(self):
        """(kind, page address): kind 1 = erase cut before it ran, 2 = program, 0 = none."""
        return self.read_word(self._ctl(REG_CUT_KIND)), self.read_word(self._ctl(REG_CUT_ADDR))

    def bus_fault(self):
        """(address, pc) if the firmware touched memory the chip does not have since
        the last power cycle, else None. power_cycle() clears it, so ask before the next one."""
        addr = self.read_word(self._ctl(REG_FAULT_ADDR))
        return (addr, self.read_word(self._ctl(REG_FAULT_PC))) if addr else None

    # ---- the golden-run trace ---------------------------------------------

    TRACE_NAME = "trace.txt"

    def trace_start(self):
        """Log every flash operation from now on (see the flash model's header)."""
        open(os.path.join(self.workdir, self.TRACE_NAME), "w").close()
        self.write_word(self._ctl(REG_TRACE), 1)

    def trace_stop(self):
        """Stop logging and return the operations as a list of dicts:
        index, kind (erase / mass_erase / program), addr, and for a program its value.
        `inferred` marks a program whose address is a guess: it wrote what was already
        there, so nothing in flash changed."""
        self.write_word(self._ctl(REG_TRACE), 0)
        ops = []
        with open(os.path.join(self.workdir, self.TRACE_NAME)) as f:
            for line in f:
                parts = line.split()
                if not parts:
                    continue
                op = {"index": len(ops), "kind": TRACE_KINDS[parts[0]], "addr": int(parts[1], 16)}
                if parts[0] == "P":
                    op["value"] = int(parts[2], 16)
                elif parts[0] == "P?":
                    op["inferred"] = True
                ops.append(op)
        return ops

    # ---- reset and power --------------------------------------------------

    def reboot(self, settle=1.5):
        """Reset the CPU and peripherals; flash contents are kept. A reset also
        re-initialises the flash model, so arm a cut after it, not before.
        settle=0 leaves the machine paused at the reset vector."""
        self.cmd("machine Reset")
        self.cmd("cpu VectorTableOffset 0x%X" % self.vector_table)
        for c in self.reset_cmds:
            self.cmd(c)
        self.rx.clear()
        if settle:
            self.run_for(settle)

    def uart_text(self):
        return self.rx.decode(errors="replace")

    def power_cycle(self, settle=1.5):
        """A real power loss: RAM is lost, flash is kept, everything restarts.
        ZeroAll, not FillWithConstantByte: the latter takes over a minute here."""
        self.cmd("%s ZeroAll" % self.ram)
        self.cmd("cpu IsHalted false")
        # the flash model's state outlives resets on purpose, so clear it here
        self.write_word(self._ctl(REG_CUTPOINT), NEVER)
        self.write_word(self._ctl(REG_CUT_PAGE), NEVER)
        self.write_word(self._ctl(REG_OPCOUNT), 0)
        self.write_word(self._ctl(REG_FAULT_ADDR), 0)
        self.write_word(self._ctl(REG_FAULT_PC), 0)
        self.reboot(settle=settle)

    def pc(self):
        for tok in self.cmd("cpu PC").split():
            if tok.startswith("0x"):
                return int(tok, 16)
        return None

    def close(self):
        try:
            self.cmd("quit", timeout=5)
        except Exception:
            pass
        for s in (getattr(self, "mon", None), getattr(self, "uart", None)):
            try:
                s.close()
            except Exception:
                pass
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


class RenodeSerial:
    """pyserial-like view of the emulated UART, so a target's real host tool runs unchanged."""

    def __init__(self, session, timeout=20, step=0.01):
        self.s = session
        self.timeout = timeout
        self.step = step

    def write(self, data):
        self.s.uart_write(bytes(data))

    def read(self, n):
        waited = 0.0
        while len(self.s.rx) < n and waited < self.timeout:
            self.s.run_for(self.step)
            waited += self.step
        out = bytes(self.s.rx[:n])
        del self.s.rx[:n]
        return out

    def sleep(self, seconds):
        """Host tools wait through this, so a wait advances emulated time, not real time."""
        self.s.idle(seconds)

    def close(self):
        pass
