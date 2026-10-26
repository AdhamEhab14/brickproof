"""Starting Renode, talking to its monitor, and stopping it."""
import os
import re
import subprocess
import threading
import time
from brickproof.engine.common import SLOWEST_START, connect, free_port, _live

PROMPT_RE = re.compile(rb"\([^)\r\n]*\) $")

_launch_lock = threading.Lock()     # Renode processes are started one at a time




class Process:
    """One part of RenodeSession (engine/session.py): what the module docstring says."""

    STARTUP_WAIT = 90           # seconds to wait for Renode's monitor to answer

    QUIT_WAIT = 10              # seconds to let it exit by itself before it is killed

    START_TRIES = 3

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
        self.uart_sent = 0              # bytes the host has sent to the device, ever
        self.link_budget = None         # bytes the link still carries before it breaks; None: no limit
        self._slowest = SLOWEST_START   # wall seconds per emulated second, the worst seen
        self._start()

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
        if self.flash.ext_size:
            # the external flash chip is a C# model, compiled as it is loaded
            self.cmd("include @models/BpSpiNor.cs", timeout=120)
        if self.flash.eeprom_size:
            self.cmd("include @models/BpI2cEeprom.cs", timeout=120)
        self.cmd("machine LoadPlatformDescription @platform.repl")
        # By default Renode will not let virtual time get ahead of host time: when it is
        # ahead, the CPU thread sleeps until the host catches up. Host time only counts
        # while emulation runs, and the flash models skip a whole sector erase (a second
        # or more) at once, so a fresh emulator is often "ahead" and sleeps: on CI every
        # first update spent two one-second slices asleep. Nothing here needs real-time
        # pacing; virtual time is all that is measured.
        self.cmd("emulation SetGlobalAdvanceImmediately true")
        if os.path.exists(os.path.join(self.workdir, "models", "nrf52_power.py")):
            self.cmd("include @models/nrf52_power.py")        # System OFF (see the file)
        self._check_memory_sizes()
        # Renode's flash starts as 0x00; real erased flash reads 0xFF. The option bytes
        # go in with it, before anything reads them.
        self.restore_flash(bytes([0xFF]) * self.flash.size + self.flash.option_bytes, "erased.bin")
        for rel, addr in self.firmware:
            if rel.lower().endswith(".elf"):
                self.cmd("sysbus LoadELF @%s" % rel)
            elif self.flash.external(addr):
                self.cmd('%s LoadAt "%s" 0x%X' % (self._ext, self._path(rel), addr - self.flash.ext_base))
            elif self.flash.eeprom(addr):
                self.cmd('%s LoadAt "%s" 0x%X' % (self._ee, self._path(rel), addr - self.flash.eeprom_base))
            else:
                self.cmd("sysbus LoadBinary @%s 0x%X" % (rel, addr))
        self.cmd("cpu VectorTableOffset 0x%X" % self.vector_table)
        # Renode runs this macro after every reset of the machine, including the ones the
        # firmware or a watchdog causes. Without it such a reset leaves the vector table
        # at address 0, where an STM32 has its flash aliased and Renode has nothing.
        self.cmd('macro reset "%s"' % "; ".join(self._after_reset()))
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
