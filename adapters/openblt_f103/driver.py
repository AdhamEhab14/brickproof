"""Driver for OpenBLT: programs the demo program over the UART with OpenBLT's XCP.

A packet on the wire is one length byte and then that many bytes. The session is the
one OpenBLT's own host tools run: connect, program start, clear the program's flash,
program it block by block, an empty program packet to finish (the bootloader then
writes its checksum, which is what makes the program startable), and a reset.

There is no old image to fall back to: a cut leaves the program erased or half
written, and the bootloader is expected to refuse to start it and to wait for a new
session. So "recovered" here means: the bootloader answers, and a complete new session
after the cut ends with the program running.
"""
import os
import struct
import subprocess

CONNECT, SET_MTA = 0xFF, 0xF6
PROGRAM_START, PROGRAM_CLEAR, PROGRAM, PROGRAM_RESET, PROGRAM_MAX = 0xD2, 0xD1, 0xD0, 0xCF, 0xC9
OK = 0xFF
CHECKSUM_AT = 0x10C             # BOOT_FLASH_VECTOR_TABLE_CS_OFFSET in the demo's blt_conf.h


def read_srec(path):
    """An S-record file as (first address, bytes); gaps are filled with 0xFF."""
    chunks = {}
    for line in open(path):
        kind = line[:2]
        if kind not in ("S1", "S2", "S3"):
            continue
        raw = bytes.fromhex(line[2:].strip())
        width = {"S1": 2, "S2": 3, "S3": 4}[kind]
        addr = int.from_bytes(raw[1:1 + width], "big")
        chunks[addr] = raw[1 + width:-1]
    first = min(chunks)
    last = max(a + len(d) for a, d in chunks.items())
    image = bytearray(b"\xFF" * (last - first))
    for addr, data in chunks.items():
        image[addr - first:addr - first + len(data)] = data
    return first, bytes(image)


class OpenBltUart:
    def __init__(self, session, adapter):
        self.s = session
        opt = adapter.driver_options
        self.baud = int(opt.get("baud", 57600))
        self.base, self.program = read_srec(os.path.join(adapter.target, opt["program"]))
        self.cto = 8
        self.failed = ""
        self.started_incomplete = False
        # the bootloader as raw bytes, for the oracle
        elf = adapter.firmware[0][0]
        if not os.path.exists(elf + ".bin"):
            subprocess.check_call(["arm-none-eabi-objcopy", "-O", "binary", elf, elf + ".bin"])

    # ---- the wire ----------------------------------------------------------------

    def _send(self, payload):
        self.s.rx.clear()
        self.s.uart_write(bytes([len(payload)]) + bytes(payload), baud=self.baud)

    def _reply(self, seconds=1.0):
        """The next packet, or None if nothing complete arrives in time."""
        waited, step = 0.0, 0.002
        while waited < seconds:
            rx = self.s.rx
            if rx and len(rx) > rx[0]:
                return bytes(rx[1:1 + rx[0]])
            self.s.run_for(step)
            waited += step
            step = min(step * 2, 0.05)
        return None

    def _command(self, payload, seconds=1.0):
        self._send(payload)
        r = self._reply(seconds)
        return bool(r) and r[0] == OK, r

    def _connect(self, tries=8):
        """The bootloader listens for 500 ms after a reset before it starts the program,
        and a running program answers a connect by resetting into the bootloader. So
        ask a few times."""
        for _ in range(tries):
            ok, r = self._command([CONNECT, 0], seconds=0.3)
            if ok and r and len(r) >= 4:
                self.cto = r[3]
                return True
        return False

    def _session(self):
        """One complete programming session. Returns "" or what went wrong."""
        if not self._connect():
            return "no answer to connect"
        if not self._command([PROGRAM_START])[0]:
            return "program start refused"
        self._command([SET_MTA, 0, 0, 0] + list(struct.pack("<I", self.base)))
        if not self._command([PROGRAM_CLEAR, 0, 0, 0] + list(struct.pack("<I", len(self.program))),
                             seconds=10)[0]:
            return "clearing the flash failed"
        if not self._command([SET_MTA, 0, 0, 0] + list(struct.pack("<I", self.base)))[0]:
            return "set address refused"
        data, n = self.program, self.cto - 1
        whole = len(data) - len(data) % n
        for i in range(0, whole, n):
            if not self._command([PROGRAM_MAX] + list(data[i:i + n]), seconds=3)[0]:
                return "programming failed at offset 0x%X" % i
        rest = data[whole:]
        if rest and not self._command([PROGRAM, len(rest)] + list(rest), seconds=3)[0]:
            return "programming the last bytes failed"
        if not self._command([PROGRAM, 0], seconds=5)[0]:
            return "finishing (the checksum write) failed"
        self._send([PROGRAM_RESET])
        return ""

    # ---- what BrickProof calls -----------------------------------------------------

    def prepare(self):
        """The device as shipped: the program installed once, by a real session."""
        why = self._session()
        if why:
            raise RuntimeError("could not install the program in the first place: " + why)
        self.s.run_for(1.0)

    def start_update(self):
        self.failed = self._session()

    def alive(self):
        """First look without touching anything: once the 500 ms in which the bootloader
        listens are over, is it running a program that is not the complete one? Then
        ask the bootloader to answer."""
        self.s.run_for(1.0)
        pc = self.s.pc() or 0
        complete = self.s.image_mismatch(self.oracle_images()["program"][0], self.base) is None
        self.started_incomplete = pc >= self.base and not complete
        if self._connect():
            return True
        # A program that is running but broken does not answer. A host tool then does
        # what the manual says: reset the board and connect while the bootloader listens.
        self.s.power_cycle(settle=0.02)
        return self._connect()

    def oracle_images(self):
        """The program as it sits in flash once a session has finished: the bytes of
        the S-record file, plus the checksum the bootloader adds: the two's complement
        of the sum of the first seven vector table entries."""
        image = bytearray(self.program)
        vectors = struct.unpack("<7I", image[:28])
        image[CHECKSUM_AT:CHECKSUM_AT + 4] = struct.pack("<I", (-sum(vectors)) & 0xFFFFFFFF)
        return {"program": (bytes(image), self.base)}

    def check_recovered(self):
        """The bootloader must take a whole new session, and the program must run."""
        if self.started_incomplete:
            return False, ("the bootloader started a program that is not completely written: "
                           "its checksum was in flash before the rest of the program")
        why = self._session()
        if why:
            return False, "a new programming session after the cut failed: " + why
        self.s.run_for(1.5)             # the reset, the 500 ms the bootloader listens, the start
        pc = self.s.pc()
        if pc is None or not self.base <= pc < self.base + len(self.program):
            return False, "after reprogramming the program is not running (PC 0x%08X)" % (pc or 0)
        return True, ""


def make_driver(session, adapter):
    return OpenBltUart(session, adapter)
