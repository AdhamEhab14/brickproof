"""Emulated time, and the UART that moves with it: runs in slices, the hang limit, the
core's state checked on every slice, and samples of where the CPU is."""
import time
from brickproof.engine.common import MachineHung, hang_limit




class Clock:
    """One part of RenodeSession (engine/session.py): what the module docstring says."""

    def _run_cmd(self, seconds):
        # RunFor wants fixed-point text; scientific notation is rejected
        return 'emulation RunFor "%.7f"' % seconds

    def hang_limit(self, seconds):
        """How long, in wall-clock seconds, to wait for `seconds` of emulated time before
        calling the CPU stuck."""
        return hang_limit(seconds, self._slowest)

    # A Cortex-M core runs in Thumb state only: its xPSR's T bit is always set, and an
    # attempt to run without it is a fault. Firmware that jumps through an erased vector
    # (0xFFFFFFFF) is such a fault on the chip, which then sits in its fault handler: a
    # dead device. Renode instead may take the jump as an exception return and carry on
    # with T clear, either stopping (RunFor never returns) or crawling at a few hundred
    # times its usual pace through code it can no longer run. Which one, and whether a
    # crawling slice passes the wall-clock hang limit, depends on the machine, so the same
    # cut gave "locked up" on one runner and something else 20 minutes later on another.
    # Every slice of emulated time reads the T bit as well, in the same monitor line, and
    # a core without it is locked up at once (docs/decisions/0094).
    CHECK_STATE = "cpu CPSR"

    THUMB = 1 << 24

    def _check_state(self, cpsr):
        if not cpsr & self.THUMB:
            raise MachineHung("the core left Thumb state (xPSR 0x%08X): on a Cortex-M a fault" % cpsr)

    def run_for(self, seconds, slice_s=1.0):
        """Let `seconds` of emulated time pass. A long wait is made in slices: a core
        that has locked up never returns from a run, and with slices that is noticed
        after one of them, not after the allowance for the whole wait."""
        left = seconds
        while left > 0:
            step = min(left, slice_s)
            t0 = time.time()
            try:
                reply = self.cmd_batch([self._run_cmd(step), self.CHECK_STATE],
                                       timeout=self.hang_limit(step))
            except TimeoutError:
                raise MachineHung("emulated time stopped advancing") from None
            # before the pace is learned: a slice spent crawling is not the machine's pace
            self._check_state(self._values(reply)[-1])
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
        for i in range(1, 2 * n, 2):
            self._check_state(values[i])
        return [(values[i], values[i + 1] & 0x1FF) for i in range(0, 2 * n, 2)]
