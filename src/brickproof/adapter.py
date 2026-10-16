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
    platform_extra: str           # Renode only: more platform lines
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
    wake_after: float = 0.5       # seconds a wake source takes to end Standby / System OFF
    driver_file: str = None       # a driver.py next to the adapter, or
    driver_builtin: str = None    # one that ships with BrickProof
    driver_options: dict = field(default_factory=dict)
    cuts: list = field(default_factory=list)
    emulator: str = "renode"      # renode, or m33mu (see CHIPS)
    optbytes: dict = field(default_factory=dict)   # m33mu: option bytes as shipped, by name

    def load_driver(self, session):
        """Import the driver module and return its driver object for this session."""
        if self.driver_builtin:
            mod = importlib.import_module("brickproof.drivers." + self.driver_builtin)
        else:
            spec = importlib.util.spec_from_file_location("brickproof_driver_" + self.name, self.driver_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        return mod.make_driver(session, self)


def _protected_ranges(flash, protected, key="write_protected"):
    """The write_protected (or pcrop) entries as checked (where, start, size) tuples."""
    out = []
    for i, r in enumerate(protected):
        where = "flash.%s[%d]" % (key, i)
        start, size = _need(r, "from", where), _need(r, "size", where)
        if start < flash.base or start + size > flash.base + flash.size or size <= 0:
            raise AdapterError("%s: outside the flash" % where)
        out.append((where, start, size))
    return out


def stm32f1_option_bytes(flash, protected, read_protected, hardware_watchdog=False, pcrop=()):
    """The 16 option bytes of an STM32F1 as the chip holds them: RDP, USER, Data0,
    Data1, WRP0..WRP3, each followed by its complement. `protected` is a list of
    {from, size} ranges to write-protect; a cleared WRP bit protects its unit."""
    if pcrop:
        raise AdapterError("flash.pcrop: an STM32F1 has no proprietary-code protection")
    if read_protected == 2:
        raise AdapterError("flash.read_protected: an STM32F1 has one level of read protection")
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


def _sectors_of(flash, ranges, key):
    """The sector numbers whole {from, size} ranges cover."""
    units = flash.units()
    starts = [u for u, _ in units]
    ends = [u + n for u, n in units]
    out = []
    for where, start, size in _protected_ranges(flash, ranges, key):
        if start not in starts or start + size not in ends:
            raise AdapterError("%s: goes by whole sectors on this chip" % where)
        out += range(starts.index(start), ends.index(start + size) + 1)
    return out


def stm32f4_option_bytes(flash, protected, read_protected, hardware_watchdog=False, pcrop=()):
    """The option bytes of an STM32F4 as the chip shows them: USER and RDP in one
    halfword, the nWRP bits in another, each followed by its complement. Write
    protection is one bit per sector, and a cleared bit protects its sector. With
    `pcrop` the sectors it names are proprietary code instead: SPRMOD set (stored
    inverted, bit 15) and their nWRP bits set, the rest cleared. read_protected 2 is
    level 2 (0xCC)."""
    if pcrop and protected:
        raise AdapterError("flash: write_protected and pcrop share the nWRP bits on this chip; "
                           "with pcrop, the proprietary-code sectors are the protected ones")
    if pcrop:
        nwrp = 0
        for s in _sectors_of(flash, pcrop, "pcrop"):
            nwrp |= 1 << s
        sprmod = 0x0000                 # SPRMOD = 1, stored inverted
    else:
        nwrp = 0xFFF
        for s in _sectors_of(flash, protected, "write_protected"):
            nwrp &= ~(1 << s)
        sprmod = 0x8000
    rdp = {0: 0xAA, 1: 0x55, 2: 0xCC}[int(read_protected)]
    out = bytearray()
    user = 0xCF if hardware_watchdog else 0xEF      # WDG_SW is bit 5, cleared = hardware
    for half in ((rdp << 8) | user, 0x7000 | sprmod | nwrp):
        out += bytes([half & 0xFF, half >> 8, ~half & 0xFF, (~half >> 8) & 0xFF]) + bytes([0xFF]) * 4
    return bytes(out)


def stm32l4_option_bytes(flash, protected, read_protected, hardware_watchdog=False, pcrop=()):
    """The STM32L4's option bytes at 0x1FFF7800: OPTR, PCROP1SR, PCROP1ER, WRP1AR and WRP1BR,
    each a word and its complement. Up to two write-protected areas, in bank 1."""
    if pcrop:
        raise AdapterError("flash.pcrop: not modelled on the STM32L4")
    rdp = {0: 0xAA, 1: 0xBB, 2: 0xCC}[int(read_protected)]
    optr = (0xFFEFF800 | rdp) & ~((1 << 16) if hardware_watchdog else 0)
    areas = []
    for _, start, size in _protected_ranges(flash, protected):
        first, last = (start - flash.base) // flash.page, (start - flash.base + size - 1) // flash.page
        if last >= flash.size // 2 // flash.page:
            raise AdapterError("flash.write_protected: bank 2 is not modelled on the STM32L4")
        areas.append(first | (last << 16) | 0xFF00FF00)
    if len(areas) > 2:
        raise AdapterError("flash.write_protected: an STM32L4 has two areas in bank 1")
    areas += [0xFF00FFFF] * (2 - len(areas))
    out = b""
    for w in (optr, 0xFFFFFFFF, 0x00000000, *areas):
        out += (w & 0xFFFFFFFF).to_bytes(4, "little") + (~w & 0xFFFFFFFF).to_bytes(4, "little")
    return out


UICR_SIZE = 0x400                 # the nRF52840's UICR registers end at REGOUT0, 0x304
UICR_APPROTECT = 0x208


def nrf52_uicr(flash, protected, read_protected, hardware_watchdog=False, pcrop=()):
    """The nRF52's UICR as shipped: erased, but for APPROTECT when read_protected is set.
    It has no write protection of its own (the ACL is set by firmware at run time)."""
    if protected or hardware_watchdog or pcrop or int(read_protected) > 1:
        raise AdapterError("flash: write_protected, hardware_watchdog, pcrop and read protection "
                           "level 2 are STM32 option bytes; on an nRF52 only read_protected "
                           "(APPROTECT) applies, and write protection is the ACL, set at run time")
    uicr = bytearray([0xFF]) * UICR_SIZE
    if read_protected:
        uicr[UICR_APPROTECT:UICR_APPROTECT + 4] = (0xFFFFFF00).to_bytes(4, "little")
    return bytes(uicr)


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
    # 2 KB pages, double-word programs with ECC (the flash of the L4, G0, G4, WB and WL)
    "stm32l476": dict(model="stm32l4_flash.py", controller=0x40022000, ob_base=0x1FFF7800,
                      option_bytes=stm32l4_option_bytes, wrp_unit=None, write_unit=8,
                      endurance=10000, mips=80, ecc=True),
    # the nRF52's option bytes are its UICR, and its ERASEALL erases them too
    "nrf52840": dict(model="nrf52_flash.py", controller=0x4001E000, ob_base=0x10001000,
                     option_bytes=nrf52_uicr, wrp_unit=None, write_unit=4,
                     endurance=10000, mips=64, mass_erase_ob=True),
}

# Chips emulated by m33mu instead of Renode. m33mu models the whole chip, so its
# memory sizes are fixed and the adapter must name them as they are; the flash
# controller, its rules and its timing are m33mu's.
#   cpu          m33mu's name for it (--cpu)
#   flash        (size, erase unit, the aliases flash is seen at)
#   ram          (size, the aliases RAM is seen at)
#   uarts        UART names an adapter can give, and their base addresses
#   wrpsg        how write protection is set: option byte per bank, flash per bit
M33MU_CHIPS = {
    # RM0481 / DS14258: 2 MB in two banks of 128 sectors of 8 KB, 640 KB of SRAM.
    # A program writes 128 bits; 10 kcycles endurance.
    "stm32h563": dict(cpu="stm32h563", flash=(0x200000, 0x2000, (0x08000000, 0x0C000000)),
                      ram=(0xA0000, (0x20000000, 0x30000000)), write_unit=16, endurance=10000,
                      uarts={"usart1": 0x40013800, "usart2": 0x40004400, "usart3": 0x40004800,
                             "uart4": 0x40004C00, "uart5": 0x40005000, "usart6": 0x40006400,
                             "uart7": 0x40007800, "uart8": 0x40007C00, "uart9": 0x40008000,
                             "usart10": 0x40006800, "usart11": 0x40006C00, "uart12": 0x40008400,
                             "lpuart1": 0x44002400},
                      wrpsg=(("WRPSG1", "WRPSG2"), 0x8000)),
}
PLATFORMS = tuple(CHIPS) + tuple(M33MU_CHIPS)

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


def _wake_after(d):
    """low_power.wake_after: how long after the chip goes into Standby (or an nRF52 into System
    OFF) its wake source brings it back, in seconds: the RTC alarm or button the board uses."""
    v = (d.get("low_power") or {}).get("wake_after", 0.5)
    if not isinstance(v, (int, float)) or not 0 < v <= 3600:
        raise AdapterError("low_power.wake_after: seconds, above 0")
    return float(v)


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
    if base in M33MU_CHIPS:
        return _load_m33mu(d, path, folder, name, target, base)

    if "option_bytes" in d:
        raise AdapterError("option_bytes: only for chips m33mu emulates; on %s use "
                           "flash.write_protected, read_protected and hardware_watchdog" % base)
    fl = _need(d, "flash", path)
    chip = CHIPS[base]
    flash = FlashGeometry(base=_need(fl, "base", "flash"), size=_need(fl, "size", "flash"),
                          page=fl.get("page"), write_unit=fl.get("write_unit", chip["write_unit"]),
                          controller=chip["controller"], model=chip["model"], ob_base=chip["ob_base"],
                          wrp_unit=chip["wrp_unit"], endurance=chip["endurance"],
                          mass_erase_ob=chip.get("mass_erase_ob", False), ecc=chip.get("ecc", False))
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
    if chip["model"] in ("stm32f1_flash.py", "nrf52_flash.py", "stm32l4_flash.py") and flash.page is None:
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
    read_protected = fl.get("read_protected", False)
    if read_protected not in (False, True, 0, 1, 2):
        raise AdapterError("flash.read_protected: false, true (level 1) or 2")
    flash.option_bytes = chip["option_bytes"](flash, fl.get("write_protected") or [],
                                              int(read_protected),
                                              bool(fl.get("hardware_watchdog", False)),
                                              pcrop=fl.get("pcrop") or [])
    reset_on = fl.get("reset_on") or []
    if reset_on:
        # nRST_STOP / nRST_STDBY cleared: entering that low-power mode resets the chip instead
        if not isinstance(reset_on, list) or not set(reset_on) <= {"stop", "standby"}:
            raise AdapterError("flash.reset_on: a list of stop and standby")
        # where USER is in the option bytes, and its two bits, on the chips that have them
        where = {"stm32f1_flash.py": (2, {"stop": 1, "standby": 2}),
                 "stm32f4_flash.py": (0, {"stop": 6, "standby": 7})}.get(chip["model"])
        if where is None:
            raise AdapterError("flash.reset_on: nRST_STOP and nRST_STDBY are STM32F1 and F4 option bits")
        ob = bytearray(flash.option_bytes)
        at, bits = where
        for mode in reset_on:
            ob[at] &= ~(1 << bits[mode]) & 0xFF
        ob[at + (1 if at == 2 else 2)] = ~ob[at] & 0xFF      # and its complement
        flash.option_bytes = bytes(ob)
    uicr = fl.get("uicr")
    if uicr:
        # UICR words as the device ships (nRF52 only): {offset: value}, for example REGOUT0
        if chip["option_bytes"] is not nrf52_uicr or not isinstance(uicr, dict):
            raise AdapterError("flash.uicr: {offset: value} words of an nRF52's UICR")
        ob = bytearray(flash.option_bytes)
        for off, value in uicr.items():
            if not (isinstance(off, int) and isinstance(value, int) and off % 4 == 0
                    and 0 <= off < UICR_SIZE and 0 <= value <= 0xFFFFFFFF):
                raise AdapterError("flash.uicr: offset 0x%X: a word offset below 0x%X, a 32-bit value"
                                   % (off if isinstance(off, int) else 0, UICR_SIZE))
            ob[off:off + 4] = value.to_bytes(4, "little")
        flash.option_bytes = bytes(ob)

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
        if not isinstance(status, int) or not 0 <= status <= 0xFFFFFF:
            raise AdapterError("external_flash.status: status register 1, or 0xTTSSRR with "
                               "register 2 (SS) and register 3 (TT) above it")
        flash.ext_status = status
        flash.ext_wp = str(ext.get("wp", "")).upper()
        for key, pin in (("cs", flash.ext_cs), ("wp", flash.ext_wp)):
            if key == "wp" and not pin:
                continue
            if not (len(pin) >= 3 and pin[0] == "P" and "A" <= pin[1] <= "K" and pin[2:].isdigit()
                    and int(pin[2:]) < 16):
                raise AdapterError("external_flash.%s: '%s' is not a pin name like PA4" % (key, pin))
        if flash.ext_wp and flash.ext_wp == flash.ext_cs:
            raise AdapterError("external_flash.wp: the same pin as cs")
        if not isinstance(flash.ext_size, int) or flash.ext_size <= 0 or flash.ext_size % 0x1000 \
                or flash.ext_size > 0x4000000:
            raise AdapterError("external_flash.size: a multiple of 4 KB, up to 64 MB (over 16 MB the "
                               "chip has 4-byte addresses)")
        if flash.ext_base < flash.base + flash.size and flash.ext_base + flash.ext_size > flash.base:
            raise AdapterError("external_flash.address: it overlaps the internal flash")

    ee = d.get("external_eeprom")
    if ee:
        where = "external_eeprom"
        flash.eeprom_bus = str(_need(ee, "bus", where))
        flash.eeprom_size = _need(ee, "size", where)
        flash.eeprom_base = ee.get("address", 0xB0000000)
        flash.eeprom_i2c = ee.get("i2c_address", 0x50)
        flash.eeprom_page = ee.get("page", 32)
        flash.eeprom_address_bytes = ee.get("address_bytes", 2 if flash.eeprom_size > 256 else 1)
        flash.eeprom_endurance = int(ee.get("endurance", 1000000))

        def power_of_two(n):
            return isinstance(n, int) and n > 0 and n & (n - 1) == 0

        if not power_of_two(flash.eeprom_size) or flash.eeprom_size > 0x10000:
            raise AdapterError("external_eeprom.size: a power of two, up to 64 KB (a 24C512)")
        if not power_of_two(flash.eeprom_page) or flash.eeprom_page > flash.eeprom_size:
            raise AdapterError("external_eeprom.page: a power of two, no bigger than the EEPROM")
        if flash.eeprom_address_bytes not in (1, 2) \
                or flash.eeprom_size > 1 << (8 * flash.eeprom_address_bytes):
            raise AdapterError("external_eeprom.address_bytes: 1 (up to 256 bytes) or 2")
        if not isinstance(flash.eeprom_i2c, int) or not 0x08 <= flash.eeprom_i2c <= 0x77:
            raise AdapterError("external_eeprom.i2c_address: a 7-bit address, 0x08 to 0x77")
        spans = [(flash.base, flash.size, "the internal flash")]
        if flash.ext_size:
            spans.append((flash.ext_base, flash.ext_size, "the external flash"))
        for start, size, name in spans:
            if flash.eeprom_base < start + size and flash.eeprom_base + flash.eeprom_size > start:
                raise AdapterError("external_eeprom.address: it overlaps %s" % name)

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
        wake_after=_wake_after(d),
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


# Keys that only mean something to Renode. An m33mu adapter that gives one would be
# describing a device it does not get, so it is refused rather than ignored.
RENODE_ONLY = {
    ("platform", "extra"): "more Renode platform lines",
    ("reset",): "Renode monitor commands",
    ("pins",): "pin levels set through Renode",
    ("external_flash",): "the Renode SPI NOR model",
    ("external_eeprom",): "the Renode I2C EEPROM model",
    ("flash", "worn"): "worn pages in the Renode flash models",
    ("flash", "uicr"): "the nRF52's UICR",
    ("clock",): "the board clock fed to Renode's clock model",
    ("cpu", "mips"): "Renode's emulated CPU speed",
}


def _firmware(d, path, target):
    firmware = []
    for i, fw in enumerate(_need(d, "firmware", path)):
        file = _need(fw, "file", "firmware[%d]" % i)
        addr = fw.get("addr")
        if not file.lower().endswith(".elf") and addr is None:
            raise AdapterError("firmware[%d]: a raw binary needs 'addr'" % i)
        firmware.append((os.path.normpath(os.path.join(target, file)), addr))
    return firmware


def _wrpsg(flash, protected, names, group):
    """flash.write_protected as the WRPSG option bytes: one per bank, a cleared bit
    protecting one group of sectors (RM0481 7.11.35)."""
    bank = flash.size // len(names)
    values = [0xFFFFFFFF] * len(names)
    for where, start, size in _protected_ranges(flash, protected):
        off = start - flash.base
        if off % group or size % group:
            raise AdapterError("%s: the chip protects whole groups of 0x%X bytes; start and "
                               "size must be multiples of that" % (where, group))
        for g in range(off // group, (off + size) // group):
            b, bit = divmod(g * group, bank)
            values[b] &= ~(1 << (bit // group))
    return {n: v for n, v in zip(names, values, strict=True) if v != 0xFFFFFFFF}


def _load_m33mu(d, path, folder, name, target, base):
    chip = M33MU_CHIPS[base]
    for keys, what in RENODE_ONLY.items():
        node = d
        for k in keys:
            node = node.get(k) if isinstance(node, dict) else None
        if node is not None:
            raise AdapterError("%s: %s, which %s does not use (m33mu emulates this chip)"
                               % (".".join(keys), what, base))

    fl = _need(d, "flash", path)
    size, unit, aliases = chip["flash"]
    fbase = _need(fl, "base", "flash")
    if fbase not in aliases:
        raise AdapterError("flash.base: %s flash is at %s"
                           % (base, " or ".join("0x%08X" % a for a in aliases)))
    if _need(fl, "size", "flash") != size:
        raise AdapterError("flash.size: %s has 0x%X bytes of flash" % (base, size))
    if fl.get("page", unit) != unit or "sectors" in fl:
        raise AdapterError("flash: %s erases sectors of 0x%X bytes; give page: 0x%X or leave it out"
                           % (base, unit, unit))
    flash = FlashGeometry(base=fbase, size=size, page=unit,
                          write_unit=fl.get("write_unit", chip["write_unit"]),
                          controller=0, model="", endurance=chip["endurance"])
    timing = fl.get("timing", "typical")
    if timing not in TIMINGS:
        raise AdapterError("flash.timing: unknown '%s' (have: %s)" % (timing, ", ".join(TIMINGS)))
    flash.timing = TIMINGS[timing]
    if fl.get("read_protected") or fl.get("hardware_watchdog"):
        raise AdapterError("flash: read_protected and hardware_watchdog are not modelled for %s" % base)

    optbytes = {}
    for opt, value in (d.get("option_bytes") or {}).items():
        if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
            raise AdapterError("option_bytes.%s: a 32-bit number" % opt)
        optbytes[str(opt)] = value
    names, group = chip["wrpsg"]
    for opt, value in _wrpsg(flash, fl.get("write_protected") or [], names, group).items():
        if opt in optbytes:
            raise AdapterError("option_bytes.%s and flash.write_protected both set it; use one" % opt)
        optbytes[opt] = value

    ram = _need(d, "ram", path)
    ram_size, ram_aliases = chip["ram"]
    if _need(ram, "size", "ram") != ram_size:
        raise AdapterError("ram.size: %s has 0x%X bytes of RAM" % (base, ram_size))
    ram_base = ram.get("base", ram_aliases[0])
    if ram_base not in ram_aliases:
        raise AdapterError("ram.base: %s RAM is at %s"
                           % (base, " or ".join("0x%08X" % a for a in ram_aliases)))

    uart = d.get("uart", "usart2")
    if isinstance(uart, str):
        if uart.lower() not in chip["uarts"]:
            raise AdapterError("uart: %s has %s, or give a base address"
                               % (base, ", ".join(sorted(chip["uarts"]))))
        uart = chip["uarts"][uart.lower()]

    cpu = d.get("cpu", {})
    oracle = _parse_oracle(d, target)
    drv = _need(d, "driver", path)
    scenario = d.get("scenario") or {}
    cuts = [cut for i, c in enumerate(scenario.get("cuts") or []) for cut in _parse_cuts(i, c)]
    if bool(drv.get("file")) == bool(drv.get("builtin")):
        raise AdapterError("driver: give exactly one of file or builtin")

    return Adapter(
        path=path, name=name, folder=folder, target=target,
        platform=base, platform_extra=None, emulator="m33mu", optbytes=optbytes,
        flash=flash, ram_base=ram_base, ram_size=ram_size, firmware=_firmware(d, path, target),
        uart=uart,
        vector_table=cpu.get("vector_table", flash.base),
        mips=0,
        reset_cmds=[],
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
