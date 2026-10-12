# STM32F4 RCC for the emulator. Renode's own model answers the ready flags but keeps the
# clock tree to itself, so a timer goes on counting from a fixed 10 MHz whatever the
# firmware configures. This one works the tree out from PLLCFGR and CFGR and tells the
# timers and the SysTick, so that a prescaler written for 84 MHz means what it says.
#
# Ready flags follow their enable bits at once and SWS follows SW. Enable and reset
# registers are plain storage: peripherals work whether or not their clock is on.
#
# Renode gives Python peripherals no parameters, so the engine rewrites the constant
# line below with the board's crystal when it copies this file.
HSE_HZ = 8000000
HSI_HZ = 16000000
APB1_TIMERS = ("timer2", "timer3", "timer4", "timer5", "timer6", "timer7", "timer12", "timer13", "timer14")
APB2_TIMERS = ("timer1", "timer8", "timer9", "timer10", "timer11")
READY = {0x00: ((0, 1), (16, 17), (24, 25), (26, 27)),      # CR: HSI, HSE, PLL, PLLI2S
         0x70: ((0, 1),),                                   # BDCR: LSE
         0x74: ((0, 1),)}                                   # CSR: LSI
AHB_DIV = (2, 4, 8, 16, 64, 128, 256, 512)


def tree():
    # (HCLK, timer clock on APB1, timer clock on APB2) as the registers describe them
    pll, cfgr = regs[0x04], regs[0x08]
    sw = cfgr & 3
    if sw == 1:
        sysclk = HSE_HZ
    elif sw == 2:
        source = HSE_HZ if pll & (1 << 22) else HSI_HZ
        m, n, p = pll & 0x3F, (pll >> 6) & 0x1FF, (((pll >> 16) & 3) + 1) * 2
        sysclk = source // max(m, 1) * n // p
    else:
        sysclk = HSI_HZ
    hpre = (cfgr >> 4) & 0xF
    hclk = sysclk // (AHB_DIV[hpre - 8] if hpre >= 8 else 1)
    out = [hclk]
    for shift in (10, 13):
        pre = (cfgr >> shift) & 7
        div = 1 << (pre - 3) if pre >= 4 else 1
        out.append(hclk // div * (1 if div == 1 else 2))    # a divided bus doubles its timer clock
    return out


def tell():
    # hand the clocks to the peripherals that count with them
    hclk, t1, t2 = tree()
    machine = self.GetMachine()
    for names, hz in ((APB1_TIMERS, t1), (APB2_TIMERS, t2), (("nvic",), hclk)):
        for name in names:
            try:
                machine["sysbus." + name].Frequency = hz
            except Exception:
                pass                    # this chip does not have that one


if request.IsInit:
    regs = {0x00: 0x00000083, 0x04: 0x24003010, 0x08: 0}
    told = False            # the machine does not exist yet when this is first run
elif request.IsWrite:
    o, v = request.Offset, request.Value
    for on, ready in READY.get(o, ()):
        v &= ~(1 << ready)              # ready flags are read-only
    if o == 0x08:
        v &= ~0xC                       # so is SWS
    regs[o] = v
    if o in (0x00, 0x04, 0x08) or not told:
        told = True
        tell()
elif request.IsRead:
    o = request.Offset
    v = regs.get(o, 0)
    for on, ready in READY.get(o, ()):
        if v & (1 << on):
            v |= 1 << ready
    if o == 0x08:
        v = (v & ~0xC) | ((v & 0x3) << 2)   # SWS = SW
    if not told:
        told = True
        tell()
    request.Value = v
