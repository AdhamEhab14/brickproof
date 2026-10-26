"""Not a power cut: damaged update images, bits flipped at rest, and a UART link that
breaks part-way through the host's session."""
import time

from brickproof import bit_errors as bit_errs
from brickproof import content as contents
from brickproof import oracle as oracles
from brickproof import trace as traces
from brickproof.engine.session import MachineHung
from brickproof.campaign.judge import _failed, _fault_message, _hang_confirmed, _verdict
from brickproof.campaign.results import CutResult


@_hang_confirmed
def run_content(session, driver, adapter, name, image, judge):
    """One damaged image, staged in place of the update, and the update left to run. Not a
    power cut: the device must refuse the image and keep the one `judge` accepts, which the
    oracle checks from outside. The driver's own recovery check is not used: it expects the
    update to have happened."""
    res = CutResult(cut="content " + name, fired=True, kind="content", content=name)
    t0 = time.time()
    try:
        session.restore_flash(image)
        on_boot = getattr(driver, "update_on_boot", False)
        session.power_cycle(settle=0 if on_boot else adapter.boot_settle)
        driver.start_update()
        session.run_for(adapter.update_time)
        res.message = _fault_message(session) or ""
        if res.message:
            return res
        session.power_cycle(settle=adapter.boot_settle)
        res.alive = bool(driver.alive())
        res.message = _fault_message(session) or ("" if res.alive else "the device did not come back")
        if res.message:
            return res
        v = judge.judge(session)
        res.image = v.image
        res.message = "" if v.ok else "the bootloader did not refuse it: " + v.message
        res.recovered = res.passed = v.ok
        return res
    except MachineHung:
        res.hung = True
        res.message = "the device locked up (emulated CPU stopped making progress)"
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


@_hang_confirmed
def run_bit_error(session, driver, adapter, name, image, region, judge):
    """Boot from flash with bits flipped inside `region`. The device must not execute
    there, nor sit in a fault handler: refusing the damaged image is the right answer."""
    res = CutResult(cut="bits " + name, fired=True, kind="bit error", bit_error=name)
    t0 = time.time()
    try:
        session.restore_flash(image)
        session.power_cycle(settle=adapter.boot_settle)
        session.run_for(adapter.update_time)
        res.alive = True
        res.message = _fault_message(session) or ""
        if res.message:
            return res
        lo, hi = region
        for pc, exc in session.sample_cpu(judge.samples, judge.interval):
            if exc in oracles.FAULTS:
                res.message = "the device is in the %s handler (PC 0x%08X)" % (oracles.FAULTS[exc], pc)
                return res
            if lo <= pc < hi:
                res.message = "the damaged image is running (PC 0x%08X): nothing checked it" % pc
                return res
        res.recovered = res.passed = True
        return res
    except MachineHung:
        res.hung = True
        res.message = "the device locked up (emulated CPU stopped making progress)"
        session.restart()
        return res
    finally:
        res.seconds = round(time.time() - t0, 1)


def bit_errors(pool, adapter, golden, out, on_result=None, fail_fast=False):
    """Bits flipped in the flash the update left behind, one test each."""
    cfg = adapter.bit_errors
    o = golden.oracle
    flash = adapter.flash
    regions = cfg["regions"]
    if regions is None:
        regions = {i.name: (i.addr, i.end) for i in o.images if i.name in o.accept}
    regions = {n: r for n, r in regions.items()
               if flash.base <= r[0] and r[1] <= flash.base + flash.size}
    end = bytes(golden.replay.at(len(golden.ops)))
    tasks = bit_errs.cases(end, flash.base, regions, cfg["flips"], cfg["runs"], cfg["seed"])
    results = pool.run(lambda s, d, t: run_bit_error(s, d, adapter, t[0], t[1], t[2], o), tasks,
                       on_result, _failed if fail_fast else None)
    out.results += results


def link_points(total, n):
    """n byte counts spread over a session of `total` bytes, the first and last byte
    included: where to break the link."""
    if total <= 1:
        return []
    picks = {1, total - 1} | {round(total * k / (n + 1)) for k in range(1, n + 1)}
    return sorted(p for p in picks if 0 < p < total)


@_hang_confirmed
def run_link(session, driver, adapter, n, golden):
    """The link breaks after the host has sent n bytes of the update; the device keeps its
    power. After `wait` seconds the cable is back, the host runs the whole update again,
    and the usual verdict follows: the device must be alive, the oracle content, and the
    driver's own check (for a protocol driver, one more full session) must pass."""
    res = CutResult(cut="link %d" % n, fired=True, kind="link", link=n)
    t0 = time.time()
    try:
        session.restore_flash(golden.pre)
        session.power_cycle(settle=adapter.boot_settle)
        session.link_budget = n
        try:
            driver.start_update()           # the host's session; it fails when the link goes
        except Exception:                   # noqa: BLE001 - a host tool giving up is expected here
            pass
        session.run_for(adapter.link_cuts["wait"])
        session.link_budget = None          # the cable is back
        res.message = _fault_message(session) or ""
        if res.message:
            return res
        driver.start_update()               # the host tries again from the start
        session.run_for(adapter.update_time)
        _verdict(session, driver, adapter, res, golden.oracle, None)
        return res
    except MachineHung:
        res.hung = True
        res.message = "the device locked up (emulated CPU stopped making progress)"
        session.restart()
        return res
    finally:
        session.link_budget = None
        res.seconds = round(time.time() - t0, 1)


def link_cuts(pool, adapter, golden, out, on_result=None, fail_fast=False):
    """Break the host's link at points spread over the bytes it sends."""
    points = link_points(golden.link_bytes, adapter.link_cuts["points"])
    results = pool.run(lambda s, d, n: run_link(s, d, adapter, n, golden), points,
                       on_result, _failed if fail_fast else None)
    out.results += results


def content_faults(pool, adapter, driver, golden, out, on_result=None, fail_fast=False):
    """Every damaged image the adapter asks for, each run as its own test."""
    cfg = adapter.content_faults
    if not hasattr(driver, "staged"):
        raise ValueError("scenario.content_faults: the driver does not say what it stages "
                         "(it needs a staged() method, as staged_slot has)")
    addr, staged = driver.staged()
    files = {}
    for name, path in cfg["images"].items():
        with open(path, "rb") as f:
            files[name] = f.read()
    off, _ = traces.locate(addr, adapter.flash)
    tasks = []
    for name, data in contents.mutations(staged, cfg, files):
        image = bytearray(golden.pre)
        # an oversized image stops at the end of the flash it was staged in
        unit_end = adapter.flash.size if off < adapter.flash.size else len(image)
        data = data[:max(0, unit_end - off)]
        image[off:off + len(data)] = data
        tasks.append((name, bytes(image)))
    o = golden.oracle
    judge = oracles.Oracle(o.images, [cfg["keep"]], o.run_in, o.samples, o.interval, o.stable_for)
    results = pool.run(lambda s, d, t: run_content(s, d, adapter, t[0], t[1], judge), tasks,
                       on_result, _failed if fail_fast else None)
    out.results += results
