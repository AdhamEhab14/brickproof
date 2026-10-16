"""Drive one m33mu instance, as RenodeSession drives Renode.

m33mu (https://github.com/danielinux/m33mu) emulates Cortex-M33 chips Renode does not
have, STM32H5 among them. It is started with --no-realtime, so virtual time runs as
fast as the host allows and only while BrickProof lets it, and with its GDB server,
whose monitor commands do what the flash models' test registers do under Renode:
count flash operations, cut the power just before one, trace them, save and load
the whole flash, cycle the power, and keep a UART inside the emulator. They are
described in m33mu's docs/gdb-monitor.md.

What differs from Renode, and why the engine does not notice:

  a cut lands exactly before its operation, in the chip's flash controller, so a
    program is never half applied and never needs putting back (no "rewound");
  every store to flash goes through the controller, so there are no stray writes,
    and flash_resync has nothing to do;
  memory the chip does not have faults inside m33mu as on silicon, so the oracle
    sees the fault handler and there is no separate fault latch;
  option bytes are not part of the flash image. m33mu keeps them by name; they are
    read when the machine comes up and set back with every restore_flash, so each
    run starts from the device as shipped.

m33mu names flash by the chip's secure alias (0x0C000000 on an STM32H5). An adapter
may use either alias; addresses are translated at this boundary.
"""
import os
import socket
import subprocess
import time

from brickproof.engine.session import (CUT_ERASE, CUT_PROGRAM, TRACE_KINDS, MachineHung,
                                       SLOWEST_START, _live, free_port, hang_limit)

GDB_PC, GDB_XPSR = 0x0F, 0x10


def find_m33mu():
    import shutil
    return os.environ.get("M33MU_PATH") or shutil.which("m33mu")


class M33muError(RuntimeError):
    pass


class Gdb:
    """The part of the GDB remote protocol a harness needs: monitor commands,
    continue, registers and memory."""

    def __init__(self, port, wait):
        end = time.time() + wait
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                if time.time() > end:
                    raise
                time.sleep(0.05)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _packet(self, timeout):
        self.sock.settimeout(timeout)
        while True:
            start = self.buf.find(b"$")
            if start >= 0:
                end = self.buf.find(b"#", start)
                if end >= 0 and len(self.buf) >= end + 3:
                    payload = self.buf[start + 1:end]
                    self.buf = self.buf[end + 3:]
                    self.sock.sendall(b"+")
                    return payload.decode(errors="replace")
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise TimeoutError("m33mu did not answer within %.0f s" % timeout) from None
            if not chunk:
                raise M33muError("m33mu closed the connection")
            self.buf += chunk

    def send(self, payload):
        data = payload.encode()
        self.sock.sendall(b"$" + data + b"#%02x" % (sum(data) & 0xFF))

    def request(self, payload, timeout=60):
        """Send a packet and return its reply, skipping console output and the
        stop replies m33mu sends unasked (one when a client connects)."""
        self.send(payload)
        while True:
            reply = self._packet(timeout)
            if reply[:1] in ("S", "T") or (reply.startswith("O") and reply != "OK"):
                continue
            return reply

    def monitor(self, text, timeout=60):
        """Run a monitor command; return its console output or raise."""
        self.send("qRcmd," + text.encode().hex())
        out = ""
        while True:
            reply = self._packet(timeout)
            if reply.startswith("O") and reply != "OK":
                out += bytes.fromhex(reply[1:]).decode(errors="replace")
                continue
            if reply[:1] in ("S", "T"):
                continue
            if reply == "OK":
                return out
            raise M33muError("m33mu rejected 'monitor %s': %s" % (text, out.strip() or reply))

    def cont(self, timeout):
        """Continue until the core stops; return the stop reply."""
        self.send("c")
        while True:
            reply = self._packet(timeout)
            if reply.startswith("O") and reply != "OK":
                continue
            return reply

    def register(self, num):
        reply = self.request("p%x" % num)
        return int.from_bytes(bytes.fromhex(reply), "little")

    def read_memory(self, addr, n):
        out = b""
        while len(out) < n:
            k = min(0x200, n - len(out))
            reply = self.request("m%x,%x" % (addr + len(out), k))
            if reply.startswith("E") or len(reply) != 2 * k:
                raise M33muError("m33mu could not read 0x%X bytes at 0x%08X" % (k, addr + len(out)))
            out += bytes.fromhex(reply)
        return out

    def write_memory(self, addr, data):
        for i in range(0, len(data), 0x200):
            chunk = data[i:i + 0x200]
            if self.request("M%x,%x:%s" % (addr + i, len(chunk), chunk.hex())) != "OK":
                raise M33muError("m33mu could not write 0x%X bytes at 0x%08X" % (len(chunk), addr + i))


class M33muSession:
    """One emulated machine on m33mu, with the methods the runner, the oracle and the
    drivers use on a RenodeSession.

    workdir    folder holding the firmware files (paths in `firmware` are relative to it)
    firmware   list of (relative path, address or None); ELFs load at their own addresses
    cpu        m33mu's name for the chip (--cpu)
    uart       base address of the UART the firmware prints on
    optbytes   {name: value} set before the device first boots (--optbyte)
    """

    STARTUP_WAIT = 20
    QUIT_WAIT = 10
    TRACE_NAME = "trace.txt"

    def __init__(self, exe, workdir, flash, firmware, cpu, uart, optbytes=None,
                 vector_table=None, log=None):
        self.exe = exe
        self.workdir = workdir
        self.flash = flash
        self.firmware = list(firmware)
        self.cpu = cpu
        self.uart_base = uart
        self.optbytes = dict(optbytes or {})
        self.vector_table = vector_table
        self.log = log
        self.virtual_time = 0.0
        self.rx = bytearray()
        self.uart_sent = 0              # bytes the host has sent to the device, ever
        self.link_budget = None         # bytes the link still carries before it breaks; None: no limit
        self._slowest = SLOWEST_START
        self._dump = None               # the flash as last saved, until something can change it
        self._start()

    # ---- process ----------------------------------------------------------

    def _args(self):
        args = [self.exe, "--cpu", self.cpu, "--gdb", "--port", str(self.port), "--no-realtime",
                "--flash-timing", ("none", "typical", "max")[self.flash.timing]]
        for name, value in self.optbytes.items():
            args += ["--optbyte", "%s=0x%X" % (name, value)]
        if self.vector_table is not None and self.vector_table != self.flash.base:
            args.append("--boot-offset=0x%X" % (self.vector_table - self.flash.base))
        for rel, addr in self.firmware:
            path = os.path.join(self.workdir, rel)
            if rel.lower().endswith((".elf", ".hex", ".uf2")):
                args.append(path)
            else:
                args.append("%s:0x%X" % (path, addr - self.flash.base))
        return args

    def _start(self):
        _live.add(self)
        try:
            self._bring_up()
        except BaseException:
            self.close()
            raise

    def _bring_up(self):
        self.port = free_port()
        out = open(self.log, "ab") if self.log else open(os.path.join(self.workdir, "m33mu.log"), "wb")
        self.proc = subprocess.Popen(self._args(), cwd=self.workdir, stdin=subprocess.DEVNULL,
                                     stdout=out, stderr=subprocess.STDOUT)
        out.close()
        try:
            self.gdb = Gdb(self.port, self.STARTUP_WAIT)
        except OSError:
            self.proc.poll()
            raise M33muError("m33mu did not start%s" % self._why()) from None
        # an m33mu without the harness commands answers unknown monitor commands with a
        # bare OK, so ask for something that must print
        if not self.gdb.monitor("vtime").startswith("vtime "):
            raise M33muError("%s is too old for BrickProof: it needs --no-realtime and the GDB "
                             "monitor commands for test harnesses (m33mu 23960ed or later)" % self.exe)
        info = self.gdb.monitor("flash info").split()
        self.mbase, msize = int(info[1], 16), int(info[2], 16)
        if msize != self.flash.size:
            raise M33muError("flash is 0x%X on m33mu's %s, the adapter says 0x%X"
                             % (msize, self.cpu, self.flash.size))
        self.gdb.monitor("uart attach 0x%X" % self.uart_base)
        # the option bytes as the device ships: every restore goes back to them
        self.shipped_optbytes = {}
        for line in self.gdb.monitor("optbytes").splitlines():
            parts = line.split()
            if len(parts) == 2:
                self.shipped_optbytes[parts[0]] = int(parts[1], 16)

    def _why(self):
        """What m33mu printed before it died, for the error message."""
        if self.proc.returncode is None:
            return ""
        path = self.log or os.path.join(self.workdir, "m33mu.log")
        try:
            with open(path, errors="replace") as f:
                tail = f.read()[-400:].strip()
        except OSError:
            tail = ""
        if "unknown option" in tail:
            return (": %s is too old for BrickProof (it needs --no-realtime; m33mu 23960ed or "
                    "later)" % self.exe)
        return " (exit %d): %s" % (self.proc.returncode, tail)

    def restart(self):
        """Throw this m33mu away and start a fresh one with the same machine."""
        self.close()
        self.rx.clear()
        self._dump = None
        self._start()

    def close(self):
        _live.discard(self)
        gdb = self.__dict__.pop("gdb", None)
        if gdb is not None:
            try:
                gdb.send("qRcmd," + b"quit".hex())
            except OSError:
                pass
            gdb.close()
        proc = self.__dict__.pop("proc", None)
        if proc is None:
            return
        try:
            proc.wait(timeout=self.QUIT_WAIT)
        except Exception:
            proc.kill()
            proc.wait(timeout=10)

    # ---- addresses --------------------------------------------------------

    def _to_m(self, addr):
        return addr - self.flash.base + self.mbase

    def _from_m(self, addr):
        return addr - self.mbase + self.flash.base

    def _in_flash(self, addr):
        return self.flash.base <= addr < self.flash.base + self.flash.size

    # ---- time and UART ----------------------------------------------------

    def hang_limit(self, seconds):
        return hang_limit(seconds, self._slowest)

    def _run(self, seconds):
        """Let up to `seconds` of virtual time pass; stops early at a cut."""
        self._dump = None
        us = max(1, int(round(seconds * 1e6)))
        t0 = time.time()
        self.gdb.monitor("run-for %d" % us)
        try:
            # A core that locks up (a fault while handling a fault) stops with SIGSEGV
            # or SIGILL and stays halted until the next power cycle, as on silicon: to
            # the runner that is a device that says nothing and does not run its image
            self.gdb.cont(self.hang_limit(seconds))
        except TimeoutError:
            raise MachineHung("emulated time stopped advancing") from None
        except (OSError, M33muError):
            raise MachineHung("m33mu went away: %s" % self._why().lstrip(": ")) from None
        self.gdb.monitor("run-for off")
        if seconds >= 0.05:
            self._slowest = max(self._slowest, (time.time() - t0) / seconds)
        self.virtual_time += seconds
        self._pull()

    def run_for(self, seconds):
        self._run(seconds)

    def idle(self, seconds, mips=None):
        """Renode slows its CPU for this; m33mu needs nothing of the kind."""
        self._run(seconds)

    def _pull(self):
        while True:
            fields = self.gdb.monitor("uart read 0x%X" % self.uart_base).split()
            if len(fields) >= 3 and fields[2] != "-":
                self.rx += bytes.fromhex(fields[2])
            if len(fields) < 2 or fields[1] == "0":
                return

    def uart_write(self, data, baud=115200, port=None):
        """Queue bytes for the firmware, then let the time they take on the wire pass.
        With a link budget set (a broken link, see runner.run_link), only that many more
        bytes reach the device, as with RenodeSession."""
        base = self.uart_base if port is None else port
        data = bytes(data)
        self.uart_sent += len(data)
        if self.link_budget is not None:
            data, self.link_budget = data[:self.link_budget], max(0, self.link_budget - len(data))
        for i in range(0, len(data), 128):
            self.gdb.monitor("uart write 0x%X %s" % (base, data[i:i + 128].hex()))
        if data:
            self._run(max(10.0 / baud, 0.0001) * len(data))

    def uart_text(self):
        return self.rx.decode(errors="replace")

    # ---- memory -----------------------------------------------------------

    def _flash_image(self):
        if self._dump is None:
            path = os.path.join(self.workdir, "flash_dump.bin")
            self.gdb.monitor("flash save %s" % path)
            with open(path, "rb") as f:
                self._dump = f.read()
        return self._dump

    def _flash_load(self, image):
        path = os.path.join(self.workdir, "flash_load.bin")
        with open(path, "wb") as f:
            f.write(image)
        self.gdb.monitor("flash load %s" % path)
        self._dump = bytes(image)

    def dump_flash(self):
        """The whole flash image as bytes (option bytes are not part of it)."""
        return self._flash_image()

    def restore_flash(self, data, name=None):
        """Replace the whole flash with `data`, put the option bytes back as shipped and
        forget what the flash checks had seen."""
        self._flash_load(bytes(data[:self.flash.size]))
        for opt, value in self.shipped_optbytes.items():
            self.gdb.monitor("optbytes set %s 0x%X" % (opt, value))
        self.gdb.monitor("flash latches clear")

    def read_bytes(self, addr, n):
        if self._in_flash(addr):
            off = addr - self.flash.base
            return self._flash_image()[off:off + n]
        return self.gdb.read_memory(addr, n)

    def read_unit(self, addr, size):
        return int.from_bytes(self.read_bytes(addr, size), "little")

    def write_unit(self, addr, value, size, name=None):
        self.load_bytes(value.to_bytes(size, "little"), addr)

    def load_bytes(self, data, addr):
        """Put bytes into memory from outside. Into flash, this is a load, not a flash
        operation: nothing is counted or traced."""
        if self._in_flash(addr):
            image = bytearray(self._flash_image())
            off = addr - self.flash.base
            if off + len(data) > self.flash.size:
                raise ValueError("0x%X bytes at 0x%08X run past the end of flash" % (len(data), addr))
            image[off:off + len(data)] = data
            self._flash_load(bytes(image))
        else:
            self.gdb.write_memory(addr, data)

    def load_binary(self, rel_path, addr):
        """Put a file straight into memory. Path is relative to the work folder."""
        with open(os.path.join(self.workdir, rel_path), "rb") as f:
            self.load_bytes(f.read(), addr)

    def flash_mismatch(self, expected, name=None):
        """First address where flash differs from `expected` (a whole-flash image), or None."""
        return self.image_mismatch(expected[:self.flash.size], self.flash.base)

    def image_mismatch(self, data, addr, name=None, whole=False):
        """First address where flash at `addr` differs from `data`, or None."""
        off = addr - self.flash.base
        have = self._flash_image()[off:off + len(data)]
        if have == bytes(data):
            return None
        for i, (a, b) in enumerate(zip(have, data, strict=False)):
            if a != b:
                return addr + i
        return addr + len(have)          # data runs past the end of flash

    def pc(self):
        return self.gdb.register(GDB_PC)

    def sample_cpu(self, n=4, interval=0.02):
        """Let the firmware run and look at the core n times: [(pc, exception number)]."""
        out = []
        for _ in range(n):
            self._run(interval)
            out.append((self.gdb.register(GDB_PC), self.gdb.register(GDB_XPSR) & 0x1FF))
        return out

    # ---- cuts ---------------------------------------------------------------

    def flash_ops(self):
        return int(self.gdb.monitor("flash ops").split()[2])

    def set_cut(self, opcount):
        self.gdb.monitor("flash cut %d" % opcount)

    def set_cut_on_erase(self, page_addr):
        self.gdb.monitor("flash cut erase 0x%X" % self._to_m(page_addr))

    def _cut(self):
        """(fired, kind, address, index) from m33mu."""
        f = self.gdb.monitor("flash cut status").split()
        if f[2] == "none":
            return False, 0, 0, 0
        kind = CUT_PROGRAM if f[3] == "program" else CUT_ERASE
        return True, kind, self._from_m(int(f[4], 16)), int(f[2])

    def cut_fired(self):
        return self._cut()[0]

    def run_until_cut(self, limit, step=None, longest=None):
        """Advance until the armed cut fires. True if it did within `limit` virtual
        seconds. m33mu stops the core at the cut itself, so this is one run."""
        self._run(limit)
        return self.cut_fired()

    def cut_status(self):
        """(kind, page address, operations before it), read after a cut."""
        _fired, kind, addr, index = self._cut()
        return kind, addr, index

    def violations(self):
        """What the firmware did that the chip does not allow, as RenodeSession reports it.
        A fault on memory the chip does not have is a fault inside m33mu, as on silicon,
        and the oracle sees it; there are no stray writes."""
        f = self.gdb.monitor("flash latches").split()
        rn, ra, pn, pa = int(f[3]), int(f[4], 16), int(f[6]), int(f[7], 16)
        return {"fault": None,
                "refused": (rn, self._from_m(ra)) if rn else None,
                "stray": None,
                "protected": (pn, self._from_m(pa)) if pn else None}

    def bus_fault(self):
        return None

    def flash_resync(self):
        """Nothing to do: m33mu sees every change to flash for what it is."""

    # ---- the golden-run trace ---------------------------------------------

    def trace_start(self):
        path = os.path.join(self.workdir, self.TRACE_NAME)
        open(path, "w").close()
        self.gdb.monitor("flash trace %s" % path)

    def trace_stop(self):
        """Stop logging and return the operations, as RenodeSession.trace_stop does."""
        self.gdb.monitor("flash trace off")
        ops = []
        with open(os.path.join(self.workdir, self.TRACE_NAME)) as f:
            for line in f:
                parts = line.split()
                if not parts:
                    continue
                if parts[0] == "B":
                    raise M33muError("the update rewrote the whole flash at once (a bank swap); "
                                     "BrickProof cannot replay that yet")
                us = [int(t[1:]) for t in parts if t.startswith("@")]
                length = [int(t[1:], 16) for t in parts if t.startswith("#")]
                parts = [t for t in parts if t[0] not in "@#"]
                op = {"index": len(ops), "kind": TRACE_KINDS[parts[0]],
                      "addr": self._from_m(int(parts[1], 16))}
                if parts[0] in ("P", "X"):
                    op["value"] = int(parts[2], 16)
                    op["size"] = len(parts[2].replace("0x", "")) // 2
                if parts[0] == "X":
                    op["old"] = int(parts[3], 16)
                if us:
                    op["us"] = us[0]
                if length and length[0] != self.flash.unit_at(op["addr"])[1]:
                    op["length"] = length[0]
                ops.append(op)
        return ops

    # ---- reset and power --------------------------------------------------

    def power_cycle(self, settle=1.5):
        """A real power loss: RAM is lost, flash is kept, everything restarts. Any cut
        still armed is disarmed, as with Renode."""
        self.gdb.monitor("power-cycle")
        self.gdb.monitor("flash cut off")
        self.gdb.monitor("flash latches clear")
        self.rx.clear()
        self._dump = None
        if settle:
            self.run_for(settle)

    def reboot(self, settle=1.5):
        self.gdb.monitor("reset")
        self.rx.clear()
        self._dump = None
        if settle:
            self.run_for(settle)
