# Helpers every flash model has, word for word. Renode runs each model as a script of its
# own and cannot import this file, so BrickProof puts it into each *_flash.py, at its
# FLASH_COMMON marker line, when it copies the model into the work folder
# (engine/workdir.py). They use the model's own globals: bus, STATE, EXPECT, FLASH_BASE,
# TRACE_FILE, and its imports of TimeInterval and EmulationManager.


def st(i):
    return int(bus.ReadDoubleWord(STATE + 4 * i))


def st_w(i, v):
    bus.WriteDoubleWord(STATE + 4 * i, v & 0xFFFFFFFF)


def log(text):
    if st(TRACE) == 1:
        f = open(TRACE_FILE, "a")
        f.write(text + chr(10))
        f.close()


def wake_clock():
    # Renode's clock can miss the CPU thread starting at the beginning of a RunFor, and
    # then wait out a 10 ms timeout each time the CPU stops early, which it does over and
    # over while flash is programmed: a one-second slice once took 450 s. Telling the
    # clock the CPU is active again ends that, and costs nothing when it was not waiting.
    EmulationManager.Instance.CurrentEmulation.MasterTimeSource.ReportHandleActive()
    bus.Machine.LocalTimeSource.ReportHandleActive()


def spend(us):
    # the chip is busy for this long and the CPU, which runs from flash, waits
    wake_clock()
    if us:
        for c in bus.GetCPUs():
            c.SkipTime(TimeInterval.FromMicroseconds(us))
    return us


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
