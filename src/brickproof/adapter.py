"""Target adapters: one YAML file describing the firmware, plus a Python driver.

The YAML says what to load, the flash geometry, how to reset, and where to cut.
The driver knows the target's update protocol (how to stage and start an update,
how to tell the device is alive). See adapters/three_tier_f103/ for an example.
"""
import importlib.util
import os
from dataclasses import dataclass, field

import yaml

from brickproof import bit_errors as bit_errs
from brickproof import content
from brickproof.engine.session import FlashGeometry
from brickproof.torn import KINDS as TORN_KINDS


class AdapterError(ValueError):
    pass


@dataclass
class Cut:
    """One place to pull the plug.

    on_erase  cut just before the erase of this page address starts
    at_op     cut just before flash operation number N, counted from the start
              of the update (0 = its first erase or program)
    expect    optional (kind, address) the cut must land on, as a sanity check
    group     cuts expanded from one at_ops range share a group; once one of them
              finds the update already over, the later ones are skipped
    """
    name: str
    on_erase: int = None
    at_op: int = None
    expect: tuple = None
    group: int = None


@dataclass
class Adapter:
    path: str                     # the YAML file it was read from
    name: str
    folder: str
    target: str
    platform: str
    platform_extra: str
    flash: FlashGeometry
    ram_base: int
    ram_size: int
    firmware: list
    uart: str
    vector_table: int
    mips: int
    reset_cmds: list
    boot_settle: float
    cut_limit: float
    update_time: float            # virtual seconds an uninterrupted update needs
    check_states: bool            # compare flash at each cut with the golden run replayed
    oracle: dict = None           # approved images and which ones a cut may leave (see oracle.py)
    plan: dict = None             # let the planner choose cuts from the golden run (see plan.py)
    torn: list = None             # torn-operation shapes to try at each cut (see torn.py)
    torn_seed: int = 0
    depth: dict = None            # explore cuts during recovery (see runner.explore)
    shard: tuple = None           # (k, n): run only every nth cut, starting with the kth
    soak: tuple = None            # (seconds, seed): random tests until then, instead of the plan
    content_faults: dict = None   # damaged images the bootloader must refuse (see content.py)
    link_cuts: dict = None        # break the host's link mid-session (see runner.run_link)
    bit_errors: dict = None       # bits flipped in a stored image while off (see bit_errors.py)
    hse: int = 8000000            # the board's crystal or external clock, in Hz
    driver_file: str = None       # a driver.py next to the adapter, or
    driver_builtin: str = None    # one that ships with BrickProof
    driver_options: dict = field(default_factory=dict)
    cuts: list = field(default_factory=list)

    def load_driver(self, session):
        """Import the driver module and return its driver object for this session."""
        if self.driver_builtin:
            mod = importlib.import_module("brickproof.drivers." + self.driver_builtin)
        else:
            spec = importlib.util.spec_from_file_location("brickproof_driver_" + self.name, self.driver_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        return mod.make_driver(session, self)


def _protected_ranges(flash, protected):
    """The write_protected entries as checked (where, start, size) tuples."""
    out = []
    for i, r in enumerate(protected):
        where = "flash.write_protected[%d]" % i
        start, size = _need(r, "from", where), _need(r, "size", where)
        if start < flash.base or start + size > flash.base + flash.size or size <= 0:
            raise AdapterError("%s: outside the flash" % where)
        out.append((where, start, size))
    return out


def stm32f1_option_bytes(flash, protected, read_protected, hardware_watchdog=False):
    """The 16 option bytes of an STM32F1 as the chip holds them: RDP, USER, Data0,
    Data1, WRP0..WRP3, each followed by its complement. `protected` is a list of
    {from, size} ranges to write-protect; a cleared WRP bit protects its unit."""
    unit = flash.wrp_unit
    wrp = 0xFFFFFFFF
    for where, start, size in _protected_ranges(flash, protected):
        if (start - flash.base) % unit or size % unit:
            raise AdapterError("%s: write protection goes in units of 0x%X on this chip"
                               % (where, unit))
        for u in range((start - flash.base) // unit, (start - flash.base + size) // unit):
            if u >= 31 and (start - flash.base + size) < flash.size:
                raise AdapterError("%s: the last protection bit covers everything from 0x%08X "
                                   "to the end of flash, all or nothing" % (where, flash.base + 31 * unit))
            wrp &= ~(1 << min(u, 31))
    out = bytearray()
    user = 0xFE if hardware_watchdog else 0xFF      # WDG_SW is bit 0, cleared = hardware
    for data in (0x00 if read_protected else 0xA5, user, 0xFF, 0xFF,
                 wrp & 0xFF, (wrp >> 8) & 0xFF, (wrp >> 16) & 0xFF, (wrp >> 24) & 0xFF):
        out += bytes([data, ~data & 0xFF])
    return bytes(out)


def stm32f4_option_bytes(flash, protected, read_protected, hardware_watchdog=False):
    """The option bytes of an STM32F4 as the chip shows them: USER and RDP in one
    halfword, the nWRP bits in another, each followed by its complement. Write
    protection is one bit per sector, and a cleared bit protects its sector."""
    units = flash.units()
    nwrp = 0xFFF
    for where, start, size in _protected_ranges(flash, protected):
        starts = [u for u, _ in units]
        ends = [u + n for u, n in units]
        if start not in starts or start + size not in ends:
            raise AdapterError("%s: write protection goes by whole sectors on this chip" % where)
        for s in range(starts.index(start), ends.index(start + size) + 1):
            nwrp &= ~(1 << s)
    out = bytearray()
    user = 0xCF if hardware_watchdog else 0xEF      # WDG_SW is bit 5, cleared = hardware
    for half in (((0x55 if read_protected else 0xAA) << 8) | user, 0xF000 | nwrp):
        out += bytes([half & 0xFF, half >> 8, ~half & 0xFF, (~half >> 8) & 0xFF]) + bytes([0xFF]) * 4
    return bytes(out)


def no_option_bytes(flash, protected, read_protected, hardware_watchdog=False):
    """A chip without STM32-style option bytes (the nRF52's UICR is not modelled)."""
    if protected or read_protected or hardware_watchdog:
        raise AdapterError("flash: write_protected, read_protected and hardware_watchdog are "
                           "STM32 option bytes; this chip has none")
    return b""


# What the engine has to know about each chip family it can emulate.
#   model         the flash controller model in models/
#   controller    where that controller sits
#   ob_base       where the option bytes are
#   option_bytes  builds them from an adapter's write_protected / read_protected
#   wrp_unit      how much flash one write-protection bit covers (None: one per sector)
#   write_unit    bytes a program usually writes
#   endurance     erase cycles per page or sector the datasheet promises
#   mips          the core clock in MHz, as the emulator's default speed (72 if not given)
CHIPS = {
    "stm32f103": dict(model="stm32f1_flash.py", controller=0x40022000, ob_base=0x1FFFF800,
                      option_bytes=stm32f1_option_bytes, wrp_unit=0x1000, write_unit=2,
                      endurance=10000),
    "stm32f411": dict(model="stm32f4_flash.py", controller=0x40023C00, ob_base=0x1FFFC000,
                      option_bytes=stm32f4_option_bytes, wrp_unit=None, write_unit=4,
                      endurance=10000),
    "nrf52840": dict(model="nrf52_flash.py", controller=0x4001E000, ob_base=None,
                     option_bytes=no_option_bytes, wrp_unit=None, write_unit=4,
                     endurance=10000, mips=64),
}
PLATFORMS = tuple(CHIPS)

# flash.timing: how long erases and programs take in the emulator
TIMINGS = {"none": 0, "typical": 1, "max": 2}


def _parse_pins(d):
    """`pins: {PC13: high, PA0: low}` as the Renode lines that hold those inputs at
    that level after every reset. An input nothing drives reads low in the emulator,
    which firmware that looks at a button or a strap at start-up takes as pressed."""
    lines = []
    for pin, level in (d.get("pins") or {}).items():
        pin, level = str(pin).upper(), str(level).lower()
        ok = len(pin) >= 3 and pin[0] == "P" and "A" <= pin[1] <= "K" and pin[2:].isdigit() \
            and int(pin[2:]) < 16
        if not ok:
            raise AdapterError("pins: '%s' is not a pin name like PC13" % pin)
        if level not in ("high", "low"):
            raise AdapterError("pins.%s: use high or low, not '%s'" % (pin, level))
        state = "true" if level == "high" else "false"
        lines.append("gpioPort%s OnGPIO %d %s" % (pin[1], int(pin[2:]), state))
    return lines


def _need(d, key, where):
    if key not in d:
        raise AdapterError("%s: missing '%s'" % (where, key))
    return d[key]


def _parse_cuts(i, c):
    """One YAML entry: a single cut, or an at_ops range that expands to many."""
    where = "cuts[%d]" % i
    if not isinstance(c, dict):
        raise AdapterError("%s: expected a mapping" % where)
    if "at_ops" in c:
        r = c["at_ops"]
        lo, hi, step = r.get("from", 0), r.get("to"), r.get("step", 1)
        if hi is None or hi < lo or step < 1:
            raise AdapterError("%s.at_ops: need from <= to and step >= 1" % where)
        return [Cut(name="op-%d" % n, at_op=n, group=i) for n in range(lo, hi + 1, step)]
    return [_parse_cut(where, c)]


def _parse_cut(where, c):
    on_erase, at_op = c.get("on_erase"), c.get("at_op")
    if (on_erase is None) == (at_op is None):
        raise AdapterError("%s: give exactly one of on_erase or at_op" % where)
    expect = None
    if "expect" in c:
        e = c["expect"]
        kind = {"erase": 1, "program": 2}.get(e.get("kind"))
        if kind is None:
            raise AdapterError("%s.expect.kind: use erase or program" % where)
        expect = (kind, e.get("addr", 0))
    default = ("erase-0x%08X" % on_erase) if on_erase is not None else "op-%d" % at_op
    return Cut(name=c.get("name", default), on_erase=on_erase, at_op=at_op, expect=expect)


def _merge(base, over):
    """Mappings merge key by key, anything else (lists included) is replaced."""
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read(path, depth=0):
    with open(path) as f:
        d = yaml.safe_load(f) or {}
    parent = d.pop("extends", None)
    if parent:
        if depth > 4:
            raise AdapterError("%s: 'extends' nests too deep" % path)
        d = _merge(_read(os.path.join(os.path.dirname(path), parent), depth + 1), d)
    return d


def _parse_plan(scenario):
    """scenario.plan: a mode name, or {mode, per_phase, small, real_every}. With
    real_every N only every Nth planned cut is made in the emulator; the others are
    powered up from the computed flash state. None if absent."""
    p = scenario.get("plan")
    if p is None:
        return None
    if isinstance(p, str):
        p = {"mode": p}
    if not isinstance(p, dict):
        raise AdapterError("scenario.plan: give a mode (phases, every) or a mapping")
    unknown = set(p) - {"mode", "per_phase", "small", "real_every"}
    if unknown:
        raise AdapterError("scenario.plan: unknown key(s) %s" % ", ".join(sorted(unknown)))
    mode = p.get("mode", "phases")
    if mode not in ("phases", "every"):
        raise AdapterError("scenario.plan.mode: use phases or every, not %r" % mode)
    out = {"mode": mode}
    for key in ("per_phase", "small", "real_every"):
        if key in p:
            if not isinstance(p[key], int) or p[key] < 0:
                raise AdapterError("scenario.plan.%s: a whole number, 0 or more" % key)
            out[key] = p[key]
    return out


DEPTH_DEFAULTS = {"mode": "phases", "per_phase": 2, "small": 6, "max_states": 2000, "torn": False}
EXHAUSTIVE = 1000000      # "levels: exhaustive": go on until a level finds no new flash state


def _parse_depth(scenario):
    """scenario.depth: how many power cuts in a row to explore. A number, or a mapping
    {levels, mode, per_phase, small, max_states, torn}. With torn, the half-done
    versions of each recovery operation are tried as well (it needs scenario.torn or
    --torn for the shapes). `levels: exhaustive` (or `depth: exhaustive`) goes on until a
    level finds no flash state not already tested, or max_states is reached. None when it
    is 1 or absent."""
    d = scenario.get("depth")
    if d is None:
        return None
    if isinstance(d, (int, str)) and not isinstance(d, bool):
        d = {"levels": d}
    if not isinstance(d, dict):
        raise AdapterError("scenario.depth: a number of cuts in a row, or a mapping")
    unknown = set(d) - {"levels", *DEPTH_DEFAULTS}
    if unknown:
        raise AdapterError("scenario.depth: unknown key(s) %s" % ", ".join(sorted(unknown)))
    out = dict(DEPTH_DEFAULTS, **d)
    out.setdefault("levels", 2)
    if out["levels"] == "exhaustive":
        out["levels"] = EXHAUSTIVE
    if out["mode"] not in ("phases", "every"):
        raise AdapterError("scenario.depth.mode: use phases or every, not %r" % out["mode"])
    for key in ("levels", "per_phase", "small", "max_states"):
        if not isinstance(out[key], int) or isinstance(out[key], bool) or out[key] < 0:
            raise AdapterError("scenario.depth.%s: a whole number, 0 or more" % key)
    if not isinstance(out["torn"], bool):
        raise AdapterError("scenario.depth.torn: true or false")
    if out["levels"] < 1:
        raise AdapterError("scenario.depth.levels: at least 1")
    return out if out["levels"] > 1 else None


def _parse_torn(scenario):
    """scenario.torn: true for every shape, or a list of shape names. None if off."""
    t = scenario.get("torn")
    if not t:
        return None
    if t is True:
        return list(TORN_KINDS)
    if not isinstance(t, list) or any(k not in TORN_KINDS for k in t):
        raise AdapterError("scenario.torn: true, or a list from: %s" % ", ".join(TORN_KINDS))
    return list(t)


def _parse_content(scenario, target, oracle):
    """scenario.content_faults (see content.py), with image paths made absolute. None if off."""
    c = scenario.get("content_faults")
    if not c:
        return None
    if not isinstance(c, dict):
        raise AdapterError("scenario.content_faults: a mapping")
    unknown = set(c) - content.KEYS
    if unknown:
        raise AdapterError("scenario.content_faults: unknown key(s) %s" % ", ".join(sorted(unknown)))
    if not oracle:
        raise AdapterError("scenario.content_faults: needs an oracle, which judges the result")
    keep = _need(c, "keep", "scenario.content_faults")
    if keep not in oracle["images"]:
        raise AdapterError("scenario.content_faults.keep: %r is not one of the oracle's images "
                           "(%s)" % (keep, ", ".join(sorted(oracle["images"]))))
    out = {"keep": str(keep), "image_size": c.get("image_size"),
           "mutations": list(c.get("mutations") or content.MUTATIONS), "regions": {}, "images": {}}
    bad = [m for m in out["mutations"] if m not in content.MUTATIONS]
    if bad:
        raise AdapterError("scenario.content_faults.mutations: use %s, not %s" % (
            ", ".join(content.MUTATIONS), ", ".join(bad)))
    size = out["image_size"]
    if size is not None and (not isinstance(size, int) or size <= 0):
        raise AdapterError("scenario.content_faults.image_size: a number of bytes")
    for name, r in (c.get("regions") or {}).items():
        if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r)
                and 0 <= r[0] < r[1]):
            raise AdapterError("scenario.content_faults.regions.%s: [start, end] offsets" % name)
        out["regions"][str(name)] = (r[0], r[1])
    for name, f in (c.get("images") or {}).items():
        out["images"][str(name)] = os.path.normpath(os.path.join(target, f))
    return out


def _parse_link(scenario):
    """scenario.link_cuts: true, or {points, wait}. None if off."""
    c = scenario.get("link_cuts")
    if not c:
        return None
    out = {"points": 8, "wait": 2.0}
    if c is not True:
        if not isinstance(c, dict) or set(c) - set(out):
            raise AdapterError("scenario.link_cuts: true, or a mapping with points and wait")
        out.update(c)
    if not isinstance(out["points"], int) or out["points"] < 1:
        raise AdapterError("scenario.link_cuts.points: how many places to break the link, 1 or more")
    if not isinstance(out["wait"], (int, float)) or out["wait"] < 0:
        raise AdapterError("scenario.link_cuts.wait: seconds the link stays down")
    out["wait"] = float(out["wait"])
    return out


def _parse_bit_errors(scenario, oracle):
    """scenario.bit_errors (see bit_errors.py): true, or a mapping. None if off."""
    c = scenario.get("bit_errors")
    if not c:
        return None
    if not oracle:
        raise AdapterError("scenario.bit_errors: needs an oracle, which judges the result")
    c = {} if c is True else c
    if not isinstance(c, dict) or set(c) - bit_errs.KEYS:
        raise AdapterError("scenario.bit_errors: true, or a mapping with %s"
                           % ", ".join(sorted(bit_errs.KEYS)))
    out = {"flips": c.get("flips", 1), "runs": c.get("runs", 4), "seed": c.get("seed", 0), "regions": None}
    for key in ("flips", "runs"):
        if not isinstance(out[key], int) or out[key] < 1:
            raise AdapterError("scenario.bit_errors.%s: a whole number, 1 or more" % key)
    if c.get("regions"):
        out["regions"] = {}
        for name, r in c["regions"].items():
            if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r)
                    and r[0] < r[1]):
                raise AdapterError("scenario.bit_errors.regions.%s: [start, end] addresses" % name)
            out["regions"][str(name)] = (r[0], r[1])
    return out


def _parse_oracle(d, target):
    """The `oracle:` section, with image paths made absolute. None if there is none."""
    o = d.get("oracle")
    if not o:
        return None
    images = {}
    for name, spec in (o.get("images") or {}).items():
        where = "oracle.images.%s" % name
        path = os.path.normpath(os.path.join(target, _need(spec, "file", where)))
        images[str(name)] = (path, _need(spec, "at", where))
    accept = [str(a) for a in _need(o, "accept", "oracle")]
    if not accept:
        raise AdapterError("oracle.accept: name at least one image")
    run_in = o.get("run_in")
    if run_in is not None:
        run_in = (_need(run_in, "start", "oracle.run_in"), _need(run_in, "end", "oracle.run_in"))
        if run_in[0] >= run_in[1]:
            raise AdapterError("oracle.run_in: start must be below end")
    return {"images": images, "accept": accept, "run_in": run_in,
            "samples": int(o.get("samples", 4)), "interval": float(o.get("interval", 0.02))}


def load(path, target=None):
    """Read an adapter YAML. `target` overrides the firmware project folder it names.

    `extends: other.yaml` starts from another adapter and changes only what this
    file says. Relative paths resolve against this file's folder, so keep the two
    side by side.
    """
    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    d = _read(path)

    name = _need(d, "name", path)
    target = os.path.abspath(target or os.path.join(folder, _need(d, "target", path)))

    plat = _need(d, "platform", path)
    base = _need(plat, "base", "platform")
    if base not in PLATFORMS:
        raise AdapterError("platform.base: unknown '%s' (have: %s)" % (base, ", ".join(PLATFORMS)))
    extra = plat.get("extra")

    fl = _need(d, "flash", path)
    chip = CHIPS[base]
    flash = FlashGeometry(base=_need(fl, "base", "flash"), size=_need(fl, "size", "flash"),
                          page=fl.get("page"), write_unit=fl.get("write_unit", chip["write_unit"]),
                          controller=chip["controller"], model=chip["model"], ob_base=chip["ob_base"],
                          wrp_unit=chip["wrp_unit"], endurance=chip["endurance"])
    timing = fl.get("timing", "typical")
    if timing not in TIMINGS:
        raise AdapterError("flash.timing: unknown '%s' (have: %s)" % (timing, ", ".join(TIMINGS)))
    flash.timing = TIMINGS[timing]
    if (flash.page is None) == ("sectors" not in fl):
        raise AdapterError("flash: give exactly one of page (one erase size everywhere) "
                           "or sectors (a list of sizes)")
    if flash.page is not None:
        if flash.page <= 0 or flash.size % flash.page:
            raise AdapterError("flash.size must be a whole number of pages")
    else:
        sizes = fl["sectors"]
        if not isinstance(sizes, list) or not sizes or any(not isinstance(n, int) or n <= 0 for n in sizes):
            raise AdapterError("flash.sectors must be a list of sector sizes")
        if sum(sizes) != flash.size:
            raise AdapterError("flash.sectors add up to 0x%X, but flash.size is 0x%X"
                               % (sum(sizes), flash.size))
        flash.sectors = [(sum(sizes[:i]), n) for i, n in enumerate(sizes)]
    if chip["model"] in ("stm32f1_flash.py", "nrf52_flash.py") and flash.page is None:
        raise AdapterError("flash: an %s erases by page, not by sector" % base)
    if chip["model"] == "stm32f4_flash.py" and flash.sectors is None:
        raise AdapterError("flash: an %s erases by sector; list them in flash.sectors" % base)
    worn = fl.get("worn")
    if worn:
        where = "flash.worn"
        start, size = _need(worn, "from", where), _need(worn, "size", where)
        if not (flash.base <= start and start + size <= flash.base + flash.size and size > 0):
            raise AdapterError("flash.worn: inside the flash, with a size above 0")
        flash.worn = (start, start + size)
    flash.option_bytes = chip["option_bytes"](flash, fl.get("write_protected") or [],
                                              bool(fl.get("read_protected", False)),
                                              bool(fl.get("hardware_watchdog", False)))

    ext = d.get("external_flash")
    if ext:
        where = "external_flash"
        flash.ext_bus = str(_need(ext, "bus", where))
        flash.ext_cs = str(_need(ext, "cs", where)).upper()
        flash.ext_size = _need(ext, "size", where)
        flash.ext_base = ext.get("address", 0xA0000000)
        flash.ext_endurance = int(ext.get("endurance", 100000))
        # the status registers as the device ships: block protection set at the factory
        status = ext.get("status", 0)
        if not isinstance(status, int) or not 0 <= status <= 0xFFFF:
            raise AdapterError("external_flash.status: status register 1, or both as 0xSSRR "
                               "(register 2 in the high byte)")
        flash.ext_status = status
        pin = flash.ext_cs
        if not (len(pin) >= 3 and pin[0] == "P" and "A" <= pin[1] <= "K" and pin[2:].isdigit()
                and int(pin[2:]) < 16):
            raise AdapterError("external_flash.cs: '%s' is not a pin name like PA4" % pin)
        if not isinstance(flash.ext_size, int) or flash.ext_size <= 0 or flash.ext_size % 0x1000 \
                or flash.ext_size > 0x1000000:
            raise AdapterError("external_flash.size: a multiple of 4 KB, up to 16 MB (three address bytes)")
        if flash.ext_base < flash.base + flash.size and flash.ext_base + flash.ext_size > flash.base:
            raise AdapterError("external_flash.address: it overlaps the internal flash")

    # RAM size is not optional: an emulator with more RAM than the chip hides
    # real faults (a stack access past the end of RAM just works)
    ram = _need(d, "ram", path)
    ram_size = _need(ram, "size", "ram")
    if ram_size <= 0:
        raise AdapterError("ram.size must be positive")

    firmware = []
    for i, fw in enumerate(_need(d, "firmware", path)):
        file = _need(fw, "file", "firmware[%d]" % i)
        addr = fw.get("addr")
        if not file.lower().endswith(".elf") and addr is None:
            raise AdapterError("firmware[%d]: a raw binary needs 'addr'" % i)
        firmware.append((os.path.normpath(os.path.join(target, file)), addr))

    cpu = d.get("cpu", {})
    drv = _need(d, "driver", path)
    oracle = _parse_oracle(d, target)
    scenario = d.get("scenario") or {}
    cuts = [cut for i, c in enumerate(scenario.get("cuts") or []) for cut in _parse_cuts(i, c)]
    if bool(drv.get("file")) == bool(drv.get("builtin")):
        raise AdapterError("driver: give exactly one of file or builtin")

    return Adapter(
        path=path, name=name, folder=folder, target=target,
        platform=base, platform_extra=os.path.join(folder, extra) if extra else None,
        flash=flash, ram_base=ram.get("base", 0x20000000), ram_size=ram_size, firmware=firmware,
        uart=d.get("uart", "usart2"),
        vector_table=cpu.get("vector_table", flash.base),
        mips=cpu.get("mips", chip.get("mips", 72)),
        reset_cmds=_parse_pins(d) + list(d.get("reset", [])),
        hse=int((d.get("clock") or {}).get("hse", 8000000)),
        boot_settle=float(d.get("boot_settle", 1.5)),
        cut_limit=float(scenario.get("cut_limit", 30.0)),
        update_time=float(scenario.get("update_time", scenario.get("cut_limit", 30.0))),
        check_states=bool(scenario.get("check_states", True)),
        oracle=oracle,
        content_faults=_parse_content(scenario, target, oracle),
        link_cuts=_parse_link(scenario),
        bit_errors=_parse_bit_errors(scenario, oracle),
        plan=_parse_plan(scenario),
        torn=_parse_torn(scenario),
        torn_seed=int(scenario.get("torn_seed", 0)),
        depth=_parse_depth(scenario),
        driver_file=os.path.join(folder, drv["file"]) if drv.get("file") else None,
        driver_builtin=drv.get("builtin"),
        driver_options=drv.get("options", {}) or {},
        cuts=cuts,
    )
