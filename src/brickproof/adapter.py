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
    """
    name: str
    on_erase: int = None
    at_op: int = None
    expect: tuple = None


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
    driver_file: str
    driver_options: dict = field(default_factory=dict)
    cuts: list = field(default_factory=list)

    def load_driver(self, session):
        """Import the driver module and return its driver object for this session."""
        spec = importlib.util.spec_from_file_location("brickproof_driver_" + self.name, self.driver_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.make_driver(session, self)


def _need(d, key, where):
    if key not in d:
        raise AdapterError("%s: missing '%s'" % (where, key))
    return d[key]


def _parse_cut(i, c):
    where = "cuts[%d]" % i
    if not isinstance(c, dict):
        raise AdapterError("%s: expected a mapping" % where)
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


def load(path, target=None):
    """Read an adapter YAML. `target` overrides the firmware project folder it names."""
    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    with open(path) as f:
        d = yaml.safe_load(f) or {}

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
    scenario = d.get("scenario", {})
    cuts = [_parse_cut(i, c) for i, c in enumerate(scenario.get("cuts", []))]

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
        driver_file=os.path.join(folder, _need(drv, "file", "driver")),
        driver_options=drv.get("options", {}) or {},
        cuts=cuts,
    )
