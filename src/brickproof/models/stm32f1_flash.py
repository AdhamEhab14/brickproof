# STM32F1 flash controller (FPEC) for the emulator: lock/unlock, page and mass
# erase, always ready. On top of that it does four jobs for BrickProof:
#
#   counts every flash operation and can stop the CPU at a chosen one
#     (how the power-cut tests "pull the plug");
#   enforces the chip's programming rule, which Renode's plain memory does not:
#     a halfword that is not erased can only be programmed to 0x0000. Anything
#     else is refused: the old value stays and PGERR is set;
#   notices flash changing with no flash operation behind it (a store with PG
#     clear, or with the controller locked): silicon ignores those, Renode stores them;
#   can log each operation to a file (the golden-run trace).
#
# An operation starts when software sets STRT (erase) or sets PG (program). The
# halfword itself is written by the CPU straight into flash memory, so the model
# never sees it happen. It keeps a shadow copy of flash that only real operations
# update, and when PG is cleared it compares the two to find what was written.
#
# Test-only registers (not on the real chip). They and the shadow live in plain
# memory (bpState, bpShadow), not in this script's variables, because a firmware
# reset re-runs IsInit and would wipe them in the middle of an update:
#   0x100  opcount     operations started so far (read) / set (write)
#   0x104  cutpoint    stop when opcount reaches this value (0xFFFFFFFF = never)
#   0x108  cut info    read: 1 when the cut fired
#   0x10C  cut kind    read: 1 = erase, 2 = program, 0 = none
#   0x110  cut addr    read: page address of the erase that was cut (0 for a program)
#   0x114  cut page    stop when an erase of this page is about to start (0xFFFFFFFF = never)
#   0x118  fault addr  written by mem_guard.py: an address that does not exist on the chip
#   0x11C  fault pc    and where the CPU was when it touched it (both 0 = no fault)
#   0x120  trace       1 = append every operation to TRACE_FILE
#   0x124  pending     1 = a program has started and its halfword is not accounted for yet
#   0x128  audit       write 1: compare flash with the shadow. read: first address that
#                      differs, 0 if none. write 0: forget the last result
#   0x12C  refused     programs refused by the rule above (write 0 to clear)
#   0x130  refused at  address of the first one
#   0x134  last        address of the last program found (where a copy is likely to go on)
#   0x138  resync      write: make the shadow equal to flash (after the engine loads an image)
#   0x13C  compare     write: compare flash with the image the engine loaded into bpExpect.
#                      read: first address that differs, 0 if they are equal
#   0x140  from        the range to compare: first flash address,
#   0x144  length      and how many bytes (0 = the whole flash)
#
# Renode gives Python peripherals no parameters, so the engine rewrites the
# constant lines below with the target's values when it copies this file.
PAGE = 0x400
FLASH_BASE = 0x08000000
FLASH_SIZE = 0x20000
STATE = 0x90000000
SHADOW = 0x91000000
EXPECT = 0x92000000
TRACE_FILE = ""
NEVER = 0xFFFFFFFF
MAGIC = 0xB81C0002          # state word 0: set once the defaults below are in place
SR_PGERR = 0x04

from System import Array, Byte, Convert

(OPCOUNT, CUTPOINT, CUT_HIT, CUT_KIND, CUT_ADDR, CUT_PAGE, FAULT_ADDR, FAULT_PC,
 TRACE, PENDING, AUDIT, REFUSED, REFUSED_AT, LAST, _RESYNC, COMPARE, CMP_FROM, CMP_LEN) = range(1, 19)

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


def resync():
    bus.WriteBytes(bus.ReadBytes(FLASH_BASE, FLASH_SIZE), SHADOW)


def fill_ff(addr, size):
    # an erase: in flash, and in the shadow, because it is a real operation
    ff = Array[Byte]([0xFF] * size)
    bus.WriteBytes(ff, addr)
    bus.WriteBytes(ff, addr - FLASH_BASE + SHADOW)


def differs(addr):
    return int(bus.ReadWord(addr)) != int(bus.ReadWord(addr - FLASH_BASE + SHADOW))


def all_differences():
    # every halfword where flash is not what the shadow says. Pages are compared
    # as strings first (native code), so a clean flash costs about a millisecond.
    now = bus.ReadBytes(FLASH_BASE, FLASH_SIZE)
    was = bus.ReadBytes(SHADOW, FLASH_SIZE)
    out = []
    if Convert.ToBase64String(now) == Convert.ToBase64String(was):
        return out
    for p in range(0, FLASH_SIZE, PAGE):
        if Convert.ToBase64String(now, p, PAGE) != Convert.ToBase64String(was, p, PAGE):
            for i in range(p, p + PAGE, 2):
                if now[i] != was[i] or now[i + 1] != was[i + 1]:
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


def written_halfwords():
    # Which halfwords did the program that just ended write? A copy goes on from
    # where the last one stopped, so look there first. If nothing is there, look
    # everywhere, and take the first difference plus any that directly follow it
    # (firmware may leave PG set for a few halfwords). A difference somewhere else
    # was not made by this program: leave it for the audit to report.
    found = []
    last = st(LAST)
    a = last + 2 if last else 0
    while a and FLASH_BASE <= a < FLASH_BASE + FLASH_SIZE and differs(a):
        found.append(a)
        a += 2
    if not found:
        diffs = all_differences()
        for d in diffs:
            if not found or d == found[-1] + 2:
                found.append(d)
        if len(diffs) > len(found) and not st(AUDIT):
            st_w(AUDIT, [d for d in diffs if d not in found][0])
    return found


def settle_program():
    # PG was just cleared: account for what the program wrote, the way the chip would
    global sr_err
    st_w(PENDING, 0)
    found = written_halfwords()
    if not found:
        # flash is as it was: the program wrote the value already there. In a
        # sequential copy that is the next halfword, so say so, as a guess.
        last = st(LAST)
        if last:
            st_w(LAST, last + 2)
        log("P? 0x%08X" % (last + 2 if last else 0))
    for n, a in enumerate(found):
        if n:
            st_w(OPCOUNT, st(OPCOUNT) + 1)      # PG stayed set: each further halfword is an operation
        new = int(bus.ReadWord(a))
        old = int(bus.ReadWord(a - FLASH_BASE + SHADOW))
        if old != 0xFFFF and new != 0x0000:
            bus.WriteWord(a, old)               # refused: the cell keeps what it had
            sr_err |= SR_PGERR
            if not st(REFUSED):
                st_w(REFUSED_AT, a)
            st_w(REFUSED, st(REFUSED) + 1)
            log("X 0x%08X 0x%04X 0x%04X" % (a, new, old))
        else:
            bus.WriteWord(a - FLASH_BASE + SHADOW, new)
            log("P 0x%08X 0x%04X" % (a, new))
        st_w(LAST, a)


if request.IsInit:
    regs = {0x10: 0x80, 0x14: 0, 0x04: 0}
    keystate = 0
    sr_err = 0
elif request.IsWrite:
    ensure_state()
    o, v = request.Offset, request.Value
    if o == 0x04:
        if keystate == 0 and v == 0x45670123: keystate = 1
        elif keystate == 1 and v == 0xCDEF89AB:
            keystate = 2; regs[0x10] &= ~0x80
        else: keystate = 0
    elif o == 0x10:
        old = regs[0x10]
        locked = old & 0x80
        if v & 0x80:                    # LOCK is write-1-to-set and restarts the key sequence
            locked = 0x80
            keystate = 0
        regs[0x10] = (v & ~(0x80 | 0x40)) | locked   # STRT clears itself when the operation ends
        unlocked = not locked
        starting_erase = unlocked and (v & 0x40) and (v & 0x6)
        starting_prog = unlocked and (v & 0x1) and not (old & 0x1)
        if st(PENDING) and not (v & 0x1):
            settle_program()
        if starting_erase or starting_prog:
            opcount = st(OPCOUNT)
            page_now = (regs[0x14] & ~(PAGE - 1)) if starting_erase else NEVER
            if (opcount == st(CUTPOINT) or (starting_erase and page_now == st(CUT_PAGE))) and not st(CUT_HIT):
                st_w(CUT_HIT, 1)
                st_w(CUT_KIND, 1 if starting_erase else 2)
                st_w(CUT_ADDR, (regs[0x14] & ~(PAGE - 1)) if starting_erase else 0)
                for c in bus.GetCPUs():
                    c.IsHalted = True            # power is gone: stop executing right here
            elif not st(CUT_HIT):
                st_w(OPCOUNT, opcount + 1)
                if starting_erase:
                    if v & 0x2:          # PER
                        a = regs[0x14] & ~(PAGE - 1)
                        if FLASH_BASE <= a < FLASH_BASE + FLASH_SIZE:
                            fill_ff(a, PAGE)
                        log("E 0x%08X" % a)
                    else:                # MER
                        fill_ff(FLASH_BASE, FLASH_SIZE)
                        log("M 0x%08X" % FLASH_BASE)
                else:
                    st_w(PENDING, 1)
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
    elif 0x100 <= o <= 0x134 or o in (0x140, 0x144):
        st_w((o - 0x100) // 4 + 1, v)
    else:
        regs[o] = v
elif request.IsRead:
    ensure_state()
    o = request.Offset
    if o == 0x0C: request.Value = 0x20 | sr_err   # EOP set, BSY clear, plus any error
    elif o == 0x1C: request.Value = 0x03FFFFFC    # OBR: no read protection
    elif 0x100 <= o <= 0x144: request.Value = st((o - 0x100) // 4 + 1)
    else: request.Value = regs.get(o, 0)
