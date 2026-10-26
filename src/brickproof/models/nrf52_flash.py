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
# The UICR (0x10001000) is flash too: stores into it while WEN is Wen are programs under
# the same rules, ERASEUICR erases it, and ERASEALL erases it with the code area. It is part
# of the flash image, after the code area, like the STM32 option bytes.
#
# Partial erase (ERASEPAGEPARTIAL) erases a page for ERASEPAGEPARTIALCFG milliseconds; the
# page is erased once the time spent on it adds up to tERASEPAGE, and until then the
# specification calls its bits undefined. Here each 0 bit of the page needs its own share
# of tERASEPAGE before it reads 1 (partial_needs, the same function as in trace.py), so a
# page part way through is old data with some bits already flipped, never fresh 0s. The
# time spent is kept per page (PARTIAL) and logged with each step; a power cut loses it,
# which is the safe side: firmware that starts over erases for longer than it needs.
#
# ACL: eight regions (0x800 + 16 n: ADDR, SIZE, PERM), each written once until reset.
# PERM bit 1 blocks writes and erases, bit 2 reads. On the chip a blocked access is a bus
# fault; here it is blocked and reported: a write or erase as write protection (0x148,
# 0x14C, the STM32 models' registers), a read as a protected read (0x150, 0x154). Whether
# the chip also blocks ERASEPAGE and ERASEALL in a region is not in the specification; the
# model blocks them.
#
# Not modelled: APPROTECT's effect on a debugger (the UICR only holds it), the instruction
# cache.
#
# The test-only registers at 0x100..0x154 are the same as the STM32 models' (see the F1
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
OB_BASE = 0x10001000        # the UICR
OB_SIZE = 0x400
TRACE_FILE = ""
CHUNK = 0x400               # flash is compared with its shadow in pieces of this size
TIMING = 0
WORN_FROM = 0x0           # worn pages (flash.worn): [WORN_FROM, WORN_TO), none by default
WORN_TO = 0x0
T_WRITE_US = (0, 41, 41)
T_ERASE_US = (0, 85000, 85000)
T_ERASEALL_US = (0, 169000, 169000)
T_PAGE_ERASE = 85000        # what partial erases of a page must add up to, in microseconds
N_WRITE = 2
NEVER = 0xFFFFFFFF
MAGIC = 0x52F0000A          # state word 0: set once the defaults below are in place
WEN_REN, WEN_WEN, WEN_EEN = 0, 1, 2

from System import Array, Byte, Convert
from Antmicro.Renode.Time import TimeInterval
from Antmicro.Renode.Core import EmulationManager

(OPCOUNT, CUTPOINT, CUT_HIT, CUT_KIND, CUT_ADDR, CUT_PAGE, FAULT_ADDR, FAULT_PC,
 TRACE, PENDING, AUDIT, REFUSED, REFUSED_AT, LAST, _RESYNC, COMPARE, CMP_FROM, CMP_LEN,
 PROTECTED, PROTECTED_AT, READS, READS_AT) = range(1, 23)
RESETS = 60                 # state word: resets since the engine last cleared it (all models)
UICR_COUNTS = COUNTS + FLASH_SIZE // 4      # then the UICR's words
PARTIAL = UICR_COUNTS + 0x400               # then microseconds of partial erase, a word a page

bus = None if request.IsInit else self.GetMachine().SystemBus   # no machine yet at construction


# @FLASH_COMMON@ st, st_w, log, wake_clock, spend, first_difference, get, put:
# models/flash_common.py, put here when the model is copied (engine/workdir.py)


def ensure_state():
    # the state memory starts as zeros, and a cutpoint of 0 would cut at once
    if st(0) != MAGIC:
        st_w(CUTPOINT, NEVER)
        st_w(CUT_PAGE, NEVER)
        resync()
        st_w(0, MAGIC)
        self.GetMachine().MachineReset += after_reset


def after_reset(machine, resets=STATE + 4 * RESETS):
    # a reset ends any programming that was going on: CONFIG is back to Ren. Every reset
    # is counted, so the engine can tell a device that keeps rebooting.
    b = machine.SystemBus
    b.WriteDoubleWord(resets, (int(b.ReadDoubleWord(resets)) + 1) & 0xFFFFFFFF)
    for c in b.GetCPUs():
        c.SetHookAtMemoryAccess(None)


def resync():
    # flash is now what it should be (the engine restored it): it is the shadow, no word
    # counts as written since its erase, and no page is part way through a partial erase
    bus.WriteBytes(bus.ReadBytes(FLASH_BASE, FLASH_SIZE), SHADOW)
    bus.WriteBytes(bus.ReadBytes(OB_BASE, OB_SIZE), SHADOW + FLASH_SIZE)
    bus.WriteBytes(Array[Byte]([0] * (FLASH_SIZE // 4 + 0x400 + 4 * (FLASH_SIZE // PAGE))), COUNTS)


def in_uicr(addr):
    return OB_BASE <= addr < OB_BASE + OB_SIZE


def shadow_of(addr):
    if in_uicr(addr):
        return SHADOW + FLASH_SIZE + (addr - OB_BASE)
    return SHADOW + (addr - FLASH_BASE)


def count_of(addr):
    if in_uicr(addr):
        return UICR_COUNTS + (addr - OB_BASE) // 4
    return COUNTS + (addr - FLASH_BASE) // 4


def partial_needs(i):
    # how many microseconds of erase bit i of a page (8 * byte offset + bit) needs before
    # it reads 1. Spread evenly over tERASEPAGE, the same on every run (see trace.py).
    h = (i * 2654435761) & 0xFFFFFFFF
    h ^= h >> 15
    return 1 + h % T_PAGE_ERASE


def partial_erase(a, us):
    # ERASEPAGEPARTIAL: `us` more microseconds on the page at a. Returns the total so far.
    slot = PARTIAL + 4 * ((a - FLASH_BASE) // PAGE)
    total = int(bus.ReadDoubleWord(slot)) + us
    if total >= T_PAGE_ERASE:
        erase(a, PAGE)                      # one whole erase cycle: the page is erased
        bus.WriteDoubleWord(slot, 0)
        return total
    raw = bus.ReadBytes(a, PAGE)
    out = []
    for off in range(PAGE):
        b = int(raw[off])
        if b != 0xFF:
            for bit in range(8):
                if not (b >> bit) & 1 and partial_needs(8 * off + bit) <= total:
                    b |= 1 << bit
        out.append(b)
    data = Array[Byte](out)
    bus.WriteBytes(data, a)
    bus.WriteBytes(data, shadow_of(a))
    bus.WriteDoubleWord(slot, total)
    return total


def erase(addr, size):
    # an erase: in flash, in the shadow, and the write counts of its words
    ff = Array[Byte]([0xFF] * size)
    bus.WriteBytes(ff, addr)
    bus.WriteBytes(ff, shadow_of(addr))
    bus.WriteBytes(Array[Byte]([0] * (size // 4)), count_of(addr))
    if not in_uicr(addr):
        bus.WriteBytes(Array[Byte]([0] * (4 * (size // PAGE))), PARTIAL + 4 * ((addr - FLASH_BASE) // PAGE))


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
    now = bus.ReadBytes(OB_BASE, OB_SIZE)
    was = bus.ReadBytes(SHADOW + FLASH_SIZE, OB_SIZE)
    for i in range(OB_SIZE):
        if now[i] != was[i]:
            out.append(OB_BASE + i)
    return out


def listen(on):
    # Hear every memory access of the CPU, or stop hearing them. Ending the current
    # block of translated code makes the very next instruction count already.
    for c in bus.GetCPUs():
        c.SetHookAtMemoryAccess(on_access if on else None)
        if on:
            c.RequestTranslationBlockRestart()
    wake_clock()


def update_listening():
    # stores are programs while WEN is Wen; reads are watched while an ACL region
    # blocks them
    listen(config == WEN_WEN or any(r[2] & PERM_READ for r in acl))


def on_access(pc, operation, virtual, addr, width, value):
    # called by the CPU after each of its memory accesses while listening
    addr = int(addr)
    op = str(operation)
    if op == "MemoryRead":
        if acl_blocks(addr, PERM_READ):
            if not st(READS):
                st_w(READS_AT, addr)
            st_w(READS, st(READS) + 1)
        return
    if op != "MemoryWrite" or config != WEN_WEN:
        return
    if FLASH_BASE <= addr < FLASH_BASE + FLASH_SIZE or in_uicr(addr):
        program(addr, int(width), int(value))


PERM_WRITE, PERM_READ = 2, 4


def acl_blocks(addr, what):
    # does an ACL region forbid this kind of access at addr? A region counts once its
    # address is on a page boundary and its size a whole number of pages
    for start, size, perm in acl:
        if perm & what and size and not start % PAGE and not size % PAGE and start <= addr < start + size:
            return True
    return False


def refuse_protected(addr):
    if not st(PROTECTED):
        st_w(PROTECTED_AT, addr)
    st_w(PROTECTED, st(PROTECTED) + 1)
    log("W 0x%08X" % addr)


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
    if acl_blocks(a, PERM_WRITE):
        put(a, width, old)                      # a bus fault on the chip: nothing is written
        refuse_protected(a)
        return
    writes = int(bus.ReadByte(count_of(a)))
    if writes >= N_WRITE:
        refuse(a, width, value, old)            # nWRITE: no more without an erase
        return
    stored = old & value                        # a program clears bits, it cannot set them
    if worn(a):
        stored = (stored & ~1) | (old & 1)
    put(a, 4, stored)
    put(shadow_of(a), 4, stored)
    bus.WriteByte(count_of(a), writes + 1)
    log("P 0x%08X 0x%08X @%d" % (a, stored, T_WRITE_US[TIMING]))


def worn(a):
    # a worn page (flash.worn in the adapter): programs there report success, but bit 0 of
    # each cell no longer changes, so the data read back differs from what was written
    return WORN_FROM <= a < WORN_TO


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
    partial_ms = 10                             # ERASEPAGEPARTIALCFG after reset
    acl = [[0, 0, 0] for _ in range(8)]         # ADDR, SIZE, PERM: cleared by a reset
elif request.IsWrite or request.IsRead:
    ensure_state()
    o = request.Offset

    if request.IsRead:
        if o == 0x400 or o == 0x408: request.Value = 1     # READY, READYNEXT: always ready
        elif o == 0x504: request.Value = config
        elif o == 0x51C: request.Value = partial_ms
        elif 0x800 <= o < 0x880 and o % 16 < 12: request.Value = acl[(o - 0x800) // 16][(o % 16) // 4]
        elif 0x100 <= o <= 0x154: request.Value = st((o - 0x100) // 4 + 1)
        else: request.Value = 0
    else:
        v = request.Value
        if o == 0x504:
            listening = config == WEN_WEN
            config = v & 7
            if (config == WEN_WEN) != listening:
                update_listening()              # stores into flash are programs while Wen
        elif o == 0x508 or o == 0x510 or o == 0x518:   # ERASEPAGE (ERASEPCR1, ERASEPCR0), PARTIAL
            a = FLASH_BASE + ((v - FLASH_BASE) // PAGE) * PAGE
            if config == WEN_EEN and FLASH_BASE <= a < FLASH_BASE + FLASH_SIZE:
                if begin(True, a):
                    if acl_blocks(a, PERM_WRITE):
                        refuse_protected(a)
                    elif o == 0x518:
                        us = 1000 * partial_ms
                        total = partial_erase(a, us)
                        log("Q 0x%08X %d @%d" % (a, total, spend(us if TIMING else 0)))
                    else:
                        erase(a, PAGE)
                        log("E 0x%08X @%d" % (a, spend(T_ERASE_US[TIMING])))
        elif o == 0x51C:
            partial_ms = v & 0x7F
        elif o == 0x50C:                       # ERASEALL: the code area and the UICR
            if config == WEN_EEN and v & 1:
                if begin(True, FLASH_BASE):
                    if any(r[2] & PERM_WRITE for r in acl):
                        refuse_protected(FLASH_BASE)
                    else:
                        erase(FLASH_BASE, FLASH_SIZE)
                        erase(OB_BASE, OB_SIZE)
                        log("M 0x%08X @%d" % (FLASH_BASE, spend(T_ERASEALL_US[TIMING])))
        elif o == 0x514:                       # ERASEUICR
            if config == WEN_EEN and v & 1:
                if begin(True, OB_BASE):
                    erase(OB_BASE, OB_SIZE)
                    log("E 0x%08X @%d" % (OB_BASE, spend(T_ERASE_US[TIMING])))
        elif 0x800 <= o < 0x880 and o % 16 < 12:
            # ACL: each register takes one write until reset. The region is enforced once
            # its address is on a page boundary and its size and permissions are not zero.
            r = acl[(o - 0x800) // 16]
            i = (o % 16) // 4
            if r[i] == 0:
                r[i] = v & (6 if i == 2 else 0xFFFFFFFF)
                update_listening()
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
        elif 0x100 <= o <= 0x154:
            st_w((o - 0x100) // 4 + 1, v)
