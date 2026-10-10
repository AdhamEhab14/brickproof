# STM32F1 flash controller (FPEC) for the emulator: lock/unlock, page and mass
# erase, always ready. It also numbers every flash operation, can stop the machine
# at a chosen one (how the power-cut tests "pull the plug"), and can log each
# operation to a file (the golden-run trace).
#
# An operation starts when software sets STRT (erase) or sets PG (program). The
# halfword itself is written by the CPU straight into flash memory afterwards, so
# the model never sees its address. When tracing, it finds it by comparing flash
# with a shadow copy once PG is cleared.
#
# Test-only registers (not on the real chip). They live in the bpState memory, not
# in this script's variables, because a firmware reset re-runs IsInit and would
# wipe them in the middle of an update:
#   0x100  opcount     operations started so far (read) / set (write)
#   0x104  cutpoint    pause when opcount reaches this value (0xFFFFFFFF = never)
#   0x108  cut info    read: 1 when the cut fired
#   0x10C  cut kind    read: 1 = erase, 2 = program, 0 = none
#   0x110  cut addr    read: page address of the erase that was cut (0 for a program)
#   0x114  cut page    pause when an erase of this page is about to start (0xFFFFFFFF = never)
#   0x118  fault addr  written by mem_guard.py: an address that does not exist on the chip
#   0x11C  fault pc    and where the CPU was when it touched it (both 0 = no fault)
#   0x120  trace       1 = append every operation to TRACE_FILE
#   0x124  pending     1 = a traced program is waiting for its address
#
# Renode gives Python peripherals no parameters, so the engine rewrites the
# constant lines below with the target's values when it copies this file.
PAGE = 0x400
FLASH_BASE = 0x08000000
FLASH_SIZE = 0x20000
STATE = 0x90000000
TRACE_FILE = ""
NEVER = 0xFFFFFFFF
MAGIC = 0xB81C0001          # state word 0: set once the defaults below are in place

from System import Convert

OPCOUNT, CUTPOINT, CUT_HIT, CUT_KIND, CUT_ADDR, CUT_PAGE, FAULT_ADDR, FAULT_PC, TRACE, PENDING = range(1, 11)


def st(i):
    return int(self.GetMachine().SystemBus.ReadDoubleWord(STATE + 4 * i))


def st_w(i, v):
    self.GetMachine().SystemBus.WriteDoubleWord(STATE + 4 * i, v & 0xFFFFFFFF)


def ensure_state():
    # the state memory starts as zeros, and a cutpoint of 0 would cut at once
    if st(0) != MAGIC:
        st_w(CUTPOINT, NEVER)
        st_w(CUT_PAGE, NEVER)
        st_w(0, MAGIC)


def log(text):
    f = open(TRACE_FILE, "a")
    f.write(text + chr(10))
    f.close()


def read_page(addr):
    return [int(b) for b in self.GetMachine().SystemBus.ReadBytes(addr, PAGE)]


def fingerprints():
    # one read of the whole flash, one string per page. Comparing these is native
    # code, so "did anything change anywhere?" costs a millisecond, not a scan.
    raw = self.GetMachine().SystemBus.ReadBytes(FLASH_BASE, FLASH_SIZE)
    return dict((FLASH_BASE + i, Convert.ToBase64String(raw, i, PAGE)) for i in range(0, FLASH_SIZE, PAGE))


def take_shadow():
    return dict((a, read_page(a)) for a in range(FLASH_BASE, FLASH_BASE + FLASH_SIZE, PAGE)), fingerprints()


def changed_in(page, shadow, prints):
    # first halfword of this page that differs from the shadow, or None
    now = read_page(page)
    was = shadow[page]
    for i in range(0, PAGE, 2):
        if now[i] != was[i] or now[i + 1] != was[i + 1]:
            was[i], was[i + 1] = now[i], now[i + 1]
            prints[page] = Convert.ToBase64String(self.GetMachine().SystemBus.ReadBytes(page, PAGE))
            return page + i, now[i] | (now[i + 1] << 8)
    return None


def find_program(shadow, prints, last):
    # where did the last program land? Copies are sequential, so try the page being
    # filled and the next one first. Otherwise look at every page's fingerprint.
    if last:
        here = last & ~(PAGE - 1)
        for page in (here, here + PAGE):
            if page in shadow:
                hit = changed_in(page, shadow, prints)
                if hit:
                    return hit
    now = fingerprints()
    for page in sorted(now):
        if now[page] != prints[page]:
            hit = changed_in(page, shadow, prints)
            if hit:
                return hit
    return None


if request.IsInit:
    regs = {0x10: 0x80, 0x0C: 0x0, 0x14: 0, 0x04: 0}
    keystate = 0
    shadow = None           # rebuilt on demand: a reset does not change flash
    prints = None
    last_prog = 0
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
        tracing = st(TRACE) == 1
        if tracing and st(PENDING) and not (v & 0x1):
            # PG was just cleared: the halfword is in flash now, go and find it
            st_w(PENDING, 0)
            hit = find_program(shadow, prints, last_prog) if shadow is not None else None
            if hit:
                last_prog = hit[0]
                log("P 0x%08X 0x%04X" % hit)
            else:
                # nothing changed (it wrote what was already there), or a reset lost
                # the shadow. In a sequential copy the next halfword is the best guess.
                last_prog = last_prog + 2 if last_prog else 0
                log("P? 0x%08X" % last_prog)
        if starting_erase or starting_prog:
            opcount = st(OPCOUNT)
            page_now = (regs[0x14] & ~(PAGE - 1)) if starting_erase else NEVER
            if (opcount == st(CUTPOINT) or (starting_erase and page_now == st(CUT_PAGE))) and not st(CUT_HIT):
                st_w(CUT_HIT, 1)
                st_w(CUT_KIND, 1 if starting_erase else 2)
                st_w(CUT_ADDR, (regs[0x14] & ~(PAGE - 1)) if starting_erase else 0)
                for c in self.GetMachine().SystemBus.GetCPUs():
                    c.IsHalted = True            # power is gone: stop executing right here
            elif not st(CUT_HIT):
                st_w(OPCOUNT, opcount + 1)
                if tracing and shadow is None:
                    shadow, prints = take_shadow()
                if starting_erase:
                    if v & 0x2:          # PER
                        a = regs[0x14] & ~(PAGE - 1)
                        for i in range(0, PAGE, 4):
                            self.GetMachine().SystemBus.WriteDoubleWord(a + i, 0xFFFFFFFF)
                        if tracing:
                            shadow[a] = [0xFF] * PAGE
                            prints[a] = Convert.ToBase64String(self.GetMachine().SystemBus.ReadBytes(a, PAGE))
                            log("E 0x%08X" % a)
                    else:                # MER
                        for i in range(0, FLASH_SIZE, 4):
                            self.GetMachine().SystemBus.WriteDoubleWord(FLASH_BASE + i, 0xFFFFFFFF)
                        if tracing:
                            shadow, prints = take_shadow()
                            log("M 0x%08X" % FLASH_BASE)
                elif tracing:
                    st_w(PENDING, 1)
    elif o == 0x0C:
        pass                             # flags are write-1-to-clear; we never set errors
    elif o == 0x104 or o == 0x114:       # arming a cut clears the last one's result
        st_w(CUTPOINT if o == 0x104 else CUT_PAGE, v)
        st_w(CUT_HIT, 0)
        st_w(CUT_KIND, 0)
        st_w(CUT_ADDR, 0)
    elif o == 0x120:
        if v == 1:
            shadow, prints = take_shadow()
            last_prog = 0
        st_w(PENDING, 0)
        st_w(TRACE, v)
    elif 0x100 <= o <= 0x124:
        st_w((o - 0x100) // 4 + 1, v)
    else:
        regs[o] = v
elif request.IsRead:
    ensure_state()
    o = request.Offset
    if o == 0x0C: request.Value = 0x20   # EOP set, BSY clear
    elif o == 0x1C: request.Value = 0x03FFFFFC  # OBR: no read protection
    elif 0x100 <= o <= 0x124: request.Value = st((o - 0x100) // 4 + 1)
    else: request.Value = regs.get(o, 0)
