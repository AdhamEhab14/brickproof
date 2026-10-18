# STM32F1 flash controller (FPEC) for the emulator: lock/unlock, page and mass
# erase, option bytes, always ready. On top of that it does these jobs for BrickProof:
#
#   counts every flash operation and can stop the CPU at a chosen one
#     (how the power-cut tests "pull the plug");
#   enforces the chip's programming rule, which Renode's plain memory does not:
#     a halfword that is not erased can only be programmed to 0x0000. Anything
#     else is refused: the old value stays and PGERR is set;
#   enforces write protection: an erase or a program in a page the option bytes
#     protect is refused and WRPRTERR is set;
#   notices flash changing with no flash operation behind it (a store with PG
#     clear, or with the controller locked): silicon ignores those, Renode stores them;
#   can log each operation to a file (the golden-run trace);
#   makes each operation take the time it takes on the chip (TIMING below). The CPU
#     runs from flash, and flash cannot be read while it is being erased or programmed,
#     so the chip simply stops for that long. The model skips the same amount of
#     virtual time: timers, watchdogs and timeouts see a 30 ms erase as 30 ms.
#
# An erase is an operation when software sets STRT. A program is an operation when the
# CPU stores into flash while PG is set. That store goes straight into Renode's flash
# memory, so while PG is set the model listens to the CPU's memory accesses (and only
# then, because listening is slow) and applies the chip's rules to each store as it
# lands. It also keeps a shadow copy of flash that only real operations update.
# Whatever differs from the shadow later was stored with PG clear, which the chip
# ignores: that is what the audit reports.
#
# Option bytes are 16 bytes at OB_BASE: RDP, USER, Data0, Data1, WRP0..WRP3, each a
# data byte followed by its complement. They are read into the WRPR and OBR registers
# at reset, as on the chip, so a change only takes effect after the next reset. They
# are erased and programmed through OPTER and OPTPG (after the OPTKEYR keys), and those
# are operations like any other: counted, traced, and a power cut can fall on them.
# For the shadow and the compare the option bytes sit right after the flash image.
# The USER byte's WDG_SW bit is honoured: when it is cleared the independent watchdog
# starts by itself at every reset, as on the chip, and the firmware cannot stop it.
# One consequence is modelled because a power cut can trigger it: erasing the option
# bytes leaves the read-protection byte erased, which the chip reads as "protected"
# at the next reset, and writing the unprotected value back while protection is in
# force makes the chip mass-erase the main flash.
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
#   0x124  (unused)
#   0x128  audit       write 1: compare flash with the shadow. read: first address that
#                      differs, 0 if none. write 0: forget the last result
#   0x12C  refused     programs refused by the programming rule (write 0 to clear)
#   0x130  refused at  address of the first one
#   0x134  (unused)
#   0x138  resync      write: make the shadow equal to flash (after the engine loads an image)
#   0x13C  compare     write: compare flash with the image the engine loaded into bpExpect.
#                      read: first address that differs, 0 if they are equal
#   0x140  from        the range to compare: first flash address,
#   0x144  length      and how many bytes (0 = the whole flash)
#   0x148  protected   operations refused by write protection (write 0 to clear)
#   0x14C  protected at  address of the first one
#
# Renode gives Python peripherals no parameters, so the engine rewrites the
# constant lines below with the target's values when it copies this file.
PAGE = 0x400
FLASH_BASE = 0x08000000
FLASH_SIZE = 0x20000
WRP_UNIT = 0x1000
STATE = 0x90000000
SHADOW = 0x91000000
EXPECT = 0x92000000
TRACE_FILE = ""
OB_BASE = 0x1FFFF800
OB_SIZE = 16
# How long operations take: 0 = no time at all, 1 = typical, 2 = the slowest the datasheet
# allows. DS5319 table 28: programming 16 bits takes 40 to 70 us (52.5 typical), a page or
# mass erase 20 to 40 ms. No typical erase time is given, so the middle is used.
TIMING = 0
WORN_FROM = 0x0           # worn pages (flash.worn): [WORN_FROM, WORN_TO), none by default
WORN_TO = 0x0
T_PROGRAM_US = (0, 53, 70)
T_ERASE_US = (0, 30000, 40000)
IWDG_KR = 0x40003000        # writing 0xCCCC here starts the independent watchdog
NEVER = 0xFFFFFFFF
MAGIC = 0xB81C0003          # state word 0: set once the defaults below are in place
SR_PGERR = 0x04
SR_WRPRTERR = 0x10
CR_PG, CR_PER, CR_MER, CR_OPTPG, CR_OPTER, CR_STRT, CR_LOCK, CR_OPTWRE = 1, 2, 4, 0x10, 0x20, 0x40, 0x80, 0x200

from System import Array, Byte, Convert
from Antmicro.Renode.Time import TimeInterval

(OPCOUNT, CUTPOINT, CUT_HIT, CUT_KIND, CUT_ADDR, CUT_PAGE, FAULT_ADDR, FAULT_PC,
 TRACE, PENDING, AUDIT, REFUSED, REFUSED_AT, LAST, _RESYNC, COMPARE, CMP_FROM, CMP_LEN,
 PROTECTED, PROTECTED_AT) = range(1, 21)
RESETS = 60                 # state word: resets since the engine last cleared it (all models)

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


def after_reset(machine, ob=OB_BASE, kr=IWDG_KR, resets=STATE + 4 * RESETS):
    # Runs after every reset of the machine, for as long as this emulator lives. With
    # WDG_SW cleared in the USER option byte the watchdog is a hardware one: it is
    # running before the first instruction, with its reset timeout of about 0.4 s.
    # The values come in as defaults because this outlives the script that defined it.
    # Every reset is counted, so the engine can tell a device that keeps rebooting.
    b = machine.SystemBus
    b.WriteDoubleWord(resets, (int(b.ReadDoubleWord(resets)) + 1) & 0xFFFFFFFF)
    for c in b.GetCPUs():
        c.SetHookAtMemoryAccess(None)           # a reset ends any program that was going on
    if not int(b.ReadByte(ob + 2)) & 1:
        b.WriteDoubleWord(kr, 0xCCCC)


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


def load_option_bytes():
    # what the chip does at reset: WRPR and OBR are loaded from the option bytes.
    # Returns (wrpr, read protected, obr). A set bit in WRPR means "not protected".
    # OBR shows OPTERR in bit 0, RDPRT in bit 1, then the USER byte, Data0 and Data1.
    # Each option byte is stored with its complement. Where the two do not match, the
    # chip sets OPTERR and loads that byte as 0xFF (RM0008, FLASH_OBR): an RDP byte
    # read that way means "protected", a WRP byte that way means "not protected".
    ob = bus.ReadBytes(OB_BASE, OB_SIZE)
    byte = []
    opterr = 0
    for i in range(OB_SIZE // 2):
        b, c = int(ob[2 * i]), int(ob[2 * i + 1])
        if b ^ c != 0xFF:
            b, opterr = 0xFF, 1
        byte.append(b)
    wrpr = byte[4] | (byte[5] << 8) | (byte[6] << 16) | (byte[7] << 24)
    protected = byte[0] != 0xA5
    obr = (byte[3] << 18) | (byte[2] << 10) | (byte[1] << 2) | (2 if protected else 0) | opterr
    return wrpr, protected, obr


def is_protected(addr):
    # write protection goes in units of WRP_UNIT, one bit each; the last bit covers the rest
    bit = min((addr - FLASH_BASE) // WRP_UNIT, 31)
    if rdp and bit == 0:
        return True                     # read protection also write-protects the first unit
    return not (wrpr >> bit) & 1


def refuse_protected(addr):
    global sr_err
    sr_err |= SR_WRPRTERR
    if not st(PROTECTED):
        st_w(PROTECTED_AT, addr)
    st_w(PROTECTED, st(PROTECTED) + 1)
    log("W 0x%08X" % addr)


def differs(addr):
    return int(bus.ReadWord(addr)) != int(bus.ReadWord(shadow_of(addr)))


def all_differences():
    # every halfword where flash is not what the shadow says. Pages are compared
    # as strings first (native code), so a clean flash costs about a millisecond.
    now = bus.ReadBytes(FLASH_BASE, FLASH_SIZE)
    was = bus.ReadBytes(SHADOW, FLASH_SIZE)
    out = []
    if Convert.ToBase64String(now) != Convert.ToBase64String(was):
        for p in range(0, FLASH_SIZE, PAGE):
            if Convert.ToBase64String(now, p, PAGE) != Convert.ToBase64String(was, p, PAGE):
                for i in range(p, p + PAGE, 2):
                    if now[i] != was[i] or now[i + 1] != was[i + 1]:
                        out.append(FLASH_BASE + i)
    return out + option_differences()


def option_differences():
    return [OB_BASE + i for i in range(0, OB_SIZE, 2) if differs(OB_BASE + i)]


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


def get(addr, size):
    # `size` bytes as a number, least significant byte first
    raw = bus.ReadBytes(addr, size)
    v = 0
    for i in range(size):
        v |= int(raw[i]) << (8 * i)
    return v


def put(addr, size, v):
    bus.WriteBytes(Array[Byte]([(v >> (8 * i)) & 0xFF for i in range(size)]), addr)


def listen(on):
    # Hear every memory access of the CPU, or stop hearing them. Ending the current
    # block of translated code makes the very next instruction count already: the
    # store usually follows the write to CR at once.
    for c in bus.GetCPUs():
        c.SetHookAtMemoryAccess(on_access if on else None)
        if on:
            c.RequestTranslationBlockRestart()


def on_access(pc, operation, virtual, addr, width, value):
    # called by the CPU after each of its memory accesses while PG or OPTPG is set
    if str(operation) != "MemoryWrite":
        return
    addr = int(addr)
    if addr < FLASH_SIZE:
        addr += FLASH_BASE                      # a store through the boot alias at address 0
    if FLASH_BASE <= addr < FLASH_BASE + FLASH_SIZE or OB_BASE <= addr < OB_BASE + OB_SIZE:
        program(addr, int(width), int(value))


def power_off(kind, addr):
    # the cut: nothing executes from here on
    st_w(CUT_HIT, 1)
    st_w(CUT_KIND, kind)
    st_w(CUT_ADDR, addr)
    for c in bus.GetCPUs():
        c.IsHalted = True


def worn(a):
    # a worn page (flash.worn in the adapter): programs there report success, but bit 0 of
    # each cell no longer changes, so the data read back differs from what was written
    return WORN_FROM <= a < WORN_TO


def refuse(addr, new, old):
    # the programming rule: the cell keeps what it had and PGERR is set
    global sr_err
    sr_err |= SR_PGERR
    if not st(REFUSED):
        st_w(REFUSED_AT, addr)
    st_w(REFUSED, st(REFUSED) + 1)
    log("X 0x%08X 0x%04X 0x%04X" % (addr, new & 0xFFFF, old & 0xFFFF))


def program(a, width, value):
    # One store into flash or the option bytes while PG or OPTPG is set. It has already
    # landed in Renode's memory. What the chip makes of it is decided here.
    old = get(shadow_of(a), width)
    options = a >= OB_BASE
    if st(CUT_HIT):
        put(a, width, old)                      # the power is off
        return
    if not regs[0x10] & (CR_OPTPG if options else CR_PG):
        put(a, width, old)                      # the wrong kind of program for this address:
        if not st(AUDIT):                       # nothing is written, and it is worth reporting
            st_w(AUDIT, a)
        return
    opcount = st(OPCOUNT)
    if opcount == st(CUTPOINT):
        put(a, width, old)                      # the power goes just before this store
        power_off(2, 0)
        for c in bus.GetCPUs():
            c.RequestTranslationBlockRestart()  # and not after the rest of this block
        return
    st_w(OPCOUNT, opcount + 1)
    spend(T_PROGRAM_US[TIMING])
    if width != 2:
        put(a, width, old)                      # the F1 programs halfwords and nothing else
        refuse(a, value, old)
    elif options:
        # the chip stores the data byte and, next to it, its complement, whatever the
        # upper byte of the written halfword was
        data = value & 0xFF
        if old != 0xFFFF:
            put(a, 2, old)                      # an option byte must be erased first
            refuse(a, data, old)
            return
        stored = data | ((~data & 0xFF) << 8)
        put(a, 2, stored)
        put(shadow_of(a), 2, stored)
        log("P 0x%08X 0x%04X @%d" % (a, stored, T_PROGRAM_US[TIMING]))
        if a == OB_BASE and data == 0xA5 and rdp:
            # Read protection was in force (loaded at reset) and is being removed.
            # The chip answers that by erasing the whole main flash.
            if st(OPCOUNT) == st(CUTPOINT):
                power_off(1, FLASH_BASE)
                return
            st_w(OPCOUNT, st(OPCOUNT) + 1)
            fill_ff(FLASH_BASE, FLASH_SIZE)
            log("M 0x%08X @%d" % (FLASH_BASE, spend(T_ERASE_US[TIMING])))
    elif is_protected(a):
        put(a, 2, old)                          # write-protected: nothing is written
        refuse_protected(a)
    elif old != 0xFFFF and value != 0x0000:
        put(a, 2, old)                          # not erased, and not being cleared to zero
        refuse(a, value, old)
    else:
        stored = (value & ~1) | (old & 1) if worn(a) else value
        put(a, 2, stored)
        put(shadow_of(a), 2, stored)
        log("P 0x%08X 0x%04X @%d" % (a, stored, T_PROGRAM_US[TIMING]))


if request.IsInit:
    regs = {0x10: 0x80, 0x14: 0, 0x04: 0}
    keystate = 0
    optkeystate = 0
    sr_err = 0
    wrpr = None             # loaded from the option bytes on first use after this reset
    rdp = False
    obr = 0
    listening = False       # whether the CPU's memory accesses are being heard (see listen)
elif request.IsWrite or request.IsRead:
    ensure_state()
    if wrpr is None:
        wrpr, rdp, obr = load_option_bytes()
    o = request.Offset

    if request.IsRead:
        if o == 0x0C: request.Value = 0x20 | sr_err   # EOP set, BSY clear, plus any error
        elif o == 0x1C: request.Value = obr           # OPTERR, RDPRT, USER, Data0, Data1
        elif o == 0x20: request.Value = wrpr
        elif 0x100 <= o <= 0x14C: request.Value = st((o - 0x100) // 4 + 1)
        else: request.Value = regs.get(o, 0)
    else:
        v = request.Value
        if o == 0x04:
            if keystate == 0 and v == 0x45670123: keystate = 1
            elif keystate == 1 and v == 0xCDEF89AB:
                keystate = 2; regs[0x10] &= ~CR_LOCK
            else: keystate = 0
        elif o == 0x08:                     # OPTKEYR: the same two keys allow option byte writes
            if optkeystate == 0 and v == 0x45670123: optkeystate = 1
            elif optkeystate == 1 and v == 0xCDEF89AB:
                optkeystate = 2; regs[0x10] |= CR_OPTWRE
            else: optkeystate = 0
        elif o == 0x10:
            old = regs[0x10]
            locked = old & CR_LOCK
            optwre = old & CR_OPTWRE
            if v & CR_LOCK:                 # LOCK is write-1-to-set and restarts the key sequence
                locked = CR_LOCK
                keystate = 0
            if not v & CR_OPTWRE:           # OPTWRE can be cleared by software, set only by the keys
                optwre = 0
                optkeystate = 0
            regs[0x10] = (v & ~(CR_LOCK | CR_STRT | CR_OPTWRE)) | locked | optwre   # STRT clears itself
            unlocked = not locked
            starting_erase = unlocked and (v & CR_STRT) and (v & (CR_PER | CR_MER))
            starting_opt_erase = unlocked and optwre and (v & CR_STRT) and (v & CR_OPTER)
            # stores into flash are programs for as long as PG is set, and stores into
            # the option bytes for as long as OPTPG is
            programming = bool(unlocked and ((v & CR_PG) or (optwre and (v & CR_OPTPG))))
            if programming != listening:
                listening = programming
                listen(programming)
            if (starting_erase or starting_opt_erase) and not st(CUT_HIT):
                opcount = st(OPCOUNT)
                page_now = OB_BASE if starting_opt_erase else regs[0x14] & ~(PAGE - 1)
                if opcount == st(CUTPOINT) or page_now == st(CUT_PAGE):
                    power_off(1, page_now)      # power is gone: stop executing right here
                else:
                    st_w(OPCOUNT, opcount + 1)
                    if starting_opt_erase:
                        fill_ff(OB_BASE, OB_SIZE)
                        log("E 0x%08X @%d" % (OB_BASE, spend(T_ERASE_US[TIMING])))
                    elif v & CR_PER:
                        a = page_now
                        if not FLASH_BASE <= a < FLASH_BASE + FLASH_SIZE:
                            log("E 0x%08X" % a)      # outside flash: nothing to erase
                        elif is_protected(a):
                            refuse_protected(a)
                        else:
                            fill_ff(a, PAGE)
                            log("E 0x%08X @%d" % (a, spend(T_ERASE_US[TIMING])))
                    elif rdp or wrpr != 0xFFFFFFFF:  # MER: not done if any page is protected
                        refuse_protected(FLASH_BASE)
                    else:
                        fill_ff(FLASH_BASE, FLASH_SIZE)
                        log("M 0x%08X @%d" % (FLASH_BASE, spend(T_ERASE_US[TIMING])))
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
        else:
            regs[o] = v
