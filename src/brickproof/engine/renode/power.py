"""Resets and power: a reboot keeps flash and RAM, a power cycle keeps only flash."""
from brickproof.engine.flash_regs import (NEVER,
    REG_CUTPOINT,
    REG_CUT_PAGE,
    REG_FAULT_ADDR,
    REG_FAULT_PC,
    REG_OPCOUNT,
    REG_PENDING,
    STATE_PWR_ASLEEP,
    STATE_PWR_FLAGS,
    STATE_RESETS)




class Power:
    """One part of RenodeSession (engine/session.py): what the module docstring says."""

    def reboot(self, settle=1.5):
        """Reset the CPU and peripherals; flash contents are kept. A reset also
        re-initialises the flash model, so arm a cut after it, not before.
        settle=0 leaves the machine paused at the reset vector."""
        self.cmd_batch(self._reset_lines())
        self.rx.clear()
        if settle:
            self.run_for(settle)

    def _after_reset(self):
        """What a reset must be followed by: boot from flash, and the adapter's own lines."""
        return ["cpu VectorTableOffset 0x%X" % self.vector_table] + list(self.reset_cmds)

    def _reset_lines(self):
        return ["machine Reset"] + self._after_reset()

    def uart_text(self):
        return self.rx.decode(errors="replace")

    def power_cycle(self, settle=1.5):
        """A real power loss: RAM is lost, flash is kept, everything restarts.
        ZeroAll, not FillWithConstantByte: the latter takes over a minute here."""
        # One batch: every monitor round trip costs about 35 ms, and this runs two or
        # three times per cut. The flash model's state outlives resets on purpose, so
        # it is cleared here; PENDING too, because a program cut short never finishes.
        self.cmd_batch(["%s ZeroAll" % self.ram, "cpu IsHalted false",
                        self._set(REG_CUTPOINT, NEVER), self._set(REG_CUT_PAGE, NEVER),
                        self._set(REG_OPCOUNT, 0), self._set(REG_FAULT_ADDR, 0),
                        self._set(REG_FAULT_PC, 0), self._set(REG_PENDING, 0),
                        # the PWR model's wake flags and pending wake (models/stm32_pwr.py):
                        # a power-on reset clears them
                        "sysbus WriteDoubleWord 0x%X 0" % (STATE_PWR_FLAGS),
                        "sysbus WriteDoubleWord 0x%X 0" % (STATE_PWR_ASLEEP)]
                       + (["%s PowerCycle" % self._ext] if self.flash.ext_size else [])
                       + self._reset_lines()
                       # the reset just made is the power-up itself, not one to count
                       + ["sysbus WriteDoubleWord 0x%X 0" % STATE_RESETS])
        self.rx.clear()
        if settle:
            self.run_for(settle)

    def resets(self):
        """How many times the machine has reset since the last power cycle: the firmware
        asking for one, a watchdog, a lock-up. A device that keeps counting is in a loop."""
        return self.read_word(STATE_RESETS)

    def pc(self):
        for tok in self.cmd("cpu PC").split():
            if tok.startswith("0x"):
                return int(tok, 16)
        return None
