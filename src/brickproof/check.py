"""brickproof check: everything about an adapter that can be known without an emulator.

Each check says what it looked at and, when it fails, what to do about it, in words a
first-time user can act on. `run`, `trace` and `export` run the same checks first and stop
before starting an emulator if one fails, so a typo costs a second, not a minute.

The checks, in order; a failure in the first three stops there, the rest are all made:
  the adapter file is where it was said to be
  the YAML reads, and an adapter it extends sits next to it
  BrickProof accepts every key
  every file it names exists
  the firmware fits in the chip's flash, and its stack starts inside the RAM given
  the approved images and the staged update fit in flash
  a damaged-image test's size agrees with the image
  the UART exists on the chip
  the emulator is installed
"""
import os
import re
from dataclasses import dataclass

import yaml

from brickproof import adapter as adapters
from brickproof import images

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "build", "dist", "brickproof-out",
             "__pycache__", ".pytest_cache", ".ruff_cache"}


@dataclass
class Finding:
    ok: bool
    what: str
    fix: str = ""
    warn: bool = False          # worth knowing, but nothing stops a run


class Report:
    def __init__(self):
        self.findings = []

    def ok(self, what):
        self.findings.append(Finding(True, what))

    def fail(self, what, fix=""):
        self.findings.append(Finding(False, what, fix))

    def warn(self, what, fix=""):
        self.findings.append(Finding(True, what, fix, warn=True))

    @property
    def passed(self):
        return all(f.ok for f in self.findings)

    def lines(self, only_failures=False):
        out = []
        for f in self.findings:
            if f.ok and not f.warn and only_failures:
                continue
            out.append("  %-4s  %s" % ("warn" if f.warn else "ok" if f.ok else "FAIL", f.what))
            if f.fix:
                out += ["        fix: " + line if i == 0 else "             " + line
                        for i, line in enumerate(f.fix.splitlines())]
        return out


def _same_name(name, root="."):
    """Files called `name` under `root`, for a 'did you mean' when a path is wrong."""
    hits = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if name in files:
            hits.append(os.path.relpath(os.path.join(folder, name), root))
        if len(hits) >= 5:
            break
    return hits


def _where(path):
    try:
        return os.path.relpath(path)
    except ValueError:              # another drive on Windows
        return path


def _extends_chain(path, rep):
    """Read the adapter and every file it extends; True if all are there and parse."""
    seen = 0
    while True:
        try:
            with open(path) as f:
                d = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            at = " (line %d)" % (mark.line + 1) if mark else ""
            rep.fail("%s is not valid YAML%s: %s" % (_where(path), at, getattr(e, "problem", e)),
                     "Check the indentation there: YAML uses spaces, and keys under a section "
                     "must line up.")
            return False
        if not isinstance(d, dict):
            rep.fail("%s is not an adapter (it is not a list of keys)" % _where(path))
            return False
        parent = d.get("extends")
        if not parent:
            return True
        seen += 1
        if seen > 4:
            rep.fail("%s: 'extends' nests more than 4 deep" % _where(path))
            return False
        nxt = os.path.join(os.path.dirname(path), parent)
        if not os.path.isfile(nxt):
            hits = _same_name(os.path.basename(parent))
            fix = ("An adapter that extends another is read from the same folder as it. "
                   "Put this file next to %s." % parent)
            if hits:
                fix += "\nFound %s at: %s" % (os.path.basename(parent), ", ".join(hits))
            rep.fail("%s extends %s, which is not in its folder (%s)"
                     % (_where(path), parent, _where(os.path.dirname(path)) or "."), fix)
            return False
        path = nxt


def _check_file(rep, label, path, hint):
    if os.path.isfile(path):
        return True
    rep.fail("%s not found: %s" % (label, _where(path)), hint)
    return False


def _memories(ad):
    """The flash an image can be stored in: the chip's own, and an external flash chip or
    an EEPROM beside it (no address on the bus: the adapter's name for their bytes)."""
    f = ad.flash
    out = [(f.base, f.base + f.size, "flash")]
    if f.ext_base is not None and f.ext_size:
        out.append((f.ext_base, f.ext_base + f.ext_size, "external flash"))
    if f.eeprom_base is not None and f.eeprom_size:
        out.append((f.eeprom_base, f.eeprom_base + f.eeprom_size, "EEPROM"))
    return out


def _ranges(ad):
    """Where firmware may legitimately put bytes: the memories above (internal flash with
    its alias at 0 on an STM32) and RAM."""
    f = ad.flash
    out = _memories(ad) + [(ad.ram_base, ad.ram_base + ad.ram_size, "RAM")]
    if f.base == 0x08000000:
        out.append((0, f.size, "flash"))
    return out


def _check_firmware(ad, rep):
    build_hint = ("Build the firmware first, or point --target at the folder it was built in "
                  "(now: %s)." % _where(ad.target))
    stack_checked = False
    for path, addr in ad.firmware:
        if not _check_file(rep, "firmware", path, build_hint):
            continue
        data = open(path, "rb").read()
        name = os.path.basename(path)
        if images.is_elf(data):
            try:
                segs = images.elf_segments(data)
            except ValueError as e:
                rep.fail("%s: %s" % (name, e), "BrickProof loads 32-bit ARM ELF files.")
                continue
        else:
            segs = [images.Segment(addr, data)]
        outside = [s for s in segs
                   if not any(lo <= s.addr and s.end <= hi for lo, hi, _ in _ranges(ad))]
        if outside:
            s = outside[0]
            rep.fail("%s puts bytes at 0x%08X..0x%08X, outside the flash (0x%08X..0x%08X) and RAM "
                     "the adapter gives" % (name, s.addr, s.end, ad.flash.base,
                                            ad.flash.base + ad.flash.size),
                     "Check flash.base and flash.size against the datasheet, and that this file "
                     "is built for this chip%s." % ("" if images.is_elf(data) else
                                                    " and loaded at the right addr"))
        else:
            lo = min(s.addr for s in segs)
            hi = max(s.end for s in segs)
            rep.ok("%s loads at 0x%08X..0x%08X, inside the chip" % (name, lo, hi))
        words = images.first_words(segs, ad.vector_table)
        if words and not stack_checked:
            stack_checked = True
            sp, _ = words
            top = ad.ram_base + ad.ram_size
            if not ad.ram_base < sp <= top:
                rep.fail("%s starts its stack at 0x%08X, outside the %d KB of RAM the adapter gives "
                         "(0x%08X..0x%08X)" % (name, sp, ad.ram_size // 1024, ad.ram_base, top),
                         "Set ram.size to the chip's real RAM (the datasheet's SRAM size). If "
                         "it already is, the firmware was linked for a bigger chip.")
            else:
                rep.ok("%s starts its stack at 0x%08X, inside the %d KB of RAM"
                       % (name, sp, ad.ram_size // 1024))


def _fits(ad, rep, label, path, addr, made_by_driver=False):
    if not os.path.isfile(path) and made_by_driver:
        rep.warn("%s is not there yet: %s" % (label, _where(path)),
                 "Fine if your driver makes it when it starts (OpenBLT's does); otherwise "
                 "build it first.")
        return None
    if not _check_file(rep, label, path, "Build it first, or fix the path in the adapter."):
        return None
    data = open(path, "rb").read()
    where = [m for m in _memories(ad) if m[0] <= addr and addr + len(data) <= m[1]]
    if not where:
        rep.fail("%s (%d bytes at 0x%08X) does not fit in %s" % (
                     label, len(data), addr, " or ".join("%s (0x%08X..0x%08X)" % (n, lo, hi)
                                                         for lo, hi, n in _memories(ad))),
                 "Check the address against the partition layout.")
        return None
    rep.ok("%s fits in %s at 0x%08X (%d bytes)" % (label, where[0][2], addr, len(data)))
    return data


def _check_images(ad, rep):
    for name, (path, addr) in (ad.oracle or {}).get("images", {}).items():
        _fits(ad, rep, "approved image '%s'" % name, path, addr, made_by_driver=bool(ad.driver_file))
    staged = None
    opt = ad.driver_options or {}
    if ad.driver_builtin == "staged_slot" and "image" in opt and "slot" in opt:
        staged = _fits(ad, rep, "staged update", os.path.join(ad.target, opt["image"]), opt["slot"])
    if ad.driver_file:
        _check_file(rep, "driver", ad.driver_file, "Put driver.py next to the adapter.")
    elif ad.driver_builtin:
        here = os.path.join(os.path.dirname(adapters.__file__), "drivers", ad.driver_builtin + ".py")
        if not os.path.isfile(here):
            known = sorted(f[:-3] for f in os.listdir(os.path.dirname(here))
                           if f.endswith(".py") and not f.startswith("_"))
            rep.fail("driver.builtin: no built-in driver '%s'" % ad.driver_builtin,
                     "Built-in drivers: %s." % ", ".join(known))
    cf = ad.content_faults
    if cf and staged is not None:
        found = images.mcuboot_layout(staged)
        size = cf.get("image_size")
        if found and size and size != found.size:
            rep.fail("content_faults.image_size is 0x%X, but the staged image is 0x%X bytes "
                     "(read from its MCUboot header)" % (size, found.size),
                     "Remove image_size and regions from the adapter: BrickProof reads them "
                     "from the image. (An adapter that extends another inherits its numbers, "
                     "and a rebuild changes the size.)")
        elif found and not size:
            rep.ok("damaged-image tests: MCUboot image of 0x%X bytes, layout read from its "
                   "header" % found.size)
        for name, (_start, end) in cf.get("regions", {}).items():
            if end > (size or len(staged)):
                rep.fail("content_faults.regions.%s ends at 0x%X, past the end of the image "
                         "(0x%X)" % (name, end, size or len(staged)),
                         "Remove regions to have them read from the image, or fix them.")
    for name, path in (cf or {}).get("images", {}).items():
        _check_file(rep, "content_faults image '%s'" % name, path, "Fix the path in the adapter.")


def _uart_names(ad):
    """The UARTs the Renode platform defines, or None if that cannot be read here."""
    from brickproof.engine import session
    plat = os.path.join(os.path.dirname(adapters.__file__), "platforms", ad.platform + ".repl")
    try:
        text = open(plat).read()
    except OSError:
        return None
    names = set(re.findall(r"(?m)^(\w+):\s*\S*UART", text))
    using = re.search(r'using "([^"]+)"', text)
    if using:
        exe = session.find_renode()
        if not exe:
            return None
        try:
            names |= set(re.findall(r"(?m)^(\w+):\s*\S*UART",
                                    open(os.path.join(os.path.dirname(exe), using.group(1))).read()))
        except OSError:
            return None
    return names or None


def _check_emulator(ad, rep):
    from brickproof import runner
    try:
        exe = runner.find_emulator(ad)
        rep.ok("%s found: %s" % (ad.emulator, exe))
    except RuntimeError:
        if ad.emulator == "m33mu":
            rep.fail("m33mu not found (the %s is emulated by m33mu)" % ad.platform,
                     "Build m33mu (https://github.com/danielinux/m33mu) and set M33MU_PATH to it.")
        else:
            rep.fail("Renode not found",
                     "Install Renode 1.17 (https://github.com/renode/renode/releases), then tell "
                     "BrickProof where it is.\nWindows PowerShell: [Environment]::SetEnvironmentVariable("
                     "\"RENODE_PATH\", \"C:\\path\\to\\renode.exe\", \"User\"), then open a new "
                     "terminal.\nLinux/macOS: export RENODE_PATH=/path/to/renode")
        return
    if ad.emulator == "renode":
        names = _uart_names(ad)
        if names is not None and ad.uart not in names:
            rep.fail("uart: the %s has no '%s'" % (ad.platform, ad.uart),
                     "Use one of: %s." % ", ".join(sorted(names)))
        elif names is not None:
            rep.ok("uart: %s exists on the %s" % (ad.uart, ad.platform))


def check(path, target=None, emulator=True):
    """(adapter or None, Report)."""
    rep = Report()
    if not os.path.isfile(path):
        hits = _same_name(os.path.basename(path))
        fix = "Check the path and the file name."
        if hits:
            fix = "A file with that name is at: %s" % ", ".join(hits)
            if any(".github" in h for h in hits):
                fix += ("\nAn adapter does not belong in .github/workflows (GitHub would take "
                        "it for a workflow): move it next to the adapter it extends.")
        rep.fail("no adapter at %s" % path, fix)
        return None, rep
    if not _extends_chain(os.path.abspath(path), rep):
        return None, rep
    try:
        ad = adapters.load(path, target=target)
    except adapters.AdapterError as e:
        rep.fail("adapter: %s" % e, "See docs/adapter.md for every key and what it means.")
        return None, rep
    except OSError as e:
        rep.fail("adapter: %s" % e)
        return None, rep
    rep.ok("adapter reads: %s, %s" % (ad.name, ad.platform))
    _check_firmware(ad, rep)
    _check_images(ad, rep)
    if emulator:
        _check_emulator(ad, rep)
    return ad, rep
