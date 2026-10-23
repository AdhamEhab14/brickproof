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
REG_PCROP_READS = 0x150         # STM32F4: data reads of proprietary-code (PCROP) sectors
REG_PCROP_AT = 0x154
REG_ECC_BROKEN = 0x160          # STM32L4: double words whose ECC does not match (internal)
ECC_MAP = 0x94000000            # STM32L4: the flash model's ECC map, a byte per double word
STATE_PWR_FLAGS = 0x90000000 + 4 * 41     # the PWR model's SBF and WUF (models/stm32_pwr.py)
STATE_PWR_ASLEEP = 0x90000000 + 4 * 45    # and the Standby a wake is due for
STATE_RESETS = 0x90000000 + 4 * 60        # resets the flash model has seen since power-up
EXPECT_BASE = 0x92000000         # bpExpect: an image for the flash model to compare flash with
TRACE_KINDS = {"E": "erase", "M": "mass_erase", "P": "program", "P?": "program", "X": "refused",
               "W": "protected", "Q": "partial_erase"}
NEVER = 0xFFFFFFFF
EXT_STATUS_BYTES = 3            # an external chip's status registers 1, 2 and 3, as stored

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
    page: int = None            # the erase unit, where it is the same everywhere
    write_unit: int = 2         # bytes a program usually writes
    # where erase units differ in size (an STM32F4's sectors): [(offset, size), ...]
    sectors: list = None
    controller: int = 0x40022000
    model: str = "stm32f1_flash.py"      # the flash controller model in models/
    timing: int = 0             # how long operations take: 0 none, 1 typical, 2 slowest
    # an external SPI NOR flash chip, if the board has one. It has no address on the
    # system bus; ext_base is only how its bytes are named in traces and images.
    ext_base: int = None
    ext_size: int = 0
    ext_bus: str = ""           # the SPI controller it hangs on, for example spi1
    ext_cs: str = ""            # its chip select pin, for example PA4
    ext_sector: int = 0x1000    # its smallest erase
    ext_endurance: int = 100000
    ext_status: int = 0         # its status registers as shipped: 1 | 2 << 8 | 3 << 16
    ext_wp: str = ""            # the pin wired to its /WP, if any (otherwise /WP reads high)
    # an I2C EEPROM (24-series), if the board has one. Like the external flash it has no
    # address on the system bus; eeprom_base names its bytes in traces and images.
    eeprom_base: int = None
    eeprom_size: int = 0
    eeprom_page: int = 32       # bytes one write can cover (it wraps inside the page)
    eeprom_bus: str = ""        # the I2C controller it hangs on, for example i2c1
    eeprom_i2c: int = 0x50      # its 7-bit bus address
    eeprom_address_bytes: int = 2
    eeprom_endurance: int = 1000000
    endurance: int = 0          # erase cycles the datasheet promises per unit (0: unknown)
    # Option bytes, where the chip has them: their address, and what they hold when a
    # test starts. A flash image is then the flash followed by these bytes, so a change
    # to them is saved, restored, replayed and compared like any other.
    ob_base: int = None
    mass_erase_ob: bool = False  # a mass erase wipes the option bytes too (the nRF52's UICR)
    option_bytes: bytes = b""
    wrp_unit: int = 0x1000      # how much flash one write-protection bit covers
    worn: tuple = None          # (from, to): pages whose programs no longer take (flash.worn)
    # ECC, where the chip has it (STM32L4): every 64 bits carry their own check bits, and a
    # program or erase cut short leaves them not matching. The image ends with a map, one
    # byte per double word, 1 where that is so.
    ecc: bool = False

    def unit_at(self, addr):
        """(first address, size) of the erase unit that holds `addr`."""
        if self.sectors:
            off = addr - self.base
            for start, size in self.sectors:
                if start <= off < start + size:
                    return self.base + start, size
            raise ValueError("0x%08X is not in any flash sector" % addr)
        return self.base + (addr - self.base) // self.page * self.page, self.page

    def units(self):
        """Every erase unit, in order: [(first address, size), ...]."""
        if self.sectors:
            return [(self.base + start, size) for start, size in self.sectors]
        return [(self.base + off, self.page) for off in range(0, self.size, self.page)]

    @property
    def ob_size(self):
        return len(self.option_bytes) if self.ob_base is not None else 0

    def external(self, addr):
        return self.ext_base is not None and self.ext_base <= addr < self.ext_base + self.ext_size

    def eeprom(self, addr):
        return self.eeprom_base is not None and self.eeprom_base <= addr < self.eeprom_base + self.eeprom_size

    @property
    def eeprom_offset(self):
        # where the EEPROM starts in a flash image: after everything else
        return self.size + self.ob_size + self.ext_size + (EXT_STATUS_BYTES if self.ext_size else 0)

    @property
    def ecc_offset(self):
        return self.eeprom_offset + self.eeprom_size

    @property
    def ecc_size(self):
        return self.size // 8 if self.ecc else 0

    @property
    def image_size(self):
        # the external chip's two status registers follow its contents: they are
        # non-volatile, so a power cut leaves them as they were, like the flash
        return self.ecc_offset + self.ecc_size


SLOWEST_START = 6.0     # assume a slow machine until this one has been measured


def hang_limit(seconds, slowest):
    """Wall-clock seconds to wait for `seconds` of emulated time before deciding the
    emulated CPU is stuck (on Renode a locked-up core means RunFor never returns).

    Fifty times the slowest this machine has been seen to run, and never under 30 s.
    Too short calls a slow but healthy device dead, which is a false failure; too long
    only costs time on a device that really is dead. Renode does not run at an even
    pace: in a long run of byte-wide flash programs (MCUboot on the F411, about 390,000
    of them) a healthy emulator was measured taking 27 times its usual time for a second
    of emulated time, at random places, more often in a second run in the same process.
    Twenty times, and a fixed ceiling, called that a lock-up. The worst of that (a slice
    of 450 to 565 s where 20 s is usual) was Renode's clock missing a wake-up, which the
    flash models now prevent (wake_clock); the runner also repeats a hung run before it
    calls the device locked up."""
    return max(30.0, 50 * seconds * slowest)


def find_renode():
    """RENODE_PATH, else renode on PATH, else the one `brickproof setup` installed."""
    exe = os.environ.get("RENODE_PATH") or shutil.which("renode")
    if not exe:
        from brickproof import setup
        exe = setup.installed()
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
        self.uart_sent = 0              # bytes the host has sent to the device, ever
        self.link_budget = None         # bytes the link still carries before it breaks; None: no limit
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

    def run_for(self, seconds, slice_s=1.0):
        """Let `seconds` of emulated time pass. A long wait is made in slices: a core
        that has locked up never returns from a run, and with slices that is noticed
        after one of them, not after the allowance for the whole wait."""
        left = seconds
        while left > 0:
            step = min(left, slice_s)
            t0 = time.time()
            try:
                self.cmd(self._run_cmd(step), timeout=self.hang_limit(step))
            except TimeoutError:
                raise MachineHung("emulated time stopped advancing") from None
            if step >= 0.05:
                # learn how slow this machine really is; only ever towards "slower"
                self._slowest = max(self._slowest, (time.time() - t0) / step)
            self.virtual_time += step
            left -= step
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
        received byte, so a burst would overrun it, as on hardware.

        With a link budget set (a broken link, see runner.run_link), only that many more
        bytes reach the device; the rest are lost, as when the cable comes out."""
        self.uart_sent += len(data)
        if self.link_budget is not None:
            data, self.link_budget = data[:self.link_budget], max(0, self.link_budget - len(data))
            if not data:
                return
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

    def read_unit(self, addr, size):
        """`size` bytes at addr as a number, least significant byte first."""
        return int.from_bytes(self.read_bytes(addr, size), "little")

    def write_unit(self, addr, value, size, name="unit.bin"):
        """Change `size` bytes of flash from outside, and tell the flash model."""
        if self.flash.external(addr):
            self.ext_load(value.to_bytes(size, "little"), addr - self.flash.ext_base, name)
            return
        if self.flash.eeprom(addr):
            self.ee_load(value.to_bytes(size, "little"), addr - self.flash.eeprom_base, name)
            return
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(value.to_bytes(size, "little"))
        self.cmd_batch(["sysbus LoadBinary @%s 0x%X" % (name, addr), self._set(REG_RESYNC, 1)])

    def write_word(self, addr, value):
        self.cmd("sysbus WriteDoubleWord 0x%X 0x%X" % (addr, value))

    def load_binary(self, rel_path, addr):
        """Put a file straight into memory. Path is relative to the work folder. The
        flash model is told, in case the file went into flash."""
        if self.flash.external(addr):
            self.cmd('%s LoadAt "%s" 0x%X' % (self._ext, self._path(rel_path), addr - self.flash.ext_base))
            return
        if self.flash.eeprom(addr):
            self.cmd('%s LoadAt "%s" 0x%X' % (self._ee, self._path(rel_path), addr - self.flash.eeprom_base))
            return
        self.cmd_batch(["sysbus LoadBinary @%s 0x%X" % (rel_path, addr), self._set(REG_RESYNC, 1)])

    # ---- the external flash chip ------------------------------------------------

    @property
    def _ext(self):
        return "sysbus.%s.extflash" % self.flash.ext_bus

    def _path(self, name):
        """A work-folder file as the chip model wants it: a full path with forward slashes."""
        return os.path.abspath(os.path.join(self.workdir, name)).replace("\\", "/")

    @property
    def _ee(self):
        return "sysbus.%s.eeprom" % self.flash.eeprom_bus

    def ee_dump(self, name="ee_dump.bin"):
        """Everything in the I2C EEPROM."""
        self.cmd('%s SaveTo "%s"' % (self._ee, self._path(name)))
        with open(os.path.join(self.workdir, name), "rb") as f:
            return f.read()

    def ee_load(self, data, offset=0, name="ee_load.bin"):
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        self.cmd('%s LoadAt "%s" 0x%X' % (self._ee, self._path(name), offset))

    def ee_mismatch(self, data, offset=0, name="ee_expect.bin"):
        """First address where the EEPROM differs from `data` laid at `offset`, or None."""
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        reply = self.cmd('%s Mismatch "%s" 0x%X' % (self._ee, self._path(name), offset))
        found = re.findall(r"0x[0-9A-Fa-f]+|-?\d+", reply.split(name)[-1])
        at = int(found[-1], 0) if found else -1
        if at >= 1 << 62:
            at = -1
        return None if at < 0 else self.flash.eeprom_base + at

    def ext_dump(self, name="ext_dump.bin"):
        """Everything in the external flash chip."""
        self.cmd('%s SaveTo "%s"' % (self._ext, self._path(name)))
        with open(os.path.join(self.workdir, name), "rb") as f:
            return f.read()

    def ext_status(self):
        """The external chip's status registers as stored: 1 | 2 << 8 | 3 << 16."""
        reply = self.cmd("%s GetStatus" % self._ext)
        return int(re.findall(r"^\s*(0x[0-9A-Fa-f]+|\d+)\s*$", reply, re.M)[-1], 0)

    def ext_load(self, data, offset=0, name="ext_load.bin"):
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        self.cmd('%s LoadAt "%s" 0x%X' % (self._ext, self._path(name), offset))

    def ext_mismatch(self, data, offset=0, name="ext_expect.bin"):
        """First address where the chip differs from `data` laid at `offset`, or None."""
        with open(os.path.join(self.workdir, name), "wb") as f:
            f.write(data)
        reply = self.cmd('%s Mismatch "%s" 0x%X' % (self._ext, self._path(name), offset))
        # the answer is the last number on the reply's own line: 0x... or -1 (as 0xFFFF...)
        found = re.findall(r"0x[0-9A-Fa-f]+|-?\d+", reply.split(name)[-1])
        at = int(found[-1], 0) if found else -1
        if at >= 1 << 62:
            at = -1
        return None if at < 0 else self.flash.ext_base + at

    def read_bytes(self, addr, n):
        """n bytes of memory. Slow, about 100 ms per KB: it comes back as text."""
        if self.flash.external(addr):
            off = addr - self.flash.ext_base
            return self.ext_dump()[off:off + n]
        if self.flash.eeprom(addr):
            off = addr - self.flash.eeprom_base
            return self.ee_dump()[off:off + n]
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
        if self.flash.ext_size:
            image += self.ext_dump() + self.ext_status().to_bytes(EXT_STATUS_BYTES, "little")
        if self.flash.eeprom_size:
            image += self.ee_dump()
        if self.flash.ecc:
            image += self.ecc_map()
        return image

    def ecc_map(self):
        """The ECC map: all sound unless the flash model counts a broken double word, and
        only then read back (128 KB of it takes a while)."""
        if not self.read_word(self._ctl(REG_ECC_BROKEN)):
            return bytes(self.flash.ecc_size)
        return self.read_bytes(ECC_MAP, self.flash.ecc_size)

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
        if f.ecc:
            # before the resync, which counts what is broken in it
            ecc = data[f.ecc_offset:f.ecc_offset + f.ecc_size]
            with open(os.path.join(self.workdir, "ecc_" + name), "wb") as out:
                out.write(ecc if len(ecc) == f.ecc_size else bytes(f.ecc_size))
            lines.append("sysbus LoadBinary @ecc_%s 0x%X" % (name, ECC_MAP))
        self.cmd_batch(lines + [self._set(REG_RESYNC, 1)] + self._clear_checks())
        inner = f.size + f.ob_size
        if f.ext_size and len(data) > inner:
            self.ext_load(data[inner:inner + f.ext_size])
        status = data[inner + f.ext_size:inner + f.ext_size + EXT_STATUS_BYTES]
        if f.ext_size and len(status) == EXT_STATUS_BYTES:
            self.cmd("%s SetStatus 0x%X" % (self._ext, int.from_bytes(status, "little")))
        if f.eeprom_size and len(data) > f.eeprom_offset:
            self.ee_load(data[f.eeprom_offset:f.eeprom_offset + f.eeprom_size])

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
        inner = f.size + f.ob_size
        if addr is None and f.ext_size and len(expected) > inner:
            addr = self.ext_mismatch(expected[inner:inner + f.ext_size])
        if addr is None and f.eeprom_size and len(expected) > f.eeprom_offset:
            addr = self.ee_mismatch(expected[f.eeprom_offset:f.eeprom_offset + f.eeprom_size])
        if addr is None and f.ecc and len(expected) > f.ecc_offset:
            want = expected[f.ecc_offset:f.ecc_offset + f.ecc_size]
            now = self.ecc_map()
            for i in range(min(len(want), len(now))):
                if want[i] != now[i]:
                    return f.base + 8 * i          # the double word whose ECC differs
        return addr

    def image_mismatch(self, data, addr, name="image_expect.bin", whole=False):
        """First address where flash at `addr` differs from `data`, or None if that
        image is exactly what is there."""
        if self.flash.external(addr):
            return self.ext_mismatch(data, addr - self.flash.ext_base)
        if self.flash.eeprom(addr):
            return self.ee_mismatch(data, addr - self.flash.eeprom_base)
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

    def run_until_cut(self, limit, step=0.01, longest=0.16):
        """Advance until the armed cut fires. True if it did within `limit` virtual seconds.
        The steps grow: a cut a few milliseconds in is noticed at once, and one behind a
        second-long sector erase does not cost a hundred round trips to the emulator.
        Looking late is harmless, a cut stops the CPU where it fired."""
        waited = 0.0
        while waited < limit:
            step = min(step, limit - waited)
            t0 = time.time()
            try:
                reply = self.cmd_batch([self._run_cmd(step), self._get(REG_CUT_FIRED)],
                                       timeout=self.hang_limit(step))
            except TimeoutError:
                raise MachineHung("emulated time stopped advancing") from None
            if step >= 0.05:
                # this wait learns the machine's pace too, as run_for does
                self._slowest = max(self._slowest, (time.time() - t0) / step)
            self.virtual_time += step
            waited += step
            if self._values(reply)[-1] == 1:
                self._pull()
                return True
            step = min(step * 2, longest)
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
          pcrop    (count, first address): data reads of proprietary code (STM32F4 PCROP)
        Each is None when clean. A power cycle clears the fault; restore_flash the rest."""
        fa, fpc, n, at, stray, wn, wat, pn, pat = self._values(self.cmd_batch(
            [self._get(REG_FAULT_ADDR), self._get(REG_FAULT_PC), self._get(REG_REFUSED),
             self._get(REG_REFUSED_AT), self._set(REG_AUDIT, 1), self._get(REG_AUDIT),
             self._get(REG_PROTECTED), self._get(REG_PROTECTED_AT),
             self._get(REG_PCROP_READS), self._get(REG_PCROP_AT)]))
        return {"fault": (fa, fpc) if fa else None,
                "refused": (n, at) if n else None,
                "stray": stray or None,
                "protected": (wn, wat) if wn else None,
                "pcrop": (pn, pat) if pn else None}

    def bus_fault(self):
        return self.violations()["fault"]

    def flash_resync(self):
        """Tell the flash model that flash is now what it should be. The model keeps a
        shadow copy that only real flash operations update; anything the engine puts
        into flash itself has to be declared, or it would look like a stray write."""
        self.write_word(self._ctl(REG_RESYNC), 1)

    def _clear_checks(self):
        return [self._set(reg, 0) for reg in (REG_AUDIT, REG_REFUSED, REG_REFUSED_AT, REG_PROTECTED,
                                             REG_PROTECTED_AT, REG_PCROP_READS, REG_PCROP_AT)]

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
                # a trailing @N is how many microseconds the chip spent on the operation,
                # #N how many bytes an erase took where that is not fixed
                us = [int(t[1:]) for t in parts if t.startswith("@")]
                length = [int(t[1:], 16) for t in parts if t.startswith("#")]
                parts = [t for t in parts if t[0] not in "@#"]
                op = {"index": len(ops), "kind": TRACE_KINDS[parts[0]], "addr": int(parts[1], 16)}
                if parts[0] in ("P", "X"):
                    # the number of hex digits says how many bytes the program wrote
                    op["value"] = int(parts[2], 16)
                    op["size"] = len(parts[2].replace("0x", "")) // 2
                if parts[0] == "Q":
                    op["total_us"] = int(parts[2])     # partial erase time on the page so far
                if parts[0] == "X":
                    op["old"] = int(parts[3], 16)
                elif parts[0] == "P?":
                    op["inferred"] = True
                if us:
                    op["us"] = us[0]
                if length:
                    op["length"] = length[0]
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

    def _after_reset(self):
        """What a reset must be followed by: boot from flash, and the adapter's own lines."""
        return ["cpu VectorTableOffset 0x%X" % self.vector_table] + list(self.reset_cmds)

    def _reset_lines(self):
        return ["machine Reset"] + self._after_reset()

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
                        self._set(REG_FAULT_PC, 0), self._set(REG_PENDING, 0),
                        # the PWR model's wake flags and pending wake (models/stm32_pwr.py):
                        # a power-on reset clears them
                        "sysbus WriteDoubleWord 0x%X 0" % (STATE_PWR_FLAGS),
                        "sysbus WriteDoubleWord 0x%X 0" % (STATE_PWR_ASLEEP)]
                       + (["%s PowerCycle" % self._ext] if self.flash.ext_size else [])
                       + self._reset_lines()
                       # the reset just made is the power-up itself, not one to count
                       + ["sysbus WriteDoubleWord 0x%X 0" % STATE_RESETS])
        self.rx.clear()
        if settle:
            self.run_for(settle)

    def resets(self):
        """How many times the machine has reset since the last power cycle: the firmware
        asking for one, a watchdog, a lock-up. A device that keeps counting is in a loop."""
        return self.read_word(STATE_RESETS)

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

    def __init__(self, session, timeout=20, step=0.01, longest=0.08):
        self.s = session
        self.timeout = timeout
        self.step = step
        self.longest = longest

    def write(self, data):
        self.s.uart_write(bytes(data))

    def read(self, n):
        # the steps grow while nothing arrives: a prompt answer is read at once, and a
        # device that stays silent does not cost a round trip to the emulator every 10 ms
        waited, step = 0.0, self.step
        while len(self.s.rx) < n and waited < self.timeout:
            step = min(step, self.timeout - waited)
            self.s.run_for(step)
            waited += step
            step = min(step * 2, self.longest)
        out = bytes(self.s.rx[:n])
        del self.s.rx[:n]
        return out

    def sleep(self, seconds):
        """Host tools wait through this, so a wait advances emulated time, not real time."""
        self.s.idle(seconds)

    def close(self):
        pass
