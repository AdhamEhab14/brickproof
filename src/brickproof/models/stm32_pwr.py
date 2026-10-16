# STM32F1 / STM32F4 power controller (PWR) for the emulator: the low-power modes, as far as
# a power-fail test needs them. Renode takes every WFI as a light sleep that any interrupt
# ends with RAM intact. On the chip, with SLEEPDEEP set in the core:
#
#   PDDS set: Standby. The core and its RAM lose power. A wake source (the WKUP pin, an RTC
#     alarm, the reset pin, the independent watchdog) brings the chip back through a reset,
#     with SBF set in CSR to say where it came from. Firmware that kept anything in RAM
#     across Standby finds it gone;
#   PDDS clear: Stop. The clocks stop and RAM is kept; an external interrupt ends it. Here the
#     SysTick stops for as long as the core is in Stop (other timers keep counting in the
#     emulator, which they do not on the chip);
#   the option bits nRST_STDBY and nRST_STOP, when cleared, make entering either mode reset
#     the chip instead.
#
# The model sees the core enter WFI through Renode's WFI hook. A wake from Standby comes
# WAKE_AFTER_US after it went in (adapter: low_power.wake_after), standing for whatever wake
# source the board uses. SBF and WUF are kept in the state memory, because the reset that
# ends Standby would otherwise clear them with this script's own variables; a power cycle of
# the device clears them, as a power-on reset does, and cancels a wake still to come.
#
# The engine rewrites the constant lines below for the chip and the adapter.
STATE = 0x90000000
RAM_BASE = 0x20000000
RAM_SIZE = 0x5000
OB_USER = 0x1FFFF802        # the option byte that holds nRST_STOP and nRST_STDBY
NRST_STOP_BIT = 1           # F1: bits 1 and 2 of USER; F4: bits 6 and 7
NRST_STDBY_BIT = 2
WAKE_AFTER_US = 500000
SCB_SCR = 0xE000ED10
SYST_CSR = 0xE000E010
CR_LPDS, CR_PDDS, CR_CWUF, CR_CSBF = 1, 2, 4, 8
CSR_WUF, CSR_SBF = 1, 2
MAGIC = 0x50570001
(HOOKED, FLAGS, STANDBYS, SYSTICK_SAVED, PWR_CR, ASLEEP) = range(40, 46)   # state words, after the flash models'

from System import Action, Array, Byte
from Antmicro.Renode.Time import TimeInterval

bus = None if request.IsInit else self.GetMachine().SystemBus


def hook(machine):
    # Installed once per emulator: the core's WFI, with its own bus and machine, because it
    # outlives this script (a reset runs the script's init again and drops `bus`).
    b = machine.SystemBus

    def st(i):
        return int(b.ReadDoubleWord(STATE + 4 * i))

    def st_w(i, v):
        b.WriteDoubleWord(STATE + 4 * i, v & 0xFFFFFFFF)

    def wake(token):
        if st(ASLEEP) != token:
            return                  # the device was powered off and on meanwhile: no wake
        st_w(ASLEEP, 0)
        st_w(FLAGS, st(FLAGS) | CSR_WUF | CSR_SBF)
        for c in b.GetCPUs():
            c.IsHalted = False
        machine.RequestReset()

    def on_wfi(entering):
        if not entering:
            saved = st(SYSTICK_SAVED)
            if saved:
                b.WriteDoubleWord(SYST_CSR, saved & 7)          # out of Stop: the SysTick runs again
                st_w(SYSTICK_SAVED, 0)
            return
        if not int(b.ReadDoubleWord(SCB_SCR)) & 4:
            return                                              # plain sleep: Renode has it right
        user = int(b.ReadByte(OB_USER))
        standby = st(PWR_CR) & CR_PDDS
        if not (user >> (NRST_STDBY_BIT if standby else NRST_STOP_BIT)) & 1:
            machine.RequestReset()                              # the option bit says: reset instead
            return
        if standby:
            token = st(STANDBYS) + 1
            st_w(STANDBYS, token)
            st_w(ASLEEP, token)
            b.WriteBytes(Array[Byte]([0] * RAM_SIZE), RAM_BASE)    # RAM loses power
            for c in b.GetCPUs():
                c.IsHalted = True
            machine.ScheduleAction(TimeInterval.FromMicroseconds(WAKE_AFTER_US),
                                   Action[TimeInterval](lambda _, t=token: wake(t)))
        else:
            csr = int(b.ReadDoubleWord(SYST_CSR))
            if csr & 1:
                st_w(SYSTICK_SAVED, csr | 0x80000000)           # remember it, even if it was 0
                b.WriteDoubleWord(SYST_CSR, csr & ~3)           # Stop: no SysTick to wake the core

    def after_reset(m):
        st_w(PWR_CR, 0)                                         # CR is cleared by any reset
        st_w(SYSTICK_SAVED, 0)

    for c in b.GetCPUs():
        c.AddHookAtWfiStateChange(Action[bool](on_wfi))
    machine.MachineReset += after_reset


if request.IsInit:
    csr_rest = 0
elif request.IsWrite or request.IsRead:
    if int(bus.ReadDoubleWord(STATE + 4 * HOOKED)) != MAGIC:
        hook(self.GetMachine())
        bus.WriteDoubleWord(STATE + 4 * HOOKED, MAGIC)
    o = request.Offset
    cr = int(bus.ReadDoubleWord(STATE + 4 * PWR_CR))
    flags = int(bus.ReadDoubleWord(STATE + 4 * FLAGS))
    if request.IsRead:
        if o == 0x00: request.Value = cr
        elif o == 0x04: request.Value = flags | csr_rest
        else: request.Value = 0
    else:
        v = request.Value
        if o == 0x00:
            if v & CR_CWUF: flags &= ~CSR_WUF
            if v & CR_CSBF: flags &= ~CSR_SBF
            bus.WriteDoubleWord(STATE + 4 * FLAGS, flags)
            bus.WriteDoubleWord(STATE + 4 * PWR_CR, v & ~(CR_CWUF | CR_CSBF))
        elif o == 0x04:
            csr_rest = v & 0x100                                # EWUP: kept, not acted on
