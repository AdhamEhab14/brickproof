# nRF52840 flash controller (NVMC) for the emulator. Renode has no model of it at all:
# its flash is plain memory that any store changes. This one does for the nRF52 what the
# STM32 models next to it do (count operations, stop the CPU at a chosen one, enforce what
# the chip enforces, notice stray writes, log the trace), for a chip that works
# differently from both:
#
#   there are no keys and no lock. CONFIG.WEN says what the flash will do: read only
#     (Ren), take stores as programs (Wen) or take erase commands (Een);
#   an erase wipes a 4 KB page (ERASEPAGE takes its address) or the whole flash (ERASEALL);
#   a program is a store of a whole, aligned 32-bit word. Anything narrower or unaligned
#     is a hard fault on the chip; here it is refused and reported;
#   a program can only clear bits, and a word may be written at most twice (nWRITE)
#     between two erases. A third write is outside what the chip guarantees, so it is
#     refused and reported too;
#   the CPU halts while the NVMC writes or erases, if it runs from flash, which is where
#     firmware runs. The model skips the same virtual time, as the STM32 models do.
#
# A program is an operation when the CPU stores into flash while CONFIG.WEN is Wen. The
# store goes straight into Renode's flash memory, so for as long as WEN is Wen the model
# listens to the CPU's memory accesses and applies the chip's rules as each store lands.
# A shadow copy of flash changes only with real operations; whatever differs from it
# later was stored with WEN not set, which the chip ignores: that is what the audit
# reports. How often each word was written since its page was erased is kept in memory
# (COUNTS), not in the model, because a reset of the CPU does not undo it on the chip.
#
# From the nRF52840 Product Specification: tWRITE 41 us, tERASEPAGE 85 ms, tERASEALL
# 169 ms. The specification gives these as maximums only, so typical and slowest are the
# same here. nWRITE = 2.
#
# Not modelled: partial erase (ERASEPAGEPARTIAL), the UICR (ERASEUICR is ignored, and UICR
# is not part of the flash image), the ACL write protection, and the instruction cache.
#
# The test-only registers at 0x100..0x14C are the same as the STM32 models' (see the F1
# model). The NVMC's own registers start at 0x400, so they do not meet. "cut page" (0x114)
# takes the first address of a page.
#
# Renode gives Python peripherals no parameters, so the engine rewrites the constant lines
# below with the target's values when it copies this file.
PAGE = 0x1000
FLASH_BASE = 0x0
FLASH_SIZE = 0x100000
STATE = 0x90000000
SHADOW = 0x91000000
EXPECT = 0x92000000
COUNTS = 0x93000000         # one byte per flash word: writes since its page was erased
TRACE_FILE = ""
CHUNK = 0x400               # flash is compared with its shadow in pieces of this size
TIMING = 0
T_WRITE_US = (0, 41, 41)
T_ERASE_US = (0, 85000, 85000)
T_ERASEALL_US = (0, 169000, 169000)
N_WRITE = 2
NEVER = 0xFFFFFFFF
MAGIC = 0x52F0000A          # state word 0: set once the defaults below are in place
WEN_REN, WEN_WEN, WEN_EEN = 0, 1, 2

from System import Array, Byte, Convert
from Antmicro.Renode.Time import TimeInterval

(OPCOUNT, CUTPOINT, CUT_HIT, CUT_KIND, CUT_ADDR, CUT_PAGE, FAULT_ADDR, FAULT_PC,
 TRACE, PENDING, AUDIT, REFUSED, REFUSED_AT, LAST, _RESYNC, COMPARE, CMP_FROM, CMP_LEN,
 PROTECTED, PROTECTED_AT) = range(1, 21)

bus = None if request.IsInit else self.GetMachine().SystemBus   # no machine yet at construction


def st(i):
    return int(bus.ReadDoubleWord(STATE + 4 * i))


def st_w(i, v):
    bus.WriteDoubleWord(STATE + 4 * i, v & 0xFFFFFFFF)


def ensure_state():
    # the state memory starts as zeros, and a cutpoint of 0 would cut at once
    if st(0) != MAGIC:
        st_w(CUTPOINT, NEVER)
        st_w(CUT_PAGE, NEVER)
        resync()
        st_w(0, MAGIC)
        self.GetMachine().MachineReset += after_reset


def after_reset(machine):
    # a reset ends any programming that was going on: CONFIG is back to Ren
    for c in machine.SystemBus.GetCPUs():
        c.SetHookAtMemoryAccess(None)


def log(text):
    if st(TRACE) == 1:
        f = open(TRACE_FILE, "a")
        f.write(text + chr(10))
        f.close()


def spend(us):
    # the NVMC is busy for this long and the CPU, which runs from flash, waits
    if us:
        for c in bus.GetCPUs():
            c.SkipTime(TimeInterval.FromMicroseconds(us))
    return us


def resync():
    # flash is now what it should be (the engine restored it): it is the shadow, and no
    # word counts as written since its erase
    bus.WriteBytes(bus.ReadBytes(FLASH_BASE, FLASH_SIZE), SHADOW)
    bus.WriteBytes(Array[Byte]([0] * (FLASH_SIZE // 4)), COUNTS)


def shadow_of(addr):
    return SHADOW + (addr - FLASH_BASE)


def count_of(addr):
    return COUNTS + (addr - FLASH_BASE) // 4


def erase(addr, size):
    # an erase: in flash, in the shadow, and the write counts of its words
    ff = Array[Byte]([0xFF] * size)
    bus.WriteBytes(ff, addr)
    bus.WriteBytes(ff, shadow_of(addr))
    bus.WriteBytes(Array[Byte]([0] * (size // 4)), count_of(addr))


def get(addr, size):
    raw = bus.ReadBytes(addr, size)
    v = 0
    for i in range(size):
        v |= int(raw[i]) << (8 * i)
    return v


def put(addr, size, v):
    bus.WriteBytes(Array[Byte]([(v >> (8 * i)) & 0xFF for i in range(size)]), addr)


def all_differences():
    # every byte where flash is not what the shadow says. Chunks are compared as
    # strings first (native code), so a clean flash costs about a millisecond.
    now = bus.ReadBytes(FLASH_BASE, FLASH_SIZE)
    was = bus.ReadBytes(SHADOW, FLASH_SIZE)
    out = []
    if Convert.ToBase64String(now) != Convert.ToBase64String(was):
        for p in range(0, FLASH_SIZE, CHUNK):
            if Convert.ToBase64String(now, p, CHUNK) != Convert.ToBase64String(was, p, CHUNK):
                for i in range(p, p + CHUNK):
                    if now[i] != was[i]:
                        out.append(FLASH_BASE + i)
    return out


def first_difference(addr, n):
    # first address in [addr, addr+n) where flash is not what bpExpect holds, or 0
    now = bus.ReadBytes(addr, n)
    want = bus.ReadBytes(addr - FLASH_BASE + EXPECT, n)
    if Convert.ToBase64String(now) == Convert.ToBase64String(want):
        return 0
    for i in range(n):
        if now[i] != want[i]:
            return addr + i
    return 0


def listen(on):
    # Hear every memory access of the CPU, or stop hearing them. Ending the current
    # block of translated code makes the very next instruction count already.
    for c in bus.GetCPUs():
        c.SetHookAtMemoryAccess(on_access if on else None)
        if on:
            c.RequestTranslationBlockRestart()


def on_access(pc, operation, virtual, addr, width, value):
    # called by the CPU after each of its memory accesses while WEN is Wen
    if str(operation) != "MemoryWrite":
        return
    addr = int(addr)
    if FLASH_BASE <= addr < FLASH_BASE + FLASH_SIZE:
        program(addr, int(width), int(value))


def refuse(addr, width, value, old):
    # a store the chip does not take as a program: the old value stays
    put(addr, width, old)
    if not st(REFUSED):
        st_w(REFUSED_AT, addr)
    st_w(REFUSED, st(REFUSED) + 1)
    log("X 0x%08X 0x%0*X 0x%0*X" % (addr, 2 * width, value, 2 * width, old))


def program(a, width, value):
    # One store into flash while WEN is Wen. It has already landed in Renode's memory.
    # What the chip makes of it is decided here.
    old = get(shadow_of(a), width)
    if st(CUT_HIT):
        put(a, width, old)                      # the power is off
        return
    if not begin(False, 0):
        put(a, width, old)                      # the power goes just before this store
        for c in bus.GetCPUs():
            c.RequestTranslationBlockRestart()  # and not after the rest of this block
        return
    spend(T_WRITE_US[TIMING])
    if width != 4 or a % 4:
        refuse(a, width, value, old)            # a hard fault on the chip
        return
    writes = int(bus.ReadByte(count_of(a)))
    if writes >= N_WRITE:
        refuse(a, width, value, old)            # nWRITE: no more without an erase
        return
    stored = old & value                        # a program clears bits, it cannot set them
    put(a, 4, stored)
    put(shadow_of(a), 4, stored)
    bus.WriteByte(count_of(a), writes + 1)
    log("P 0x%08X 0x%08X @%d" % (a, stored, T_WRITE_US[TIMING]))


def begin(erasing, addr):
    # One operation is about to start. Returns False if this is where the power goes:
    # the CPU is stopped and the operation must not happen.
    if st(CUT_HIT):
        return False
    opcount = st(OPCOUNT)
    if opcount == st(CUTPOINT) or (erasing and addr == st(CUT_PAGE)):
        st_w(CUT_HIT, 1)
        st_w(CUT_KIND, 1 if erasing else 2)
        st_w(CUT_ADDR, addr if erasing else 0)
        for c in bus.GetCPUs():
            c.IsHalted = True                   # power is gone: stop executing right here
        return False
    st_w(OPCOUNT, opcount + 1)
    return True


if request.IsInit:
    config = WEN_REN
elif request.IsWrite or request.IsRead:
    ensure_state()
    o = request.Offset

    if request.IsRead:
        if o == 0x400 or o == 0x408: request.Value = 1     # READY, READYNEXT: always ready
        elif o == 0x504: request.Value = config
        elif 0x100 <= o <= 0x14C: request.Value = st((o - 0x100) // 4 + 1)
        else: request.Value = 0
    else:
        v = request.Value
        if o == 0x504:
            listening = config == WEN_WEN
            config = v & 7
            if (config == WEN_WEN) != listening:
                listen(config == WEN_WEN)       # stores into flash are programs while Wen
        elif o == 0x508 or o == 0x510:         # ERASEPAGE (and ERASEPCR1 / ERASEPCR0)
            a = FLASH_BASE + ((v - FLASH_BASE) // PAGE) * PAGE
            if config == WEN_EEN and FLASH_BASE <= a < FLASH_BASE + FLASH_SIZE:
                if begin(True, a):
                    erase(a, PAGE)
                    log("E 0x%08X @%d" % (a, spend(T_ERASE_US[TIMING])))
        elif o == 0x50C:                       # ERASEALL
            if config == WEN_EEN and v & 1:
                if begin(True, FLASH_BASE):
                    erase(FLASH_BASE, FLASH_SIZE)
                    log("M 0x%08X @%d" % (FLASH_BASE, spend(T_ERASEALL_US[TIMING])))
        elif o == 0x104 or o == 0x114:       # arming a cut clears the last one's result
            st_w(CUTPOINT if o == 0x104 else CUT_PAGE, v)
            st_w(CUT_HIT, 0)
            st_w(CUT_KIND, 0)
            st_w(CUT_ADDR, 0)
        elif o == 0x128:
            if v:
                diffs = [] if st(AUDIT) else all_differences()
                if diffs:
                    st_w(AUDIT, diffs[0])
            else:
                st_w(AUDIT, 0)
        elif o == 0x138:
            resync()
        elif o == 0x13C:
            n = st(CMP_LEN)
            st_w(COMPARE, first_difference(st(CMP_FROM), n) if n else first_difference(FLASH_BASE, FLASH_SIZE))
        elif 0x100 <= o <= 0x14C:
            st_w((o - 0x100) // 4 + 1, v)
