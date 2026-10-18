"""The oracle: did the device recover? Judged from outside the firmware.

A driver's own check asks the firmware about itself (a UART banner, a version reply).
That is circular: the code under test vouches for the code under test. The oracle
uses nothing the firmware says. It looks at two facts:

  what is installed   the bytes in flash are exactly one of the approved images
  what is running     the core is executing inside that image, in normal thread
                      code, not parked in a fault handler

It shares no code with any target. An adapter lists the approved images and which of
them a scenario accepts after a cut (only the new one, or old and new). Images can also
sit side by side at different addresses, a bootloader and the program it starts: then
the core must be running inside one of those that are installed.
"""
from dataclasses import dataclass

FAULTS = {2: "NMI", 3: "HardFault", 4: "MemManage", 5: "BusFault", 6: "UsageFault"}


@dataclass
class Image:
    name: str
    data: bytes
    addr: int

    @property
    def end(self):
        return self.addr + len(self.data)


@dataclass
class Verdict:
    ok: bool
    image: str = None       # name of the approved image found installed, if any
    message: str = ""


class Oracle:
    """images     every image that is allowed to exist on the device
    accept     names of the ones this scenario may end up with after a cut
    run_in     (start, end) the PC must stay within; default: the installed image itself
    stable_for virtual seconds the device must then keep running without a reset. A few
               samples a few ms apart see an image that boots and is reset by its watchdog
               half a second later as running; this sees the loop. 0 = do not wait
    """

    def __init__(self, images, accept, run_in=None, samples=4, interval=0.02, stable_for=0.0):
        if not images:
            raise ValueError("oracle: no images")
        names = [i.name for i in images]
        unknown = [a for a in accept if a not in names]
        if unknown or not accept:
            raise ValueError("oracle: accept must name images (have %s, got %s)" % (names, accept))
        self.images = list(images)
        self.accept = list(accept)
        self.run_in = run_in
        self.samples = samples
        self.interval = interval
        self.stable_for = stable_for

    def _find(self, session):
        """(approved images that are in flash, one per address; the closest miss)."""
        nearest, here = None, {}
        for img in self.images:
            diff = session.image_mismatch(img.data, img.addr)
            if diff is None:
                # One image can be the start of another (an update that only appends),
                # and then both match. The longest is the one that is really there.
                if img.addr not in here or len(img.data) > len(here[img.addr].data):
                    here[img.addr] = img
            elif nearest is None or diff > nearest[1]:
                nearest = (img, diff)
        return list(here.values()), nearest

    def installed(self, session):
        """(the approved image that is in flash, None) or (None, why not). With images
        at several addresses, the longest of those found."""
        found, nearest = self._find(session)
        if found:
            return max(found, key=lambda i: len(i.data)), None
        img, diff = nearest
        return None, ("no approved image is installed at 0x%08X: the closest is %s, and flash "
                      "differs from it at 0x%08X" % (img.addr, img.name, diff))

    def judge(self, session, stable=True):
        """The verdict. With stable (and stable_for set), an image seen running must go
        on running, with no reset, for stable_for seconds more."""
        v = self._look(session)
        if not (v.ok and stable and self.stable_for > 0):
            return v
        count = getattr(session, "resets", None)
        before = count() if count else None     # None: the emulator cannot count resets
        session.run_for(self.stable_for)
        if before is not None:
            n = count() - before
            if n:
                return Verdict(False, v.image, "%s was running, then the device reset %d time(s) "
                               "in the next %.1f s: it keeps rebooting" % (v.image, n, self.stable_for))
        again = self._look(session)
        if not again.ok:
            return Verdict(False, again.image, "%s was running, but %.1f s later: %s"
                           % (v.image, self.stable_for, again.message))
        return again

    def _look(self, session):
        found, _ = self._find(session)
        if not found:
            return Verdict(False, None, self.installed(session)[1])
        samples = session.sample_cpu(self.samples, self.interval)
        if len(found) > 1:
            return self._judge_side_by_side(found, samples)
        img = found[0]
        if img.name not in self.accept:
            return Verdict(False, img.name, "the installed image is %s; this scenario accepts only %s"
                           % (img.name, " or ".join(self.accept)))
        lo, hi = self.run_in or (img.addr, img.end)
        for pc, exc in samples:
            if exc in FAULTS:
                return Verdict(False, img.name, "%s is installed but the core is in the %s "
                               "handler (PC 0x%08X)" % (img.name, FAULTS[exc], pc))
            if not lo <= pc < hi:
                return Verdict(False, img.name, "%s is installed but not running: PC 0x%08X is "
                               "outside 0x%08X..0x%08X" % (img.name, pc, lo, hi))
        return Verdict(True, img.name)

    def _judge_side_by_side(self, found, samples):
        """Several approved images are installed at different addresses, a bootloader and
        the program it starts for example. The core must be in one this scenario accepts.
        It may go from one to the other between two looks: a bootloader hands over."""
        names = " and ".join(i.name for i in found)
        running = None
        for pc, exc in samples:
            if exc in FAULTS:
                return Verdict(False, None, "%s are installed but the core is in the %s handler "
                               "(PC 0x%08X)" % (names, FAULTS[exc], pc))
            inside = [i for i in found if i.addr <= pc < i.end]
            if not inside:
                return Verdict(False, None, "%s are installed but neither is running: PC 0x%08X"
                               % (names, pc))
            if self.run_in and not self.run_in[0] <= pc < self.run_in[1]:
                return Verdict(False, inside[0].name, "%s are installed but PC 0x%08X is outside "
                               "0x%08X..0x%08X" % (names, pc, self.run_in[0], self.run_in[1]))
            running = inside[0]
            if running.name not in self.accept:
                return Verdict(False, running.name, "the core is running %s; this scenario accepts "
                               "only %s" % (running.name, " or ".join(self.accept)))
        return Verdict(True, running.name)


def build(adapter, driver):
    """The oracle an adapter asks for, or None. A driver can add images it makes at
    run time (a freshly signed update, for example) with oracle_images()."""
    cfg = adapter.oracle
    if not cfg:
        return None
    images = []
    for name, (path, addr) in cfg["images"].items():
        with open(path, "rb") as f:
            images.append(Image(name, f.read(), addr))
    extra = getattr(driver, "oracle_images", None)
    for name, (data, addr) in (extra() if extra else {}).items():
        images.append(Image(name, bytes(data), addr))
    return Oracle(images, cfg["accept"], cfg.get("run_in"), cfg.get("samples", 4),
                  cfg.get("interval", 0.02), cfg.get("stable_for", 0.0))
