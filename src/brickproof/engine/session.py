"""Drive one Renode instance in lock step with BrickProof, so runs are deterministic.

Renode is started with a monitor port. Virtual time only advances when we call
run_for(), and UART input is injected while the machine is paused. That removes
every wall-clock race between the host side and the emulated firmware.

Everything Renode needs is copied into a work folder first and referenced by
relative path, because the monitor breaks on paths with spaces.

Ported from the Three-Tier bootloader's tests/renode/renode_session.py.
"""
import atexit
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import weakref
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
REG_PENDING = 0x124
REG_AUDIT = 0x128
REG_REFUSED = 0x12C
REG_REFUSED_AT = 0x130
REG_RESYNC = 0x138
REG_COMPARE = 0x13C
REG_CMP_FROM = 0x140
REG_CMP_LEN = 0x144
REG_PROTECTED = 0x148
REG_PROTECTED_AT = 0x14C
EXPECT_BASE = 0x92000000         # bpExpect: an image for the flash model to compare flash with
TRACE_KINDS = {"E": "erase", "M": "mass_erase", "P": "program", "P?": "program", "X": "refused",
               "W": "protected"}
NEVER = 0xFFFFFFFF

CUT_ERASE = 1
CUT_PROGRAM = 2


# Every session that has a Renode process. If the interpreter exits without them
# being closed (an exception in a user's script, Ctrl-C), they are closed here:
# a leftover renode.exe keeps eating CPU and slows every later run.
_live = weakref.WeakSet()


@atexit.register
def _close_leftovers():
    for session in list(_live):
        session.close()


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
    # Option bytes, where the chip has them: their address, and what they hold when a
    # test starts. A flash image is then the flash followed by these bytes, so a change
    # to them is saved, restored, replayed and compared like any other.
    ob_base: int = None
    option_bytes: bytes = b""
    wrp_unit: int = 0x1000      # how much flash one write-protection bit covers

    @property
    def ob_size(self):
        return len(self.option_bytes) if self.ob_base is not None else 0

    @property
    def image_size(self):
        return self.size + self.ob_size


SLOWEST_START = 6.0     # assume a slow machine until this one has been measured


def hang_limit(seconds, slowest):
    """Wall-clock seconds to wait for `seconds` of emulated time before deciding the
    emulated CPU is stuck (on Renode a locked-up core means RunFor never returns).

    Twenty times the slowest this machine has been seen to run, never under 30 s, and
    never over the old fixed allowance. Too short would call a slow but healthy device
    dead, which is a false failure, so the floor is generous: a healthy slice takes a
    second or two. Too long only costs time on a device that really is dead."""
    return min(60 + 120 * seconds, max(30.0, 20 * seconds * slowest))


def find_renode():
    exe = os.environ.get("RENODE_PATH") or shutil.which("renode")
    if not exe and sys.platform == "win32" and os.path.exists("D:/Tools/renode/renode.exe"):
        exe = "D:/Tools/renode/renode.exe"
    return exe


_ports_lock = threading.Lock()
_ports_given = set()
_launch_lock = threading.Lock()     # Renode processes are started one at a time


def free_port():
    """A TCP port nothing is listening on, and that this process has not handed out
    before. The system only promises the first; with several sessions starting at
    once, two of them were given the same port."""
    with _ports_lock:
        for _ in range(200):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            s.close()
            if port not in _ports_given:
                _ports_given.add(port)
                return port
    raise RuntimeError("could not find a free TCP port")


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
        self._slowest = SLOWEST_START   # wall seconds per emulated second, the worst seen
        self._start()

    STARTUP_WAIT = 90           # seconds to wait for Renode's monitor to answer
    QUIT_WAIT = 10              # seconds to let it exit by itself before it is killed
    START_TRIES = 3

    def _start(self):
        """Bring Renode up. If anything on the way fails (a platform it rejects, memory
        sizes that do not match), the process must not be left running behind us."""
        # One Renode is brought up at a time: several initialising at once collide (on
        # the history file before it was moved, on Renode's temporary-files manager,
        # "Access is denied"). The collision is in start-up only; once machines exist
        # they run side by side. A failed start is tried again before giving up.
        for attempt in range(self.START_TRIES):
            _live.add(self)
            try:
                with _launch_lock:
                    self._bring_up()
                return
            except BaseException as e:
                self.close()
                last = attempt == self.START_TRIES - 1
                if last or not isinstance(e, (OSError, RuntimeError)):
                    raise
                time.sleep(1.0)

    def _bring_up(self):
        self.mon_port = free_port()
        self.uart_port = free_port()
        # Renode keeps a monitor command history, and rewrites the whole file after
        # every command. By default that is one file per user, shared by every Renode:
        # it grows without end (25 MB after a few days here, 67 ms per command), and two
        # Renodes writing it at once crash. Give this one its own, in its work folder.
        config = os.path.join(self.workdir, "renode.config")
        with open(config, "w") as f:
            f.write("[general]" + chr(10) + "history-path = %s" % os.path.join(self.workdir, "history")
                    + chr(10))
        # Its own temp folder too. Renode keeps `renode-<pid>` folders in the temp
        # directory, and on start-up looks up the process of every one it finds there.
        # A folder left by a Renode that was killed can carry a pid Windows has since
        # given to a protected process, and then that look-up fails ("Access is denied")
        # and the new Renode dies. Alone in its own folder it finds nothing to trip on,
        # and what it leaves behind goes when the work folder does.
        tmp = os.path.join(self.workdir, "tmp")
        os.makedirs(tmp, exist_ok=True)
        env = dict(os.environ, TMP=tmp, TEMP=tmp, TMPDIR=tmp)
        self.proc = subprocess.Popen(
            [self.exe, "--disable-xwt", "--plain", "--port", str(self.mon_port), "--config", config],
            cwd=self.workdir, stdin=subprocess.PIPE, env=env,
            stdout=open(self.log, "ab") if self.log else subprocess.DEVNULL, stderr=subprocess.STDOUT)
        self.mon = connect(self.mon_port, self.STARTUP_WAIT)
        self._buf = b""
        self._drain_banner()
        self.cmd("logLevel 3")
        self.cmd('emulation CreateServerSocketTerminal %d "term" false' % self.uart_port)
        self.cmd('mach create "target"')
        self.cmd("machine LoadPlatformDescription @platform.repl")
        self._check_memory_sizes()
        # Renode's flash starts as 0x00; real erased flash reads 0xFF. The option bytes
        # go in with it, before anything reads them.
        self.restore_flash(bytes([0xFF]) * self.flash.size + self.flash.option_bytes, "erased.bin")
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
        self.flash_resync()             # the firmware just loaded is what flash should hold

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

    def cmd_batch(self, lines, timeout=300, per_line=40):
        """Run many monitor commands and return their combined output.

        Renode spends 40 to 60 ms on every monitor line whatever it holds, but takes
        several commands on one line separated by ';'. So a group costs about what one
        command does. That fixed cost, not emulation, was most of a cut's time."""
        out = []
        for i in range(0, len(lines), per_line):
            text = "; ".join(lines[i:i + per_line])
            reply = self.cmd(text, timeout=timeout)
            out.append(reply[reply.find(text) + len(text):])
        return "".join(out)

    @staticmethod
    def _values(reply):
        """The numbers a group of read commands printed, in order."""
        return [int(v, 16) for v in re.findall(r"^\s*(0x[0-9A-Fa-f]+)\s*$", reply, re.M)]

    def read_words(self, addrs):
        """Several 32-bit reads for the price of one monitor line."""
        values = self._values(self.cmd_batch(["sysbus ReadDoubleWord 0x%X" % a for a in addrs]))
        if len(values) != len(addrs):
            raise RuntimeError("asked for %d words, Renode printed %d" % (len(addrs), len(values)))
        return values

    # ---- time and UART ----------------------------------------------------

    def _run_cmd(self, seconds):
        # RunFor wants fixed-point text; scientific notation is rejected
        return 'emulation RunFor "%.7f"' % seconds

    def hang_limit(self, seconds):
        """How long, in wall-clock seconds, to wait for `seconds` of emulated time before
        calling the CPU stuck."""
        return hang_limit(seconds, self._slowest)

    def run_for(self, seconds):
        t0 = time.time()
        try:
            self.cmd(self._run_cmd(seconds), timeout=self.hang_limit(seconds))
        except TimeoutError:
            raise MachineHung("emulated time stopped advancing") from None
        if seconds >= 0.05:
            # learn how slow this machine really is; only ever towards "slower"
            self._slowest = max(self._slowest, (time.time() - t0) / seconds)
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
        per_byte = max(10.0 / baud, 0.0001)             # never finer than one 100 us quantum
        lines = []
        for b in data:
            lines.append("%s WriteChar %d" % (port, b))
            lines.append(self._run_cmd(per_byte))
        self.cmd_batch(lines)
        self.virtual_time += per_byte * len(data)
        self._pull(0.0)

    # ---- memory -----------------------------------------------------------

    def read_word(self, addr):
        return self.read_words([addr])[0]

    def read_half(self, addr):
        return self._values(self.cmd_batch(["sysbus ReadWord 0x%X" % addr]))[0]

    def write_half(self, addr, value):
        """Change one halfword of flash from outside, and tell the flash model."""
        self.cmd_batch(["sysbus WriteWord 0x%X 0x%X" % (addr, value), self._set(REG_RESYNC, 1)])

    def write_word(self, addr, value):
        self.cmd("sysbus WriteDoubleWord 0x%X 0x%X" % (addr, value))

    def load_binary(self, rel_path, addr):
        """Put a file straight into memory. Path is relative to the work folder. The
        flash model is told, in case the file went into flash."""
        self.cmd_batch(["sysbus LoadBinary @%s 0x%X" % (rel_path, addr), self._set(REG_RESYNC, 1)])

    def read_bytes(self, addr, n):
        """n bytes of memory. Slow, about 100 ms per KB: it comes back as text."""
        out = self.cmd("sysbus ReadBytes 0x%X 0x%X" % (addr, n), timeout=600)
        out = out[out.find("["):]
        data = bytes(int(t, 16) for t in re.findall(r"0x[0-9A-Fa-f]{2}", out))
        if len(data) != n:
            raise RuntimeError("read of 0x%X bytes at 0x%X returned %d" % (n, addr, len(data)))
        return data

    def dump_flash(self):
        """The whole flash image as bytes: the flash, then the option bytes if the chip
        has them (slow: a few seconds for 128 KB)."""
        image = self.read_bytes(self.flash.base, self.flash.size)
        if self.flash.ob_size:
            image += self.read_bytes(self.flash.ob_base, self.flash.ob_size)
        return image

    def restore_flash(self, data, name="flash_restore.bin"):
        """Replace the whole flash with `data` and forget what the flash checks had seen.
        Renode snapshots crash with Python peripherals, so this is how a run goes back
        to a known state."""
        f = self.flash
        with open(os.path.join(self.workdir, name), "wb") as out:
            out.write(data[:f.size])
        lines = ["sysbus LoadBinary @%s 0x%X" % (name, f.base)]
        if f.ob_size and len(data) > f.size:
            with open(os.path.join(self.workdir, "ob_" + name), "wb") as out:
                out.write(data[f.size:f.size + f.ob_size])
            lines.append("sysbus LoadBinary @ob_%s 0x%X" % (name, f.ob_base))
        self.cmd_batch(lines + [self._set(REG_RESYNC, 1)] + self._clear_checks())

    def flash_mismatch(self, expected, name="flash_expect.bin"):
        """First address where flash differs from `expected` (a whole-flash image), or
        None. The comparison runs inside the flash model, on the whole flash: loading
        a file is fast, reading memory back as text is not."""
        f = self.flash
        addr = self.image_mismatch(expected[:f.size], f.base, name, whole=True)
        if addr is None and f.ob_size and len(expected) > f.size:
            now = self.read_bytes(f.ob_base, f.ob_size)
            for i in range(f.ob_size):
                if now[i] != expected[f.size + i]:
                    return f.ob_base + i
        return addr

    def image_mismatch(self, data, addr, name="image_expect.bin", whole=False):
        """First address where flash at `addr` differs from `data`, or None if that
        image is exactly what is there."""
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        reply = self.cmd_batch(
            ["sysbus LoadBinary @%s 0x%X" % (name, addr - self.flash.base + EXPECT_BASE),
             self._set(REG_CMP_FROM, addr), self._set(REG_CMP_LEN, 0 if whole else len(data)),
             self._set(REG_COMPARE, 1), self._get(REG_COMPARE)])
        return self._values(reply)[-1] or None

    def sample_cpu(self, n=4, interval=0.02):
        """Let the firmware run and look at the core n times: [(pc, exception number)].
        Exception 0 is normal thread code; 2 to 6 are NMI and the fault handlers."""
        lines = []
        for _ in range(n):
            lines += [self._run_cmd(interval), "cpu PC", "cpu CPSR"]
        try:
            values = self._values(self.cmd_batch(lines, timeout=self.hang_limit(n * interval)))
        except TimeoutError:
            raise MachineHung("emulated time stopped advancing") from None
        self.virtual_time += n * interval
        self._pull()
        if len(values) != 2 * n:
            raise RuntimeError("asked for %d CPU samples, Renode printed %d values" % (n, len(values)))
        return [(values[i], values[i + 1] & 0x1FF) for i in range(0, 2 * n, 2)]

    # ---- the flash model's cut controls ----------------------------------

    def _ctl(self, reg):
        return self.flash.controller + reg

    def _set(self, reg, value):
        """The monitor command that writes one of the flash model's test registers."""
        return "sysbus WriteDoubleWord 0x%X 0x%X" % (self._ctl(reg), value)

    def _get(self, reg):
        return "sysbus ReadDoubleWord 0x%X" % self._ctl(reg)

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

    def run_until_cut(self, limit, step=0.01):
        """Advance until the armed cut fires. True if it did within `limit` virtual seconds."""
        waited = 0.0
        while waited < limit:
            try:
                reply = self.cmd_batch([self._run_cmd(step), self._get(REG_CUT_FIRED)],
                                       timeout=self.hang_limit(step))
            except TimeoutError:
                raise MachineHung("emulated time stopped advancing") from None
            self.virtual_time += step
            waited += step
            if self._values(reply)[-1] == 1:
                self._pull()
                return True
        self._pull()
        return False

    def cut_info(self):
        """(kind, page address): kind 1 = erase cut before it ran, 2 = program, 0 = none."""
        kind, addr = self.read_words([self._ctl(REG_CUT_KIND), self._ctl(REG_CUT_ADDR)])
        return kind, addr

    def cut_status(self):
        """(kind, page address, operations started), read together after a cut."""
        return tuple(self.read_words([self._ctl(r) for r in (REG_CUT_KIND, REG_CUT_ADDR, REG_OPCOUNT)]))

    # ---- what the chip would not have allowed -----------------------------

    def violations(self):
        """Everything the firmware did that the emulator lets pass and the chip does not,
        read in one go:
          fault    (address, pc): it touched memory the chip does not have
          refused  (count, first address): programs over cells that were not erased
          stray    first address where flash changed with no flash operation behind it
          protected  (count, first address): erases or programs in write-protected pages
        Each is None when clean. A power cycle clears the fault; restore_flash the rest."""
        fa, fpc, n, at, stray, wn, wat = self._values(self.cmd_batch(
            [self._get(REG_FAULT_ADDR), self._get(REG_FAULT_PC), self._get(REG_REFUSED),
             self._get(REG_REFUSED_AT), self._set(REG_AUDIT, 1), self._get(REG_AUDIT),
             self._get(REG_PROTECTED), self._get(REG_PROTECTED_AT)]))
        return {"fault": (fa, fpc) if fa else None,
                "refused": (n, at) if n else None,
                "stray": stray or None,
                "protected": (wn, wat) if wn else None}

    def bus_fault(self):
        return self.violations()["fault"]

    def flash_resync(self):
        """Tell the flash model that flash is now what it should be. The model keeps a
        shadow copy that only real flash operations update; anything the engine puts
        into flash itself has to be declared, or it would look like a stray write."""
        self.write_word(self._ctl(REG_RESYNC), 1)

    def _clear_checks(self):
        return [self._set(reg, 0) for reg in (REG_AUDIT, REG_REFUSED, REG_REFUSED_AT, REG_PROTECTED,
                                             REG_PROTECTED_AT)]

    # ---- the golden-run trace ---------------------------------------------

    TRACE_NAME = "trace.txt"

    def trace_start(self):
        """Log every flash operation from now on (see the flash model's header)."""
        open(os.path.join(self.workdir, self.TRACE_NAME), "w").close()
        self.write_word(self._ctl(REG_TRACE), 1)

    def trace_stop(self):
        """Stop logging and return the operations as a list of dicts:
        index, kind (erase / mass_erase / program / refused), addr, and for a program
        its value. A refused program is one the chip would not have done.
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
                if parts[0] in ("P", "X"):
                    op["value"] = int(parts[2], 16)
                if parts[0] == "X":
                    op["old"] = int(parts[3], 16)
                elif parts[0] == "P?":
                    op["inferred"] = True
                ops.append(op)
        return ops

    # ---- reset and power --------------------------------------------------

    def reboot(self, settle=1.5):
        """Reset the CPU and peripherals; flash contents are kept. A reset also
        re-initialises the flash model, so arm a cut after it, not before.
        settle=0 leaves the machine paused at the reset vector."""
        self.cmd_batch(self._reset_lines())
        self.rx.clear()
        if settle:
            self.run_for(settle)

    def _reset_lines(self):
        return ["machine Reset", "cpu VectorTableOffset 0x%X" % self.vector_table] + self.reset_cmds

    def uart_text(self):
        return self.rx.decode(errors="replace")

    def power_cycle(self, settle=1.5):
        """A real power loss: RAM is lost, flash is kept, everything restarts.
        ZeroAll, not FillWithConstantByte: the latter takes over a minute here."""
        # One batch: every monitor round trip costs about 35 ms, and this runs two or
        # three times per cut. The flash model's state outlives resets on purpose, so
        # it is cleared here; PENDING too, because a program cut short never finishes.
        self.cmd_batch(["%s ZeroAll" % self.ram, "cpu IsHalted false",
                        self._set(REG_CUTPOINT, NEVER), self._set(REG_CUT_PAGE, NEVER),
                        self._set(REG_OPCOUNT, 0), self._set(REG_FAULT_ADDR, 0),
                        self._set(REG_FAULT_PC, 0), self._set(REG_PENDING, 0)] + self._reset_lines())
        self.rx.clear()
        if settle:
            self.run_for(settle)

    def pc(self):
        for tok in self.cmd("cpu PC").split():
            if tok.startswith("0x"):
                return int(tok, 16)
        return None

    def close(self):
        """Stop Renode. Safe to call at any point, including half-way through start-up
        and more than once."""
        _live.discard(self)
        mon = self.__dict__.pop("mon", None)
        if mon is not None:
            try:
                mon.settimeout(5)
                mon.sendall(b"quit\n")
            except OSError:
                pass
        for s in (mon, self.__dict__.pop("uart", None)):
            try:
                s.close()
            except Exception:
                pass
        proc = self.__dict__.pop("proc", None)
        if proc is None:
            return
        try:
            proc.stdin.close()
            proc.wait(timeout=self.QUIT_WAIT)
        except Exception:
            proc.kill()
            proc.wait(timeout=10)


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
