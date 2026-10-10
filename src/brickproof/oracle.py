"""The oracle: did the device recover? Judged from outside the firmware.

A driver's own check asks the firmware about itself (a UART banner, a version reply).
That is circular: the code under test vouches for the code under test. The oracle
uses nothing the firmware says. It looks at two facts:

  what is installed   the bytes in flash are exactly one of the approved images
  what is running     the core is executing inside that image, in normal thread
                      code, not parked in a fault handler

It shares no code with any target. An adapter lists the approved images and which of
them a scenario accepts after a cut (only the new one, or old and new).
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
    """images   every image that is allowed to exist on the device
    accept   names of the ones this scenario may end up with after a cut
    run_in   (start, end) the PC must stay within; default: the installed image itself
    """

    def __init__(self, images, accept, run_in=None, samples=4, interval=0.02):
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

    def installed(self, session):
        """(the approved image that is in flash, None) or (None, why not)."""
        nearest, matches = None, []
        for img in self.images:
            diff = session.image_mismatch(img.data, img.addr)
            if diff is None:
                matches.append(img)
            elif nearest is None or diff > nearest[1]:
                nearest = (img, diff)
        if matches:
            # One image can be the start of another (an update that only appends), and
            # then both match. The longest is the one that is really there.
            return max(matches, key=lambda i: len(i.data)), None
        img, diff = nearest
        return None, ("no approved image is installed at 0x%08X: the closest is %s, and flash "
                      "differs from it at 0x%08X" % (img.addr, img.name, diff))

    def judge(self, session):
        img, why = self.installed(session)
        if img is None:
            return Verdict(False, None, why)
        if img.name not in self.accept:
            return Verdict(False, img.name, "the installed image is %s; this scenario accepts only %s"
                           % (img.name, " or ".join(self.accept)))
        lo, hi = self.run_in or (img.addr, img.end)
        for pc, exc in session.sample_cpu(self.samples, self.interval):
            if exc in FAULTS:
                return Verdict(False, img.name, "%s is installed but the core is in the %s "
                               "handler (PC 0x%08X)" % (img.name, FAULTS[exc], pc))
            if not lo <= pc < hi:
                return Verdict(False, img.name, "%s is installed but not running: PC 0x%08X is "
                               "outside 0x%08X..0x%08X" % (img.name, pc, lo, hi))
        return Verdict(True, img.name)


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
                  cfg.get("interval", 0.02))
