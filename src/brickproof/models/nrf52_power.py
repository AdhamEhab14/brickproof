# nRF52 System OFF for the emulator. Writing 1 to POWER.SYSTEMOFF (0x40000500) turns the chip
# off: RAM loses power (RAM retention is not modelled), and a wake source (a GPIO DETECT, NFC,
# LPCOMP) brings it back through a reset. Renode's NRF_CLOCK sits on the same registers and
# ignores the write, so this is a watchpoint on that one address, set up once when the machine
# is created (the engine includes this file). The wake comes WAKE_AFTER_US later (adapter:
# low_power.wake_after). RESETREAS is not modelled: firmware cannot tell this wake from a reset.
#
# The state words are the STM32 PWR model's (models/stm32_pwr.py), so a power cycle of the
# device cancels a wake still to come in the same way.
STATE = 0x90000000
RAM_BASE = 0x20000000
RAM_SIZE = 0x40000
WAKE_AFTER_US = 500000
SYSTEMOFF = 0x40000500
STANDBYS, ASLEEP = 42, 45

from System import Action, Array, Byte
from Antmicro.Renode.Time import TimeInterval
from Antmicro.Renode.Peripherals.Bus import Access, BusHookDelegate, SysbusAccessWidth


def system_off_hook(machine):
    b = machine.SystemBus

    def st(i):
        return int(b.ReadDoubleWord(STATE + 4 * i))

    def st_w(i, v):
        b.WriteDoubleWord(STATE + 4 * i, v & 0xFFFFFFFF)

    def wake(token):
        if st(ASLEEP) != token:
            return                  # the device was powered off and on meanwhile: no wake
        st_w(ASLEEP, 0)
        for c in b.GetCPUs():
            c.IsHalted = False
        machine.RequestReset()

    def on_write(cpu, address, width, value):
        if not int(value) & 1:
            return
        token = st(STANDBYS) + 1
        st_w(STANDBYS, token)
        st_w(ASLEEP, token)
        b.WriteBytes(Array[Byte]([0] * RAM_SIZE), RAM_BASE)       # RAM loses power
        for c in b.GetCPUs():
            c.IsHalted = True
        machine.ScheduleAction(TimeInterval.FromMicroseconds(WAKE_AFTER_US),
                               Action[TimeInterval](lambda _, t=token: wake(t)))

    b.AddWatchpointHook(SYSTEMOFF, SysbusAccessWidth.DoubleWord, Access.Write, BusHookDelegate(on_write))


system_off_hook(self.Machine)
