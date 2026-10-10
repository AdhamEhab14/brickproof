"""Target adapters: one YAML file describing the firmware, plus a Python driver.

The YAML says what to load, the flash geometry, how to reset, and where to cut.
The driver knows the target's update protocol (how to stage and start an update,
how to tell the device is alive). See adapters/three_tier_f103/ for an example.
"""
import importlib.util
import os
from dataclasses import dataclass, field

import yaml

from brickproof.engine.session import FlashGeometry

PLATFORMS = ("stm32f103",)


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
    name: str
    folder: str
    target: str
    platform: str
    platform_extra: str
    flash: FlashGeometry
    firmware: list
    uart: str
    vector_table: int
    mips: int
    reset_cmds: list
    boot_settle: float
    cut_limit: float
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
    flash = FlashGeometry(base=_need(fl, "base", "flash"), size=_need(fl, "size", "flash"),
                          page=_need(fl, "page", "flash"), write_unit=fl.get("write_unit", 2))
    if flash.size % flash.page:
        raise AdapterError("flash.size must be a whole number of pages")

    firmware = []
    for i, fw in enumerate(_need(d, "firmware", path)):
        file = _need(fw, "file", "firmware[%d]" % i)
        addr = fw.get("addr")
        if not file.lower().endswith(".elf") and addr is None:
            raise AdapterError("firmware[%d]: a raw binary needs 'addr'" % i)
        firmware.append((os.path.normpath(os.path.join(target, file)), addr))

    cpu = d.get("cpu", {})
    drv = _need(d, "driver", path)
    scenario = d.get("scenario") or {}
    cuts = [cut for i, c in enumerate(scenario.get("cuts") or []) for cut in _parse_cuts(i, c)]
    if bool(drv.get("file")) == bool(drv.get("builtin")):
        raise AdapterError("driver: give exactly one of file or builtin")

    return Adapter(
        name=name, folder=folder, target=target,
        platform=base, platform_extra=os.path.join(folder, extra) if extra else None,
        flash=flash, firmware=firmware,
        uart=d.get("uart", "usart2"),
        vector_table=cpu.get("vector_table", flash.base),
        mips=cpu.get("mips", 72),
        reset_cmds=list(d.get("reset", [])),
        boot_settle=float(d.get("boot_settle", 1.5)),
        cut_limit=float(scenario.get("cut_limit", 30.0)),
        driver_file=os.path.join(folder, drv["file"]) if drv.get("file") else None,
        driver_builtin=drv.get("builtin"),
        driver_options=drv.get("options", {}) or {},
        cuts=cuts,
    )
