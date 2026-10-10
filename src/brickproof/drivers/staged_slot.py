"""Built-in driver for the most common update style: the new image is written to a
staging slot, and the bootloader applies it on the next boot (MCUboot's overwrite
mode, most OTA agents, the BrickProof demo).

Nothing is spoken over a protocol. The driver puts the image in the slot, and the
reset that follows starts the update, so cuts are armed before the first instruction.
What booted is read from the UART.

Options (adapter.yaml, driver.options):
  slot          address of the staging slot
  image         new image file, relative to the target folder
  alive         regex: some valid image is running (for example "APP v[0-9]+")
  expect        optional regex the device must print after recovering
                (for example "APP v2": the update was not lost)
  boot_timeout  virtual seconds to wait for those, default 2
  rollback      optional {image, forbidden}: after recovering, stage this older
                image and reboot; the device must NOT print `forbidden`
"""
import os
import re
import shutil


class StagedSlot:
    update_on_boot = True

    def __init__(self, session, adapter):
        self.s = session
        opt = adapter.driver_options
        for key in ("slot", "image", "alive"):
            if key not in opt:
                raise ValueError("staged_slot: driver.options.%s is required" % key)
        self.slot = opt["slot"]
        self.image = self._copy_in(adapter.target, opt["image"], "staged.img")
        self.alive_re = re.compile(opt["alive"])
        self.expect_re = re.compile(opt["expect"]) if opt.get("expect") else None
        self.timeout = float(opt.get("boot_timeout", 2.0))
        self.settle = adapter.boot_settle
        rb = opt.get("rollback")
        if rb:
            self.rollback_image = self._copy_in(adapter.target, rb["image"], "rollback.img")
            self.forbidden_re = re.compile(rb["forbidden"])
        else:
            self.rollback_image = None

    def _copy_in(self, target, rel, name):
        src = os.path.join(target, rel)
        if not os.path.exists(src):
            raise FileNotFoundError("staged_slot: image not found: %s" % src)
        shutil.copyfile(src, os.path.join(self.s.workdir, name))
        return name

    def _wait_for(self, pattern, seconds):
        waited = 0.0
        while waited < seconds:
            if pattern.search(self.s.uart_text()):
                return True
            self.s.run_for(0.05)
            waited += 0.05
        return bool(pattern.search(self.s.uart_text()))

    def prepare(self):
        self.s.load_binary(self.image, self.slot)

    def start_update(self):
        pass                            # the reset before this already started it

    def alive(self):
        return self._wait_for(self.alive_re, self.timeout)

    def check_recovered(self):
        if self.expect_re and not self._wait_for(self.expect_re, self.timeout):
            return False, "running, but not the expected image (%s)" % self.expect_re.pattern
        if self.rollback_image:
            self.s.load_binary(self.rollback_image, self.slot)
            self.s.power_cycle(settle=self.settle)
            if self._wait_for(self.forbidden_re, self.timeout):
                return False, "rollback: the older image was accepted after this cut"
        return True, ""


def make_driver(session, adapter):
    return StagedSlot(session, adapter)
