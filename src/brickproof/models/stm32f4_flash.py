# STM32F4 flash controller for the emulator: lock/unlock, sector and mass erase,
# option bytes through OPTCR, always ready. It does the same jobs for BrickProof as
# the F1 model next to it (count operations, stop the CPU at a chosen one, enforce
# what the chip enforces, notice stray writes, log the trace), for a chip that
# differs from the F1 in every one of them:
#
#   an erase wipes a sector, and sectors are not all the same size (SECTORS below);
#   a program writes a byte, a halfword, a word or a double word, as PSIZE says;
#   a program can only clear bits. Writing over a cell that is not erased is not
#     refused as on the F1: the cell ends up as old AND new, with no error flag;
#   write protection is one bit per sector;
#   the option bytes are not written by the firmware. It puts the wanted values in
#     OPTCR and sets OPTSTRT, and the chip erases and rewrites them itself.
#
# An operation starts when software sets STRT (erase), sets PG (program) or sets
# OPTSTRT. The programmed cell is written by the CPU straight into flash memory, so
# the model never sees it happen. It keeps a shadow copy of flash that only real
# operations update, and when PG is cleared it compares the two to find what was written.
#
# Option bytes are 16 bytes at OB_BASE, as the chip shows them: a word at +0 holding
# USER and RDP in its low half and their complement in its high half, and a word at +8
# holding the nWRP bits the same way. They are loaded into OPTCR at reset, so a change
# only takes effect after the next reset. One OPTSTRT is several operations here,
# because a power cut can fall between them: the erase of the option bytes, then one
# program for each of the two words. An erased RDP byte reads as "level 1" at the next
# reset, and going from level 1 back to level 0 makes the chip mass-erase the main
# flash first. That mass erase is an operation too.
#
# Operations take the time they take on the chip (TIMING below). The CPU runs from
# flash, and flash cannot be read while it is being erased or programmed, so the chip
# simply stops for that long. The model skips the same amount of virtual time: timers,
# watchdogs and timeouts see a one-second sector erase as one second.
#
# Not modelled: PGPERR and PGAERR (the model cannot see how wide a store was), PCROP
# (SPRMOD is kept but the nWRP bits always mean write protection), and RDP level 2.
#
# The test-only registers at 0x100..0x14C are the same as the F1 model's, see there.
# "cut page" (0x114) takes the first address of a sector.
#
# Renode gives Python peripherals no parameters, so the engine rewrites the
# constant lines below with the target's values when it copies this file.
SECTORS = [(0x0, 0x4000), (0x4000, 0x4000), (0x8000, 0x4000), (0xC000, 0x4000), (0x10000, 0x10000), (0x20000, 0x20000), (0x40000, 0x20000), (0x60000, 0x20000)]
FLASH_BASE = 0x08000000
FLASH_SIZE = 0x80000
STATE = 0x90000000
SHADOW = 0x91000000
EXPECT = 0x92000000
TRACE_FILE = ""
OB_BASE = 0x1FFFC000
OB_SIZE = 16
CHUNK = 0x400               # flash is compared with its shadow in pieces of this size
# How long operations take: 0 = no time at all, 1 = typical, 2 = the slowest the datasheet
# allows. From the flash memory programming table of the STM32F411xC/xE datasheet, in
# microseconds. An erase depends on the size of the sector and on PSIZE (8, 16, 32 bits;
# 64 needs an external supply and is given the 32-bit figures). Programming a cell takes
# 16 us, at most 100.
TIMING = 0
T_PROGRAM_US = (0, 16, 100)
T_ERASE_US = {
    0x4000: ((0, 0, 0, 0), (400000, 300000, 250000, 250000), (800000, 600000, 500000, 500000)),
    0x10000: ((0, 0, 0, 0), (1200000, 700000, 550000, 550000), (2400000, 1400000, 1100000, 1100000)),
    0x20000: ((0, 0, 0, 0), (2000000, 1300000, 1000000, 1000000), (4000000, 2600000, 2000000, 2000000)),
}
T_MASS_US = ((0, 0, 0, 0), (8000000, 5500000, 4000000, 4000000), (16000000, 11000000, 8000000, 8000000))
# rewriting the option bytes: no figure in the datasheet, taken as one small-sector erase
T_OPTION_US = (0, 250000, 500000)
NEVER = 0xFFFFFFFF
MAGIC = 0xB81C0004          # state word 0: set once the defaults below are in place
SR_WRPERR = 0x10
CR_PG, CR_SER, CR_MER, CR_STRT, CR_LOCK = 1, 2, 4, 1 << 16, 1 << 31
OPTCR_OPTLOCK, OPTCR_OPTSTRT = 1, 2
RDP_LEVEL_0 = 0xAA

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


def erase_time(size, psize):
    # a sector of a size the table does not have takes as long as its share of 128 KB
    if size in T_ERASE_US:
        return T_ERASE_US[size][TIMING][psize]
    return T_ERASE_US[0x20000][TIMING][psize] * size // 0x20000


def resync():
    bus.WriteBytes(bus.ReadBytes(FLASH_BASE, FLASH_SIZE), SHADOW)
    bus.WriteBytes(bus.ReadBytes(OB_BASE, OB_SIZE), SHADOW + FLASH_SIZE)


def shadow_of(addr):
    # where the shadow keeps this address: flash first, the option bytes after it
    if addr >= OB_BASE:
        return SHADOW + FLASH_SIZE + (addr - OB_BASE)
    return SHADOW + (addr - FLASH_BASE)


def fill_ff(addr, size):
    # an erase: in flash, and in the shadow, because it is a real operation
    ff = Array[Byte]([0xFF] * size)
    bus.WriteBytes(ff, addr)
    bus.WriteBytes(ff, shadow_of(addr))


def get(addr, size):
    # `size` bytes as a number, least significant byte first
    raw = bus.ReadBytes(addr, size)
    v = 0
    for i in range(size):
        v |= int(raw[i]) << (8 * i)
    return v


def put(addr, size, v):
    bus.WriteBytes(Array[Byte]([(v >> (8 * i)) & 0xFF for i in range(size)]), addr)


def sector_of(addr):
    # index of the sector holding a flash address
    off = addr - FLASH_BASE
    for i, (start, size) in enumerate(SECTORS):
        if start <= off < start + size:
            return i
    return -1


def load_option_bytes():
    # what the chip does at reset: OPTCR is loaded from the option bytes
    user_rdp = get(OB_BASE, 2)
    wrp = get(OB_BASE + 8, 2)
    value = (user_rdp & 0xFFEC) | ((wrp & 0x0FFF) << 16) | OPTCR_OPTLOCK
    if not wrp & 0x8000:
        value |= 1 << 31                # SPRMOD is stored inverted
    return value


def is_protected(addr):
    # one nWRP bit per sector, and a cleared bit protects it
    return not (nwrp >> sector_of(addr)) & 1


def refuse_protected(addr):
    global sr_err
    sr_err |= SR_WRPERR
    if not st(PROTECTED):
        st_w(PROTECTED_AT, addr)
    st_w(PROTECTED, st(PROTECTED) + 1)
    log("W 0x%08X" % addr)


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
    return out + option_differences()


def option_differences():
    now = bus.ReadBytes(OB_BASE, OB_SIZE)
    was = bus.ReadBytes(SHADOW + FLASH_SIZE, OB_SIZE)
    return [OB_BASE + i for i in range(OB_SIZE) if now[i] != was[i]]


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


def in_flash(addr):
    return FLASH_BASE <= addr < FLASH_BASE + FLASH_SIZE


def written_cells(size):
    # Which cells did the program that just ended write? A cell is `size` bytes at a
    # multiple of `size`. A copy goes on from where the last one stopped, so look
    # there first. If nothing is there, look everywhere, and take the first cell that
    # differs plus any that directly follow it (firmware may leave PG set for a few
    # cells). A difference somewhere else was not made by this program: leave it for
    # the audit to report.
    found = []
    last = st(LAST)
    a = last + size if last else 0
    if a % size:
        a = 0                           # the cell size changed since the last program
    while a and in_flash(a) and get(a, size) != get(shadow_of(a), size):
        found.append(a)
        a += size
    if not found:
        cells = []
        for d in all_differences():
            c = d - d % size
            if d < OB_BASE and (not cells or cells[-1] != c):
                cells.append(c)
        for c in cells:
            if not found or c == found[-1] + size:
                found.append(c)
        stray = [c for c in cells if c not in found] + option_differences()
        if stray and not st(AUDIT):
            st_w(AUDIT, stray[0])
    return found


def settle_program(size):
    # PG was just cleared: account for what the program wrote, the way the chip would
    st_w(PENDING, 0)
    found = written_cells(size)
    if not found:
        # flash is as it was: the program wrote the value already there. In a
        # sequential copy that is the next cell, so say so, as a guess.
        last = st(LAST)
        if last:
            st_w(LAST, last + size)
        log("P? 0x%08X @%d" % (last + size if last else 0, T_PROGRAM_US[TIMING]))
    for n, a in enumerate(found):
        if n:
            st_w(OPCOUNT, st(OPCOUNT) + 1)      # PG stayed set: each further cell is an operation
        new = get(a, size)
        old = get(shadow_of(a), size)
        if is_protected(a):
            put(a, size, old)                   # write-protected: nothing is written
            refuse_protected(a)
        else:
            stored = old & new                  # a program clears bits, it cannot set them
            put(a, size, stored)
            put(shadow_of(a), size, stored)
            log("P 0x%08X 0x%0*X @%d" % (a, 2 * size, stored, T_PROGRAM_US[TIMING]))
        if n:
            spend(T_PROGRAM_US[TIMING])         # the first one was paid for when PG was set
        st_w(LAST, a)


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


def with_complement(half):
    return (half & 0xFFFF) | ((~half & 0xFFFF) << 16)


def program_option_bytes(value):
    # OPTSTRT: the chip rewrites its option bytes from OPTCR. If that takes read
    # protection away, it erases the whole main flash before anything else.
    user_rdp = (value & 0xFFEC) | 0x0003
    wrp = ((value >> 16) & 0x0FFF) | 0x7000 | (0 if value >> 31 else 0x8000)
    if rdp != RDP_LEVEL_0 and (user_rdp >> 8) == RDP_LEVEL_0:
        if not begin(True, FLASH_BASE):
            return
        fill_ff(FLASH_BASE, FLASH_SIZE)
        log("M 0x%08X @%d" % (FLASH_BASE, spend(T_MASS_US[TIMING][(cr >> 8) & 3])))
    if not begin(True, OB_BASE):
        return
    fill_ff(OB_BASE, OB_SIZE)
    log("E 0x%08X @%d" % (OB_BASE, spend(T_OPTION_US[TIMING])))
    for a, half in ((OB_BASE, user_rdp), (OB_BASE + 8, wrp)):
        if not begin(False, a):
            return
        put(a, 4, with_complement(half))
        put(shadow_of(a), 4, with_complement(half))
        log("P 0x%08X 0x%08X @%d" % (a, with_complement(half), spend(T_PROGRAM_US[TIMING])))


if request.IsInit:
    cr = CR_LOCK
    acr = 0
    keystate = 0
    optkeystate = 0
    sr_err = 0
    optcr = None            # loaded from the option bytes on first use after this reset
    nwrp = 0xFFF
    rdp = RDP_LEVEL_0
elif request.IsWrite or request.IsRead:
    ensure_state()
    if optcr is None:
        optcr = load_option_bytes()
        nwrp = (optcr >> 16) & 0xFFF    # what is in force until the next reset
        rdp = (optcr >> 8) & 0xFF
    o = request.Offset

    if request.IsRead:
        if o == 0x00: request.Value = acr
        elif o == 0x0C: request.Value = sr_err        # BSY never set: operations are instant
        elif o == 0x10: request.Value = cr
        elif o == 0x14: request.Value = optcr
        elif 0x100 <= o <= 0x14C: request.Value = st((o - 0x100) // 4 + 1)
        else: request.Value = 0
    else:
        v = request.Value
        if o == 0x00:
            acr = v
        elif o == 0x04:
            if keystate == 0 and v == 0x45670123: keystate = 1
            elif keystate == 1 and v == 0xCDEF89AB:
                keystate = 2; cr &= ~CR_LOCK
            else: keystate = 0
        elif o == 0x08:
            if optkeystate == 0 and v == 0x08192A3B: optkeystate = 1
            elif optkeystate == 1 and v == 0x4C5D6E7F:
                optkeystate = 2; optcr &= ~OPTCR_OPTLOCK
            else: optkeystate = 0
        elif o == 0x10:
            old = cr
            locked = old & CR_LOCK
            if v & CR_LOCK:                 # LOCK is write-1-to-set and restarts the key sequence
                locked = CR_LOCK
                keystate = 0
            if old & CR_LOCK:
                v = old                     # a locked CR ignores everything but the keys
            cr = (v & ~(CR_LOCK | CR_STRT)) | locked      # STRT clears itself
            unlocked = not (old & CR_LOCK)
            if st(PENDING) and not (v & CR_PG):
                settle_program(1 << ((old >> 8) & 3))
            if unlocked and (v & CR_STRT) and (v & CR_SER):
                sector = (v >> 3) & 0xF
                if sector < len(SECTORS):
                    a = FLASH_BASE + SECTORS[sector][0]
                    if begin(True, a):
                        if is_protected(a):
                            refuse_protected(a)
                        else:
                            fill_ff(a, SECTORS[sector][1])
                            log("E 0x%08X @%d" % (a, spend(erase_time(SECTORS[sector][1], (v >> 8) & 3))))
            elif unlocked and (v & CR_STRT) and (v & CR_MER):
                if begin(True, FLASH_BASE):
                    if [s for s in range(len(SECTORS)) if not (nwrp >> s) & 1]:
                        refuse_protected(FLASH_BASE)    # not done if any sector is protected
                    else:
                        fill_ff(FLASH_BASE, FLASH_SIZE)
                        log("M 0x%08X @%d" % (FLASH_BASE, spend(T_MASS_US[TIMING][(v >> 8) & 3])))
            elif unlocked and (v & CR_PG) and not (old & CR_PG):
                if begin(False, 0):
                    st_w(PENDING, 1)
                    spend(T_PROGRAM_US[TIMING])
        elif o == 0x14:
            if not optcr & OPTCR_OPTLOCK:
                optcr = v & ~OPTCR_OPTSTRT            # OPTSTRT clears itself
                if v & OPTCR_OPTLOCK:
                    optkeystate = 0
                elif v & OPTCR_OPTSTRT:
                    program_option_bytes(v)
        elif o == 0x0C:
            sr_err &= ~v                     # error flags are write-1-to-clear
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
