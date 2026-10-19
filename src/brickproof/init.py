"""brickproof init: write an adapter by answering a few questions.

Nobody should have to learn the adapter format to try BrickProof. `init` asks what it
cannot find out (which chip, which files, how the update arrives), reads what it can from
the files (where an ELF loads, an MCUboot image's real size), and then boots the firmware
once in the emulator to learn the rest by watching: which UART it talks on, what it prints
when it runs, what it prints once the update is in, and how long the update takes. It
writes the adapter with a comment on every line, checks it, and says what to run next.

Every question has a command-line flag too, so a script (or a test) can answer them all.
"""
import os
import re
import shutil

from brickproof import check as checks
from brickproof import images

# What BrickProof knows about each chip: the questions it does not need to ask.
CHIPS = {
    "stm32f103": dict(label="STM32F103 (Nucleo-F103RB, Blue Pill)", flash_base=0x08000000,
                      flash_size=0x20000, erase="  page: 0x400               # 1 KB pages",
                      ram=0x5000, uarts=("usart2", "usart1", "usart3")),
    "stm32f411": dict(label="STM32F411 (Black Pill, Nucleo-F411RE)", flash_base=0x08000000,
                      flash_size=0x80000,
                      erase="  sectors: [0x4000, 0x4000, 0x4000, 0x4000, 0x10000, 0x20000, "
                            "0x20000, 0x20000]",
                      ram=0x20000, uarts=("usart2", "usart1", "usart6")),
    "stm32l476": dict(label="STM32L476 (Nucleo-L476RG)", flash_base=0x08000000,
                      flash_size=0x100000, erase="  page: 0x800               # 2 KB pages",
                      ram=0x18000, uarts=("usart2", "usart1", "usart3")),
    "nrf52840": dict(label="nRF52840 (nRF52840 DK, Feather)", flash_base=0x0,
                     flash_size=0x100000, erase="  page: 0x1000              # 4 KB pages",
                     ram=0x40000, uarts=("uart0", "uart1")),
    "stm32h563": dict(label="STM32H563 (Nucleo-H563ZI, emulated by m33mu)",
                      flash_base=0x0C000000, flash_size=0x200000, erase=None,
                      ram=0xA0000, ram_base=0x30000000, uarts=("usart3", "usart1", "usart2")),
}

KINDS = {
    "staged": "the bootloader installs a new image that waits in flash, at the next boot "
              "(MCUboot, most OTA designs)",
    "storage": "a flash storage library (key-value store, file system), with a workload "
               "firmware that speaks BrickProof's storage protocol",
    "protocol": "a host sends the update over the UART with its own protocol (you write a "
                "small driver.py; a skeleton is made for you)",
}


class Answers:
    """Where answers come from: the command line first, then a question on the terminal.
    With interactive=False a missing answer is an error, not a question."""

    def __init__(self, given, interactive=True, ask=input, say=print):
        self.given, self.interactive, self.ask, self.say = given, interactive, ask, say

    def get(self, key, question, default=None, check=None):
        value = self.given.get(key)
        while True:
            if value is None:
                if not self.interactive:
                    if default is not None:
                        return default
                    raise ValueError("init: --%s is needed (%s)" % (key.replace("_", "-"), question))
                hint = " [%s]" % default if default is not None else ""
                value = self.ask("%s%s: " % (question, hint)).strip().strip('"') or default
                if value is None:
                    continue
            if check is None:
                return value
            problem = check(value)
            if not problem:
                return value
            if not self.interactive:
                raise ValueError("init: --%s: %s" % (key.replace("_", "-"), problem))
            self.say("  " + problem)
            value = None

    def choose(self, key, question, options):
        """One of `options` ({value: label}), by number or by name."""
        names = list(options)
        if self.given.get(key) is None and self.interactive:
            self.say(question)
            for i, name in enumerate(names, 1):
                self.say("  %d. %s" % (i, options[name]))

        def pick(text):
            if text in options:
                return None
            if text.isdigit() and 1 <= int(text) <= len(names):
                return None
            return "answer with a number from 1 to %d" % len(names)

        text = self.get(key, "your choice", "1" if self.interactive else None, pick)
        return names[int(text) - 1] if text.isdigit() else text


def _number(text):
    try:
        return int(str(text), 0)
    except ValueError:
        return None


def _address(text):
    return None if _number(text) is not None else "an address, for example 0x08020000"


def _file(text):
    return None if os.path.isfile(text) else "no file at %s" % text


def _rel(path, folder):
    try:
        return os.path.relpath(os.path.abspath(path), folder).replace("\\", "/")
    except ValueError:                  # another drive (Windows): no relative path there
        return os.path.abspath(path).replace("\\", "/")


def flash_image(path, flash_base, flash_size):
    """The bytes a firmware file puts in flash, as one image from its lowest flash address:
    (address, bytes). An ELF's segments outside flash (RAM) are left out."""
    data = open(path, "rb").read()
    if not images.is_elf(data):
        return None, data
    segs = [s for s in images.elf_segments(data)
            if flash_base <= s.addr < flash_base + flash_size]
    if not segs:
        raise ValueError("%s loads nothing into flash (0x%08X..0x%08X)"
                         % (path, flash_base, flash_base + flash_size))
    lo, hi = min(s.addr for s in segs), max(s.end for s in segs)
    out = bytearray(b"\xFF" * (hi - lo))
    for s in segs:
        out[s.addr - lo:s.end - lo] = s.data
    return lo, bytes(out)


def _approved(path, folder, name):
    """An image as it must sit in flash once installed: an MCUboot image without the slot
    padding and trailer that come after it (written next to the adapter), else the file."""
    data = open(path, "rb").read()
    found = images.mcuboot_layout(data)
    if not found or found.size == len(data):
        return _rel(path, folder), found
    out = os.path.join(folder, name)
    with open(out, "wb") as f:
        f.write(data[:found.size])
    return name, found


SPECIAL = set(".^$*+?{}[]\\|()")


def literal(text):
    """`text` as a pattern that matches only itself. Only what a pattern reads as special
    is escaped, so 'APP v2' stays readable in the adapter (re.escape would give 'APP\\ v2')."""
    return "".join("\\" + c if c in SPECIAL else c for c in text.strip())


def generalise(line):
    """A pattern for a banner with its numbers left open: 'APP v1' gives 'APP v[0-9]+'."""
    return re.sub(r"[0-9]+", "[0-9]+", literal(line))


def last_line(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def adapter_text(a):
    """The adapter, with a comment on each part, from what init found out (a dict)."""
    chip = CHIPS[a["chip"]]
    out = ["# Written by `brickproof init`. Every key is explained in BrickProof's docs/adapter.md.",
           "# Check it with `brickproof check %s`, run it with `brickproof run %s --full`."
           % (a["file"], a["file"]), "",
           "name: %s" % a["name"],
           "target: .                          # file names below are relative to this folder", "",
           "platform:", "  base: %s" % a["chip"], "",
           "flash:",
           "  base: 0x%08X" % a["flash_base"],
           "  size: 0x%X" % chip["flash_size"]]
    if chip["erase"]:
        out.append(chip["erase"])
    out += ["", "ram:"]
    if chip.get("ram_base"):
        out.append("  base: 0x%08X" % chip["ram_base"])
    out += ["  size: 0x%X                # the chip's real RAM: more would hide stack bugs"
            % chip["ram"], "", "firmware:                          # what the device holds as shipped"]
    for path, addr, note in a["firmware"]:
        out.append("  - file: %s" % path)
        if addr is not None:
            out.append("    addr: 0x%08X" % addr)
        if note:
            out[-1] += "                # " + note
    out += ["", "uart: %s%s" % (a["uart"], "                       # found by watching the firmware boot"
                                if a.get("uart_found") else ""),
            "boot_settle: 0.5", ""]
    if a["kind"] == "staged":
        out += ["driver:", "  builtin: staged_slot", "  options:",
                "    slot: 0x%08X                # where the new image waits" % a["slot"],
                "    image: %s" % a["new"],
                "    alive: %s                     # printed by a running image" % _yaml_str(a["alive"]),
                ]
        if a.get("expect"):
            out.append("    expect: %s                    # printed once the update is in"
                       % _yaml_str(a["expect"]))
        out += ["    boot_timeout: %d" % a["boot_timeout"], ""]
        out += ["# Judged from outside the firmware: after a cut, the bytes at the app's address must",
                "# be exactly one of these images and the CPU must be running inside it.",
                "oracle:", "  images:",
                "    old: {file: %s, at: 0x%08X}" % (a["old_approved"], a["app_at"]),
                "    new: {file: %s, at: 0x%08X}" % (a["new_approved"], a["app_at"]),
                "  accept: [new]                    # a cut must never lose the update", ""]
    elif a["kind"] == "storage":
        out += ["driver:", "  builtin: storage", "  options:", "    keys: 8", "    boot_timeout: 5", "",
                "# the program itself must stay as it is and keep running",
                "oracle:", "  images:",
                "    app: {file: %s, at: 0x%08X}" % (a["app_bin"], a["app_at"]),
                "  accept: [app]", ""]
    else:
        out += ["driver:", "  file: driver.py                  # fill in its TODOs: it speaks your protocol",
                "  options: {}", "",
                "oracle:", "  images:",
                "    bootloader: {file: %s, at: 0x%08X}" % (a["app_bin"], a["app_at"]),
                "  accept: [bootloader]             # add the program once driver.py names it", ""]
    out += ["scenario:",
            "  name: %s" % {"staged": "update", "storage": "storage-workload",
                            "protocol": "update-over-uart"}[a["kind"]],
            "  update_time: %d                   # virtual seconds an uninterrupted update needs"
            % a["update_time"],
            "  cut_limit: %d" % (a["update_time"] + 5),
            "  plan: {mode: phases, per_phase: 4, real_every: auto}"]
    if a["kind"] == "staged":
        out += ["  # damaged versions of the new image: the bootloader must refuse each and keep the",
                "  # old one%s" % (" (MCUboot image: its layout is read from it)"
                                   if a.get("mcuboot") else ""),
                "  content_faults: {keep: old}",
                "  # bits flipped in the installed image while the device is off: it must not run",
                "  bit_errors: {runs: 4}"]
    return "\n".join(out) + "\n"


def _yaml_str(s):
    return "'%s'" % s.replace("'", "''")


DRIVER_SKELETON = '''"""Driver for {name}: sends the update over the UART with its own protocol.

BrickProof calls these methods; fill in the TODOs. adapters/openblt_f103/driver.py in
BrickProof's repository is a complete example of the same shape (about 150 lines).
"""


class Driver:
    def __init__(self, session, adapter):
        self.s = session                    # uart_write(), uart_text(), run_for(), power_cycle()
        self.opt = adapter.driver_options

    def prepare(self):
        """Once: the device as shipped. Often nothing to do."""

    def start_update(self):
        """Send the whole update session, as the real host tool does."""
        raise NotImplementedError("TODO: send the update over the UART")

    def alive(self):
        """True if the device answers (the bootloader) or runs a program."""
        self.s.run_for(1.0)
        return True                         # TODO: ask the bootloader something it answers

    def check_recovered(self):
        """(ok, message) after a cut: usually, a whole new session must work."""
        return True, ""


def make_driver(session, adapter):
    return Driver(session, adapter)
'''


def probe(path, kind, uarts, say=print, settle=2.0, longest=60.0):
    """Boot the adapter's firmware in the emulator and watch it: which UART talks, what
    it prints running, and (staged) what it prints after the update and how long that
    takes. Returns a dict of what was found; empty if the emulator cannot be used."""
    from brickproof import runner
    ad, rep = checks.check(path)
    if ad is None or ad.emulator != "renode":
        return {}
    exe = runner.find_emulator(ad)
    found = {}
    for uart in [ad.uart] + [u for u in uarts if u != ad.uart]:
        ad.uart = uart
        say("  booting it, listening on %s ..." % uart)
        session, work = runner.start_session(ad, exe)
        try:
            session.run_for(settle)
            before = session.uart_text()
            if not before.strip():
                continue
            found.update(uart=uart, before=before)
            if kind != "staged":
                return found
            driver = ad.load_driver(session)
            driver.prepare()                   # the new image into its slot
            session.power_cycle(settle=0)
            t0, last, quiet, ops = 0.0, -1, 0.0, 0
            while t0 < longest:
                session.run_for(0.5)
                t0 += 0.5
                ops = session.flash_ops()
                if ops == last and ops > 0:
                    quiet += 0.5
                    if quiet >= 2.0:
                        break
                else:
                    quiet = 0.0
                last = ops
            found.update(after=session.uart_text(), update_s=max(0.5, t0 - quiet), update_ops=ops)
            return found
        finally:
            session.close()
            shutil.rmtree(work, ignore_errors=True)
    return found


def run(given, interactive=True, ask=input, say=print, probe_device=True):
    """Ask, write, watch, check. Returns the adapter's path, or raises ValueError."""
    q = Answers(given, interactive, ask, say)
    chip = q.choose("chip", "Which chip?", {k: v["label"] for k, v in CHIPS.items()})
    info = CHIPS[chip]
    kind = q.choose("kind", "How does the update happen?", KINDS)
    first = q.get("firmware", "The bootloader file (ELF, or .bin)" if kind != "storage"
                  else "The workload firmware file (ELF)", check=_file)
    out = os.path.abspath(q.get("out", "Where to write the adapter", "brickproof.yaml"))
    folder = os.path.dirname(out)
    os.makedirs(folder, exist_ok=True)
    data = open(first, "rb").read()
    flash_base = info["flash_base"]
    if images.is_elf(data):
        lowest = min(s.addr for s in images.elf_segments(data))
        if chip == "stm32h563" and 0x08000000 <= lowest < 0x0C000000:
            flash_base = 0x08000000             # the H5's non-secure alias
        first_addr = None
    else:
        first_addr = _number(q.get("firmware_at", "Where does %s go in flash"
                                   % os.path.basename(first), "0x%08X" % flash_base, _address))
    a = dict(chip=chip, kind=kind, file=os.path.basename(out), flash_base=flash_base,
             name=re.sub(r"[^a-z0-9_]+", "_", os.path.splitext(os.path.basename(first))[0].lower())
             + "_" + chip, uart=info["uarts"][0], firmware=[(_rel(first, folder), first_addr, None)],
             update_time=10, boot_timeout=10, alive="", expect=None)

    if kind == "staged":
        app = q.get("app", "The app image installed now (the old one)", check=_file)
        a["app_at"] = _number(q.get("app_at", "Where is it in flash (the start of the app slot)",
                                    check=_address))
        a["new"] = _rel(q.get("new", "The new image (the update)", check=_file), folder)
        a["slot"] = _number(q.get("slot", "Where does the new image wait (the staging slot)",
                                  check=_address))
        a["firmware"].append((_rel(app, folder), a["app_at"], "the old image, installed"))
        a["old_approved"], old = _approved(app, folder, "approved_old.bin")
        a["new_approved"], new = _approved(os.path.join(folder, a["new"]), folder, "approved_new.bin")
        a["mcuboot"] = bool(new)
        if new:
            say("  the new image is an MCUboot image of %d bytes%s" % (
                new.size, ", padded to its slot: the approved copy is written next to the adapter"
                if a["new_approved"] == "approved_new.bin" else ""))
    else:
        base, image = flash_image(first, flash_base, info["flash_size"])
        a["app_at"] = base if base is not None else (first_addr or flash_base)
        a["app_bin"] = "approved_firmware.bin"
        with open(os.path.join(folder, a["app_bin"]), "wb") as f:
            f.write(image)
        if kind == "protocol":
            drv = os.path.join(folder, "driver.py")
            if not os.path.exists(drv):
                with open(drv, "w", encoding="utf-8", newline="\n") as f:
                    f.write(DRIVER_SKELETON.format(name=a["name"]))
                say("  wrote driver.py: fill in its TODOs before a run")

    def write():
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(adapter_text(a))

    write()
    if probe_device and kind != "protocol":
        say("Watching the firmware boot in the emulator, to fill in the rest:")
        try:
            seen = probe(out, kind, info["uarts"], say=say)
        except Exception as e:      # noqa: BLE001 - the adapter is still written; say so
            seen = {}
            say("  could not run it (%s); the adapter is written with defaults" % e)
        if seen.get("uart"):
            a["uart"], a["uart_found"] = seen["uart"], True
            say("  it talks on %s: %r" % (seen["uart"], last_line(seen["before"])))
            if kind == "staged":
                old_line, new_line = last_line(seen["before"]), last_line(seen.get("after", ""))
                a["alive"] = generalise(old_line)
                if new_line and new_line != old_line:
                    a["expect"] = literal(new_line)
                    if not re.search(a["alive"], new_line):
                        a["alive"] = ""
                    say("  after the update it prints %r, and the update took %.1f s (%d flash "
                        "operations)" % (new_line, seen["update_s"], seen["update_ops"]))
                else:
                    say("  after the update it prints the same as before, so only the oracle can "
                        "tell the new image from the old")
                a["update_time"] = max(2, int(seen["update_s"] * 1.5 + 1))
                a["boot_timeout"] = a["update_time"]
            elif "READY" not in seen["before"]:
                say("  it did not print READY: a storage workload firmware must speak the protocol "
                    "in BrickProof's src/brickproof/drivers/storage.py")
        elif probe_device:
            say("  it printed nothing on %s: the adapter says nothing about banners, and the "
                "oracle (the installed bytes, where the CPU runs) judges alone"
                % ", ".join(info["uarts"]))
        write()
    _ad, rep = checks.check(out)
    say("")
    say("Wrote %s. The checks:" % _rel(out, os.getcwd()))
    for line in rep.lines():
        say(line)
    # an emulator not installed yet is a step to take, not a fault in the adapter
    missing = [f for f in rep.findings if not f.ok and f.what == "Renode not found"]
    if all(f.ok or f in missing for f in rep.findings):
        if missing:
            say("Next: brickproof setup          (the emulator is not installed yet)")
        say("Next: brickproof run %s --full" % _quote(_rel(out, os.getcwd())))
    return out


def _quote(path):
    return '"%s"' % path if " " in path else path

