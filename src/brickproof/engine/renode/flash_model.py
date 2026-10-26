"""The flash model's controls: arming a cut and learning where it fired, the chip rules it
saw broken, and the trace of every operation."""
import os
import time
from brickproof.engine.common import MachineHung
from brickproof.engine.flash_regs import (REG_AUDIT,
    REG_CUTPOINT,
    REG_CUT_ADDR,
    REG_CUT_FIRED,
    REG_CUT_KIND,
    REG_CUT_PAGE,
    REG_FAULT_ADDR,
    REG_FAULT_PC,
    REG_OPCOUNT,
    REG_PCROP_AT,
    REG_PCROP_READS,
    REG_PROTECTED,
    REG_PROTECTED_AT,
    REG_REFUSED,
    REG_REFUSED_AT,
    REG_RESYNC,
    REG_TRACE,
    TRACE_KINDS)




class FlashModel:
    """One part of RenodeSession (engine/session.py): what the module docstring says."""

    def _ctl(self, reg):
        return self.flash.controller + reg

    def _set(self, reg, value):
        """The monitor command that writes one of the flash model's test registers."""
        return "sysbus WriteDoubleWord 0x%X 0x%X" % (self._ctl(reg), value)

    def _get(self, reg):
        return "sysbus ReadDoubleWord 0x%X" % self._ctl(reg)

    def flash_ops(self):
        """Flash operations started since the counter was last cleared."""
        return self.read_word(self._ctl(REG_OPCOUNT))

    def set_cut(self, opcount):
        """Cut power when the flash model is about to start operation number `opcount`."""
        self.write_word(self._ctl(REG_CUTPOINT), opcount)

    def set_cut_on_erase(self, page_addr):
        """Cut power when the firmware is about to erase the page at page_addr."""
        self.write_word(self._ctl(REG_CUT_PAGE), page_addr)

    def cut_fired(self):
        return self.read_word(self._ctl(REG_CUT_FIRED)) == 1

    def run_until_cut(self, limit, step=0.01, longest=0.16):
        """Advance until the armed cut fires. True if it did within `limit` virtual seconds.
        The steps grow: a cut a few milliseconds in is noticed at once, and one behind a
        second-long sector erase does not cost a hundred round trips to the emulator.
        Looking late is harmless, a cut stops the CPU where it fired."""
        waited = 0.0
        while waited < limit:
            step = min(step, limit - waited)
            t0 = time.time()
            try:
                reply = self.cmd_batch([self._run_cmd(step), self.CHECK_STATE, self._get(REG_CUT_FIRED)],
                                       timeout=self.hang_limit(step))
            except TimeoutError:
                raise MachineHung("emulated time stopped advancing") from None
            self._check_state(self._values(reply)[-2])
            if step >= 0.05:
                # this wait learns the machine's pace too, as run_for does
                self._slowest = max(self._slowest, (time.time() - t0) / step)
            self.virtual_time += step
            waited += step
            if self._values(reply)[-1] == 1:
                self._pull()
                return True
            step = min(step * 2, longest)
        self._pull()
        return False

    def cut_info(self):
        """(kind, page address): kind 1 = erase cut before it ran, 2 = program, 0 = none."""
        kind, addr = self.read_words([self._ctl(REG_CUT_KIND), self._ctl(REG_CUT_ADDR)])
        return kind, addr

    def cut_status(self):
        """(kind, page address, operations started), read together after a cut."""
        return tuple(self.read_words([self._ctl(r) for r in (REG_CUT_KIND, REG_CUT_ADDR, REG_OPCOUNT)]))

    def violations(self):
        """Everything the firmware did that the emulator lets pass and the chip does not,
        read in one go:
          fault    (address, pc): it touched memory the chip does not have
          refused  (count, first address): programs over cells that were not erased
          stray    first address where flash changed with no flash operation behind it
          protected  (count, first address): erases or programs in write-protected pages
          pcrop    (count, first address): data reads of proprietary code (STM32F4 PCROP)
        Each is None when clean. A power cycle clears the fault; restore_flash the rest."""
        fa, fpc, n, at, stray, wn, wat, pn, pat = self._values(self.cmd_batch(
            [self._get(REG_FAULT_ADDR), self._get(REG_FAULT_PC), self._get(REG_REFUSED),
             self._get(REG_REFUSED_AT), self._set(REG_AUDIT, 1), self._get(REG_AUDIT),
             self._get(REG_PROTECTED), self._get(REG_PROTECTED_AT),
             self._get(REG_PCROP_READS), self._get(REG_PCROP_AT)]))
        return {"fault": (fa, fpc) if fa else None,
                "refused": (n, at) if n else None,
                "stray": stray or None,
                "protected": (wn, wat) if wn else None,
                "pcrop": (pn, pat) if pn else None}

    def bus_fault(self):
        return self.violations()["fault"]

    def flash_resync(self):
        """Tell the flash model that flash is now what it should be. The model keeps a
        shadow copy that only real flash operations update; anything the engine puts
        into flash itself has to be declared, or it would look like a stray write."""
        self.write_word(self._ctl(REG_RESYNC), 1)

    def _clear_checks(self):
        return [self._set(reg, 0) for reg in (REG_AUDIT, REG_REFUSED, REG_REFUSED_AT, REG_PROTECTED,
                                             REG_PROTECTED_AT, REG_PCROP_READS, REG_PCROP_AT)]

    TRACE_NAME = "trace.txt"

    def trace_start(self):
        """Log every flash operation from now on (see the flash model's header)."""
        open(os.path.join(self.workdir, self.TRACE_NAME), "w").close()
        self.write_word(self._ctl(REG_TRACE), 1)

    def trace_stop(self):
        """Stop logging and return the operations as a list of dicts:
        index, kind (erase / mass_erase / program / refused), addr, and for a program
        its value. A refused program is one the chip would not have done.
        `inferred` marks a program whose address is a guess: it wrote what was already
        there, so nothing in flash changed."""
        self.write_word(self._ctl(REG_TRACE), 0)
        ops = []
        with open(os.path.join(self.workdir, self.TRACE_NAME)) as f:
            for line in f:
                parts = line.split()
                if not parts:
                    continue
                # a trailing @N is how many microseconds the chip spent on the operation,
                # #N how many bytes an erase took where that is not fixed
                us = [int(t[1:]) for t in parts if t.startswith("@")]
                length = [int(t[1:], 16) for t in parts if t.startswith("#")]
                parts = [t for t in parts if t[0] not in "@#"]
                op = {"index": len(ops), "kind": TRACE_KINDS[parts[0]], "addr": int(parts[1], 16)}
                if parts[0] in ("P", "X"):
                    # the number of hex digits says how many bytes the program wrote
                    op["value"] = int(parts[2], 16)
                    op["size"] = len(parts[2].replace("0x", "")) // 2
                if parts[0] == "Q":
                    op["total_us"] = int(parts[2])     # partial erase time on the page so far
                if parts[0] == "X":
                    op["old"] = int(parts[3], 16)
                elif parts[0] == "P?":
                    op["inferred"] = True
                if us:
                    op["us"] = us[0]
                if length:
                    op["length"] = length[0]
                ops.append(op)
        return ops
