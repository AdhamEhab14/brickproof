"""Built-in driver for flash storage libraries: a key-value store or a file system that
must not lose or mangle what it said it had stored, whenever the power goes.

The firmware runs a fixed workload of writes and deletes on its store and talks over the
UART (adapters/zephyr_storage/app/src/main.c is the reference):

  on every boot     MOUNT ok | MOUNT formatted | MOUNT err <rc>
                    R <key> <gen> | R <key> - | R <key> bad | R <key> err <rc>   (each key)
                    READY
  command S         the next step: C <step> W <key> <gen> | C <step> D <key> | E <step> <rc> | Z
  command W         every remaining step the same way, then W end
  command P         write the probe key and read it back: P ok | P err <rc>

Before the campaign the driver runs the workload once, a step at a time, and notes the
flash operation each step starts and ends at. The workload does the same thing every
time, so after a cut before operation N it knows which steps had finished (their values
must be there) and which one was under way (old or new value, either is right). After
each cut it checks:

  - the store still mounts, and was not formatted again (that loses everything);
  - every key holds its last finished value, or the one under way; nothing reads back
    half-written ("bad") or fails to read;
  - the store takes a new write (the probe key), and that write is still there after
    one more power cycle, with every other key unchanged.

Options (adapter.yaml, driver.options):
  keys          how many keys the workload uses, default 8 (the probe key is the next one)
  probe_gen     the generation the probe writes, default 9999
  boot_timeout  virtual seconds to wait for READY, default 5
"""
import re

MOUNT = re.compile(r"(?m)^MOUNT (ok|formatted|err (-?\d+))\r?$")
READ = re.compile(r"(?m)^R (\d+) (-|bad|err -?\d+|\d+)\r?$")
STEP = re.compile(r"^C (\d+) (?:W (\d+) (\d+)|D (\d+))$")
READY = re.compile(r"(?m)^READY\r?$")
BOOTED = re.compile(r"(?m)^(READY|MOUNT err -?\d+)\r?$")


class Step:
    """One workload step: where it starts and ends, in flash operations counted from
    the start of the update, and what it does (write a generation, or delete)."""

    def __init__(self, start, end, key, gen):
        self.start, self.end, self.key, self.gen = start, end, key, gen   # gen None: delete

    def as_list(self):
        return [self.start, self.end, self.key, self.gen]


def parse_step(line):
    """(key, gen) of a 'C' line; gen None for a delete. None if it is not one."""
    m = STEP.match(line.strip())
    if not m:
        return None
    if m.group(4):
        return int(m.group(4)), None
    return int(m.group(2)), int(m.group(3))


def parse_dump(text):
    """{key: value} from a boot's dump: an int generation, None (absent), 'bad', or
    'err <rc>'. The last line for a key wins (a later boot in the same text)."""
    out = {}
    for m in READ.finditer(text):
        v = m.group(2)
        out[int(m.group(1))] = None if v == "-" else int(v) if v.isdigit() else v
    return out


def allowed_values(steps, keys, n):
    """For a cut before operation n: {key: set of values a correct store may hold}.
    A step that ended at or before n has finished: its value must be there. One that
    started and had not ended may have taken effect or not."""
    done = {k: None for k in range(1, keys + 1)}
    under_way = []
    for st in steps:
        if st.end <= n:
            done[st.key] = st.gen
        elif st.start <= n:
            under_way.append(st)
    allowed = {k: {v} for k, v in done.items()}
    for st in under_way:
        allowed[st.key].add(st.gen)
    return allowed


def describe(v):
    return "nothing" if v is None else "generation %d" % v if isinstance(v, int) else v


def check_dump(dump, allowed, probe_key):
    """'' if the dump is what a correct store may hold, else what is wrong."""
    for key in sorted(allowed):
        v = dump.get(key, "no line")
        if v == "bad":
            return "key %d reads back a half-written or mixed-up value" % key
        if isinstance(v, str):
            return "key %d: %s" % (key, "the device did not report it" if v == "no line"
                                   else "reading it fails (%s)" % v)
        if v not in allowed[key]:
            options = sorted(allowed[key], key=lambda a: -1 if a is None else a)
            want = " or ".join(describe(a) for a in options)
            return "key %d holds %s, but the workload had left %s" % (key, describe(v), want)
    if dump.get(probe_key) not in (None, "no line"):
        return "the probe key holds %s before anything wrote it" % describe(dump[probe_key])
    return ""


class Storage:
    update_on_boot = False

    def __init__(self, session, adapter):
        self.s = session
        opt = adapter.driver_options
        self.keys = int(opt.get("keys", 8))
        self.probe_key = self.keys + 1
        self.probe_gen = int(opt.get("probe_gen", 9999))
        self.timeout = float(opt.get("boot_timeout", 5.0))
        self.settle = adapter.boot_settle
        self.steps = None
        self.update_op = None

    def _wait_for(self, pattern, seconds, since=0):
        waited, step = 0.0, 0.05
        while waited < seconds:
            if pattern.search(self.s.uart_text(), since):
                return True
            step = min(step, seconds - waited)
            self.s.run_for(step)
            waited += step
            step = min(step * 2, 0.2)
        return bool(pattern.search(self.s.uart_text(), since))

    def _command(self, c, answer, seconds):
        """Send one command character; the first line after it that matches `answer`."""
        since = len(self.s.uart_text())
        self.s.uart_write(c.encode())
        pat = re.compile(r"(?m)^(%s)\r?$" % answer)
        if not self._wait_for(pat, seconds, since):
            return None
        return pat.search(self.s.uart_text(), since).group(1)

    # ---- before the campaign --------------------------------------------------------

    def prepare(self):
        """Mount the store once (a blank partition is formatted then), which is the state
        every run starts from, and learn where each workload step lies in flash
        operations, booting the same way a run does."""
        if not self._wait_for(BOOTED, self.timeout) or not READY.search(self.s.uart_text()):
            raise RuntimeError("storage: the firmware never said READY on its first boot; it "
                               "printed: %r" % self.s.uart_text()[-300:])
        start_state = self.s.dump_flash()
        self.s.power_cycle(settle=self.settle)
        base = self.s.flash_ops()
        if not self._wait_for(READY, self.timeout):
            raise RuntimeError("storage: no READY on the second boot")
        steps = []
        while True:
            start = self.s.flash_ops() - base
            line = self._command("S", r"C %d .*|E %d .*|Z" % (len(steps), len(steps)), self.timeout)
            if line is None or line.startswith("E"):
                raise RuntimeError("storage: workload step %d %s with no power cut" % (
                    len(steps), "failed (%s)" % line if line else "never finished"))
            if line == "Z":
                break
            key, gen = parse_step(line)
            steps.append(Step(start, self.s.flash_ops() - base, key, gen))
        self.steps = steps
        self.s.restore_flash(start_state)

    def export_state(self):
        return [st.as_list() for st in self.steps]

    def import_state(self, shared):
        self.steps = [Step(*row) for row in shared]

    # ---- one run ------------------------------------------------------------------

    def start_update(self):
        self._wait_for(READY, self.timeout)
        self.s.uart_write(b"W")

    def judging(self, update_op):
        """Which operation of the update the (first) cut fell before; None: all done."""
        self.update_op = update_op

    def alive(self):
        return self._wait_for(BOOTED, self.timeout)

    def check_recovered(self):
        text = self.s.uart_text()
        m = MOUNT.search(text)
        if not m:
            return False, "the firmware did not say whether the store mounted"
        if m.group(2) is not None:
            return False, "the store does not mount any more (%s)" % m.group(2)
        if m.group(1) == "formatted":
            return False, "the store did not mount and was formatted again: everything in it was lost"
        n = self.update_op if self.update_op is not None else float("inf")
        dump = parse_dump(text)
        problem = check_dump(dump, allowed_values(self.steps, self.keys, n), self.probe_key)
        if problem:
            return False, problem
        # the store must take a new write, and keep it
        answer = self._command("P", r"P ok|P err -?\d+", self.timeout)
        if answer != "P ok":
            return False, "after this cut the store does not take a new write (%s)" % (
                answer or "no answer")
        self.s.power_cycle(settle=self.settle)
        if not self._wait_for(READY, self.timeout):
            return False, "after a write made once the cut was over, the store does not mount"
        after = parse_dump(self.s.uart_text())
        if after.get(self.probe_key) != self.probe_gen:
            return False, ("a write the store accepted after this cut is gone on the next boot "
                           "(the probe key holds %s)" % describe(after.get(self.probe_key)))
        for key in range(1, self.keys + 1):
            if after.get(key) != dump.get(key):
                return False, ("key %d changed from %s to %s when only the probe key was written"
                               % (key, describe(dump.get(key)), describe(after.get(key))))
        return True, ""


def make_driver(session, adapter):
    return Storage(session, adapter)
