# STM32L4 flash controller for the emulator (RM0351, the STM32L476 and its family; the G0,
# G4, WB and WL have the same one). It does what the F1 and F4 models next to it do for
# BrickProof (count operations, stop the CPU at a chosen one, enforce what the chip
# enforces, notice stray writes, log the trace), for a chip with a rule neither has:
#
#   every 64 bits of flash (a double word) carry 8 bits of ECC, written with them. A
#   program writes a whole double word as two 32-bit stores, the first at an 8-byte
#   boundary and the second right after it; the program starts on the second. Anything
#   else is refused: a store that is not 32 bits wide (SIZERR), a first word off the
#   boundary or a second word somewhere else (PGAERR), a double word that is not erased
#   unless the new value is all zeros (PROGERR), or any program while an error flag from
#   an earlier one is still set (PGSERR);
#   an erase wipes a 2 KB page (PER, PNB, and BKER for the second bank), or a whole bank
#   (MER1, MER2);
#   a double word whose data and ECC do not agree is an ECC error: a read of it sets ECCD
#   in ECCR, with the address, and raises an NMI. Only a program or an erase cut short can
#   leave one, so only torn states have them. Which double words are broken is kept in a
#   map, one byte per double word (ECC_MAP), part of the flash image. Correctable single
#   bit errors (ECCC) are not modelled: a broken double word is always ECCD;
#   write protection is two areas of bank 1 (WRP1AR, WRP1BR: first and last page) from the
#   option bytes, loaded at reset. Bank 2's areas (option bytes at 0x1FFFF800) and PCROP
#   are not modelled.
#
# A program is an operation when the second word of a double word is stored while PG is
# set; the model listens to the CPU's memory accesses while PG is set, and while the map
# has a broken double word (to see the reads that hit one). An erase is an operation when
# software sets STRT, a rewrite of the option bytes (OPTSTRT) is the erase of the option
# bytes and a program of each of their double words. Taking read protection from level 1
# back to 0 mass-erases both banks first, and level 2 (0xCC) is for good.
#
# Option bytes are 40 bytes at OB_BASE, five double words of value and complement: OPTR,
# PCROP1SR, PCROP1ER, WRP1AR, WRP1BR. A value that does not match its complement loads as
# all ones and sets OPTVERR, as on the F1. OPTR's IWDG_SW (bit 16) cleared makes the
# watchdog a hardware one, started at every reset.
#
# Times (TIMING) are from the STM32L4 datasheets' flash table (the L412 and L475 give the
# same figures): 81.69 us per double word, at most 90.76; 22.02 ms per page, at most 24.47;
# a bank 22.13 ms, at most 24.59.
#
# The test-only registers at 0x100..0x154 are the F1 model's; 0x158 and 0x15C count ECC
# errors seen by reads and hold the first one's address. "cut page" (0x114) takes the first
# address of a page.
#
# Renode gives Python peripherals no parameters, so the engine rewrites the constant lines
# below with the target's values when it copies this file.
PAGE = 0x800
FLASH_BASE = 0x08000000
FLASH_SIZE = 0x100000
STATE = 0x90000000
SHADOW = 0x91000000
EXPECT = 0x92000000
ECC_MAP = 0x94000000        # one byte per double word: 1 when its ECC does not match
TRACE_FILE = ""
OB_BASE = 0x1FFF7800
OB_SIZE = 0x28
CHUNK = 0x400
TIMING = 0
WORN_FROM = 0x0           # worn pages (flash.worn): [WORN_FROM, WORN_TO), none by default
WORN_TO = 0x0
T_PROGRAM_US = (0, 82, 91)
T_ERASE_US = (0, 22020, 24470)
T_MASS_US = (0, 22130, 24590)
IWDG_KR = 0x40003000
ICSR = 0xE000ED04           # writing NMIPENDSET (bit 31) here raises the NMI
NEVER = 0xFFFFFFFF
MAGIC = 0xB81C0014          # state word 0: set once the defaults below are in place
SR_EOP, SR_OPERR, SR_PROGERR, SR_WRPERR = 1, 2, 8, 0x10
SR_PGAERR, SR_SIZERR, SR_PGSERR, SR_MISERR, SR_FASTERR = 0x20, 0x40, 0x80, 0x100, 0x200
SR_RDERR, SR_OPTVERR = 0x4000, 0x8000
SR_PROGRAM_ERRORS = SR_PROGERR | SR_WRPERR | SR_PGAERR | SR_SIZERR | SR_PGSERR | SR_MISERR | SR_FASTERR
CR_PG, CR_PER, CR_MER1, CR_BKER, CR_MER2 = 1, 2, 4, 1 << 11, 1 << 15
CR_STRT, CR_OPTSTRT, CR_OBL_LAUNCH, CR_OPTLOCK, CR_LOCK = 1 << 16, 1 << 17, 1 << 27, 1 << 30, 1 << 31
ECCR_ECCD = 1 << 31
RDP_LEVEL_0 = 0xAA
RDP_LEVEL_2 = 0xCC
# the factory values of the option bytes' five words
OB_DEFAULTS = (0xFFEFF8AA, 0xFFFFFFFF, 0x00000000, 0xFF00FFFF, 0xFF00FFFF)

from System import Array, Byte, Convert
from Antmicro.Renode.Time import TimeInterval

(OPCOUNT, CUTPOINT, CUT_HIT, CUT_KIND, CUT_ADDR, CUT_PAGE, FAULT_ADDR, FAULT_PC,
 TRACE, PENDING, AUDIT, REFUSED, REFUSED_AT, LAST, _RESYNC, COMPARE, CMP_FROM, CMP_LEN,
 PROTECTED, PROTECTED_AT, _READS, _READS_AT, ECC_READS, ECC_AT, ECC_BROKEN, ECCR) = range(1, 27)

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


def ecc_reader(b, state=STATE, ecc_map=ECC_MAP, base=FLASH_BASE, size=FLASH_SIZE, icsr=ICSR):
    # A function that sees a CPU read of flash: if its double word is broken, the chip sets
    # ECCD in ECCR (kept in the state memory) with the address and raises an NMI. It carries
    # its own bus and constants because it outlives this script (see after_reset).
    def seen(a):
        if a < size:
            a += base                               # through the boot alias at address 0
        if not base <= a < base + size:
            return
        off = a - base
        if not int(b.ReadByte(ecc_map + off // 8)):
            return
        reads = int(b.ReadDoubleWord(state + 4 * ECC_READS))
        if not reads:
            b.WriteDoubleWord(state + 4 * ECC_AT, a)
        b.WriteDoubleWord(state + 4 * ECC_READS, reads + 1)
        bank = off // (size // 2)
        b.WriteDoubleWord(state + 4 * ECCR, ECCR_ECCD | (bank << 19) | (off % (size // 2)))
        b.WriteDoubleWord(icsr, 0x80000000)        # NMIPENDSET
    return seen


def after_reset(machine):
    # Runs after every reset, for as long as this emulator lives. A reset ends any program
    # that was going on; reads of broken double words are still watched; with IWDG_SW
    # cleared the watchdog starts by itself.
    b = machine.SystemBus
    b.WriteDoubleWord(STATE + 4 * ECCR, 0)          # ECCR is cleared by a reset
    seen = ecc_reader(b)

    def watch(pc, operation, virtual, addr, width, value):
        if str(operation) == "MemoryRead":
            seen(int(addr))

    broken = int(b.ReadDoubleWord(STATE + 4 * ECC_BROKEN))
    for c in b.GetCPUs():
        c.SetHookAtMemoryAccess(watch if broken else None)
    optr = int(b.ReadDoubleWord(OB_BASE))
    if optr ^ 0xFFFFFFFF == int(b.ReadDoubleWord(OB_BASE + 4)) and not (optr >> 16) & 1:
        b.WriteDoubleWord(IWDG_KR, 0xCCCC)



def log(text):
    if st(TRACE) == 1:
        f = open(TRACE_FILE, "a")
        f.write(text + chr(10))
        f.close()


def spend(us):
    # the chip is busy for this long and the CPU, which runs from flash, waits
    if us:
        for c in bus.GetCPUs():
            c.SkipTime(TimeInterval.FromMicroseconds(us))
    return us


def resync():
    # flash is now what it should be (the engine restored it, with its ECC map)
    bus.WriteBytes(bus.ReadBytes(FLASH_BASE, FLASH_SIZE), SHADOW)
    bus.WriteBytes(bus.ReadBytes(OB_BASE, OB_SIZE), SHADOW + FLASH_SIZE)
    m = bus.ReadBytes(ECC_MAP, FLASH_SIZE // 8)
    if Convert.ToBase64String(m).strip("A=") == "":
        st_w(ECC_BROKEN, 0)                     # all sound: the usual case, and quick
    else:
        st_w(ECC_BROKEN, len([1 for i in range(FLASH_SIZE // 8) if m[i]]))


def shadow_of(addr):
    if addr >= OB_BASE:
        return SHADOW + FLASH_SIZE + (addr - OB_BASE)
    return SHADOW + (addr - FLASH_BASE)


def set_ecc(addr, size, broken):
    # mark the double words of [addr, addr + size) as broken or sound
    first = (addr - FLASH_BASE) // 8
    n = (size + 7) // 8
    now = bus.ReadBytes(ECC_MAP + first, n)
    was = len([1 for i in range(n) if now[i]])
    bus.WriteBytes(Array[Byte]([1 if broken else 0] * n), ECC_MAP + first)
    st_w(ECC_BROKEN, st(ECC_BROKEN) - was + (n if broken else 0))


def fill_ff(addr, size):
    # an erase: in flash, in the shadow, and the ECC of every double word is sound again
    ff = Array[Byte]([0xFF] * size)
    bus.WriteBytes(ff, addr)
    bus.WriteBytes(ff, shadow_of(addr))
    if addr < OB_BASE:
        set_ecc(addr, size, False)


def get(addr, size):
    raw = bus.ReadBytes(addr, size)
    v = 0
    for i in range(size):
        v |= int(raw[i]) << (8 * i)
    return v


def put(addr, size, v):
    bus.WriteBytes(Array[Byte]([(v >> (8 * i)) & 0xFF for i in range(size)]), addr)


def option_word(i):
    # option byte word i as loaded at reset: all ones if it does not match its complement
    global sr
    v, c = get(OB_BASE + 8 * i, 4), get(OB_BASE + 8 * i + 4, 4)
    if v ^ 0xFFFFFFFF != c:
        sr |= SR_OPTVERR
        return 0xFFFFFFFF
    return v


def load_option_bytes():
    # at reset: the option registers take the option bytes' values, and so does what is in
    # force (write protection) until the next load
    global wrp1ar, wrp1br, ob_regs
    ob_regs = [option_word(i) for i in range(5)]
    wrp1ar, wrp1br = ob_regs[3], ob_regs[4]


def is_protected(addr):
    # bank 1's two write-protected areas, first and last page included
    off = addr - FLASH_BASE
    if off >= FLASH_SIZE // 2:
        return False
    page = off // PAGE
    for r in (wrp1ar, wrp1br):
        start, end = r & 0xFF, (r >> 16) & 0xFF
        if start <= page <= end:
            return True
    return False


def refuse_protected(addr):
    global sr
    sr |= SR_WRPERR
    if not st(PROTECTED):
        st_w(PROTECTED_AT, addr)
    st_w(PROTECTED, st(PROTECTED) + 1)
    log("W 0x%08X" % addr)


def refuse(addr, value, old, flag, size=8):
    # a program the chip does not make: the flag is set and nothing changes
    global sr
    sr |= flag
    if not st(REFUSED):
        st_w(REFUSED_AT, addr)
    st_w(REFUSED, st(REFUSED) + 1)
    log("X 0x%08X 0x%0*X 0x%0*X" % (addr, 2 * size, value, 2 * size, old))


def all_differences():
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
    return out + [OB_BASE + i for i in range(OB_SIZE) if now[i] != was[i]]


def first_difference(addr, n):
    now = bus.ReadBytes(addr, n)
    want = bus.ReadBytes(addr - FLASH_BASE + EXPECT, n)
    if Convert.ToBase64String(now) == Convert.ToBase64String(want):
        return 0
    for i in range(n):
        if now[i] != want[i]:
            return addr + i
    return 0


def listen():
    # Hear the CPU's memory accesses while PG is set (its stores into flash are programs)
    # or while a double word is broken (its reads of one are ECC errors). Listening is
    # slow, so it is off otherwise.
    global reader
    on = programming or st(ECC_BROKEN) > 0
    reader = ecc_reader(bus)
    for c in bus.GetCPUs():
        c.SetHookAtMemoryAccess(on_access if on else None)
        if on:
            c.RequestTranslationBlockRestart()


def on_access(pc, operation, virtual, addr, width, value):
    op = str(operation)
    addr = int(addr)
    if op == "MemoryRead":
        if st(ECC_BROKEN):
            reader(addr)
        return
    if op != "MemoryWrite" or not programming:
        return
    if addr < FLASH_SIZE:
        addr += FLASH_BASE
    if FLASH_BASE <= addr < FLASH_BASE + FLASH_SIZE:
        store(addr, int(width), int(value))


def store(a, width, value):
    # One store into flash while PG is set. It has already landed in Renode's memory; the
    # shadow says what was there. Nothing is written until the second word arrives.
    global pending
    old = get(shadow_of(a), width)
    put(a, width, old)
    if st(CUT_HIT):
        return                                  # the power is off
    if width != 4:
        pending = None
        return refuse(a, value, old, SR_SIZERR, width)
    if pending is None:
        if sr & SR_PROGRAM_ERRORS:
            return refuse(a, value, old, SR_PGSERR, 4)    # an earlier error not cleared
        if a % 8:
            return refuse(a, value, old, SR_PGAERR, 4)    # the first word off the boundary
        pending = (a, value)
        return
    first, low = pending
    pending = None
    if a != first + 4:
        return refuse(a, value, old, SR_PGAERR, 4)        # not the second word of that one
    program(first, low | (value << 32))


def program(a, value):
    # the double word at a: the operation itself
    if not begin(False, 0):
        for c in bus.GetCPUs():
            c.RequestTranslationBlockRestart()  # the power goes just before this program
        return
    spend(T_PROGRAM_US[TIMING])
    old = get(shadow_of(a), 8)
    if is_protected(a):
        return refuse_protected(a)
    if old != 0xFFFFFFFFFFFFFFFF and value != 0:
        return refuse(a, value, old, SR_PROGERR)          # not erased, and not all zeros
    stored = value
    if WORN_FROM <= a < WORN_TO:
        stored = (stored & ~1) | (old & 1)
    put(a, 8, stored)
    put(shadow_of(a), 8, stored)
    set_ecc(a, 8, False)
    log("P 0x%08X 0x%016X @%d" % (a, stored, T_PROGRAM_US[TIMING]))


def begin(erasing, addr):
    # One operation is about to start. Returns False if this is where the power goes.
    if st(CUT_HIT):
        return False
    opcount = st(OPCOUNT)
    if opcount == st(CUTPOINT) or (erasing and addr == st(CUT_PAGE)):
        st_w(CUT_HIT, 1)
        st_w(CUT_KIND, 1 if erasing else 2)
        st_w(CUT_ADDR, addr if erasing else 0)
        for c in bus.GetCPUs():
            c.IsHalted = True
        return False
    st_w(OPCOUNT, opcount + 1)
    return True


def erase_page(v):
    bank = 1 if v & CR_BKER else 0
    page = (v >> 3) & 0xFF
    a = FLASH_BASE + bank * (FLASH_SIZE // 2) + page * PAGE
    if a >= FLASH_BASE + FLASH_SIZE or not begin(True, a):
        return
    if is_protected(a):
        return refuse_protected(a)
    fill_ff(a, PAGE)
    log("E 0x%08X @%d" % (a, spend(T_ERASE_US[TIMING])))


def erase_banks(v):
    half = FLASH_SIZE // 2
    banks = [b for b, bit in ((0, CR_MER1), (1, CR_MER2)) if v & bit]
    for b in banks:
        a = FLASH_BASE + b * half
        if not begin(True, a):
            return
        if b == 0 and [p for p in range(half // PAGE) if is_protected(FLASH_BASE + p * PAGE)]:
            refuse_protected(a)                 # not done if any page in it is protected
            continue
        fill_ff(a, half)
        log("E 0x%08X #0x%X @%d" % (a, half, spend(T_MASS_US[TIMING])))


def program_option_bytes():
    # OPTSTRT: the chip writes the option registers to the option bytes. Taking read
    # protection away (level 1 to 0) mass-erases both banks first.
    stored_rdp = option_word(0) & 0xFF
    if stored_rdp == RDP_LEVEL_2:
        log("X 0x%08X level 2: the option bytes cannot change" % OB_BASE)
        return
    words = list(ob_regs)
    if stored_rdp != RDP_LEVEL_0 and (words[0] & 0xFF) == RDP_LEVEL_0:
        if not begin(True, FLASH_BASE):
            return
        fill_ff(FLASH_BASE, FLASH_SIZE)
        log("M 0x%08X @%d" % (FLASH_BASE, spend(2 * T_MASS_US[TIMING])))
    if not begin(True, OB_BASE):
        return
    fill_ff(OB_BASE, OB_SIZE)
    log("E 0x%08X @%d" % (OB_BASE, spend(T_ERASE_US[TIMING])))
    for i, w in enumerate(words):
        a = OB_BASE + 8 * i
        if not begin(False, a):
            return
        both = (w & 0xFFFFFFFF) | ((w ^ 0xFFFFFFFF) << 32)
        put(a, 8, both)
        put(shadow_of(a), 8, both)
        log("P 0x%08X 0x%016X @%d" % (a, both, spend(T_PROGRAM_US[TIMING])))


if request.IsInit:
    cr = CR_LOCK | CR_OPTLOCK
    acr = 0x600
    sr = 0
    keystate = 0
    optkeystate = 0
    programming = False
    pending = None          # the first word of a double word, waiting for the second
    ob_regs = None          # OPTR, PCROP1SR, PCROP1ER, WRP1AR, WRP1BR: loaded on first use
    reader = None
elif request.IsWrite or request.IsRead:
    ensure_state()
    if ob_regs is None:
        load_option_bytes()
    o = request.Offset

    if request.IsRead:
        if o == 0x00: request.Value = acr
        elif o == 0x10: request.Value = sr      # BSY never set: operations are instant
        elif o == 0x14: request.Value = cr
        elif o == 0x18: request.Value = st(ECCR)
        elif 0x20 <= o <= 0x30 and o % 4 == 0: request.Value = ob_regs[(o - 0x20) // 4]
        elif o == 0x4C or o == 0x50: request.Value = 0xFF00FFFF     # bank 2: no areas
        elif o == 0x44: request.Value = 0xFFFFFFFF
        elif 0x100 <= o <= 0x164: request.Value = st((o - 0x100) // 4 + 1)   # with ECC_BROKEN, ECCR
        else: request.Value = 0
    else:
        v = request.Value
        if o == 0x00:
            acr = v
        elif o == 0x08:
            if keystate == 0 and v == 0x45670123: keystate = 1
            elif keystate == 1 and v == 0xCDEF89AB:
                keystate = 2; cr &= ~CR_LOCK
            else: keystate = 0
        elif o == 0x0C:
            if optkeystate == 0 and v == 0x08192A3B: optkeystate = 1
            elif optkeystate == 1 and v == 0x4C5D6E7F:
                optkeystate = 2; cr &= ~CR_OPTLOCK
            else: optkeystate = 0
        elif o == 0x10:
            sr &= ~(v & 0xC3FB)                 # error flags and EOP are write-1-to-clear
        elif o == 0x14:
            old = cr
            if old & CR_LOCK:
                v = old | (v & (CR_LOCK | CR_OPTLOCK))  # locked: everything but the keys is ignored
            if v & CR_LOCK:
                keystate = 0                    # LOCK and OPTLOCK are set-only: the keys clear them
            locks = (old | v) & (CR_LOCK | CR_OPTLOCK)
            cr = (v & ~(CR_LOCK | CR_OPTLOCK | CR_STRT | CR_OPTSTRT | CR_OBL_LAUNCH)) | locks
            now = bool(cr & CR_PG) and not cr & CR_LOCK
            if now != programming:
                programming = now
                pending = None
                listen()
            if not old & CR_LOCK and v & CR_STRT:
                if v & CR_PER:
                    erase_page(v)
                elif v & (CR_MER1 | CR_MER2):
                    erase_banks(v)
                if st(ECC_BROKEN) == 0 and not programming:
                    listen()
            if not old & CR_LOCK and not old & CR_OPTLOCK and v & CR_OPTSTRT:
                program_option_bytes()
            if v & CR_OBL_LAUNCH and not old & CR_OPTLOCK:
                self.GetMachine().RequestReset()        # the option bytes load at reset
        elif o == 0x18:
            st_w(ECCR, st(ECCR) & ~(v & (ECCR_ECCD | (1 << 30))))     # ECCD, ECCC: write 1 to clear
        elif 0x20 <= o <= 0x30 and o % 4 == 0:
            if not cr & CR_OPTLOCK:
                ob_regs[(o - 0x20) // 4] = v    # written to the option bytes by OPTSTRT
        elif o == 0x104 or o == 0x114:
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
            listen()
        elif o == 0x13C:
            n = st(CMP_LEN)
            st_w(COMPARE, first_difference(st(CMP_FROM), n) if n else first_difference(FLASH_BASE, FLASH_SIZE))
        elif 0x100 <= o <= 0x15C:
            st_w((o - 0x100) // 4 + 1, v)
