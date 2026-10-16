# STM32L4 RCC for the emulator (RM0351). Renode has no L4 platform, so no RCC either. Like
# the F4 one next to it, this answers the ready flags and works the clock tree out from the
# registers, then tells the timers, the USARTs and the SysTick what they run at.
#
# The chip starts from MSI at 4 MHz (MSIRANGE 6). SYSCLK is MSI, HSI16, HSE or the PLL (SW);
# the PLL takes MSI, HSI16 or HSE, divides by M, multiplies by N and divides by R. Ready
# flags follow their enable bits at once and SWS follows SW. Enable and reset registers are
# plain storage: peripherals work whether or not their clock is on.
#
# Renode gives Python peripherals no parameters, so the engine rewrites the constant line
# below with the board's crystal when it copies this file.
HSE_HZ = 8000000
HSI16_HZ = 16000000
MSI_HZ = (100000, 200000, 400000, 800000, 1000000, 2000000, 4000000, 8000000, 16000000,
          24000000, 32000000, 48000000)
APB1 = ("timer2", "timer3", "timer4", "timer5", "timer6", "timer7", "usart2", "usart3")
APB2 = ("timer1", "timer8", "timer15", "timer16", "timer17", "usart1")
READY = {0x00: ((0, 1), (8, 10), (16, 17), (24, 25), (26, 27), (28, 29)),   # CR: MSI HSI HSE PLL PLLSAI1/2
         0x90: ((0, 1),),                                                # BDCR: LSE
         0x94: ((0, 1),)}                                                # CSR: LSI
AHB_DIV = (2, 4, 8, 16, 64, 128, 256, 512)


def msi():
    # MSIRGSEL picks the range from CR, otherwise the one CSR keeps for after standby
    cr = regs[0x00]
    rng = (cr >> 4) & 0xF if cr & 8 else (regs.get(0x94, 0x0C000600) >> 8) & 0xF
    return MSI_HZ[min(rng, len(MSI_HZ) - 1)]


def tree():
    # (HCLK, PCLK1-ish timer clock, PCLK2-ish timer clock, PCLK1, PCLK2)
    cfgr, pll = regs[0x08], regs[0x0C]
    sw = cfgr & 3
    if sw == 1:
        sysclk = HSI16_HZ
    elif sw == 2:
        sysclk = HSE_HZ
    elif sw == 3:
        src = pll & 3
        source = {1: msi(), 2: HSI16_HZ, 3: HSE_HZ}.get(src, 0)
        m, n, r = ((pll >> 4) & 7) + 1, (pll >> 8) & 0x7F, (((pll >> 25) & 3) + 1) * 2
        sysclk = source // m * n // r
    else:
        sysclk = msi()
    hpre = (cfgr >> 4) & 0xF
    hclk = sysclk // (AHB_DIV[hpre - 8] if hpre >= 8 else 1)
    out = [hclk]
    pclks = []
    for shift in (8, 11):
        pre = (cfgr >> shift) & 7
        div = 1 << (pre - 3) if pre >= 4 else 1
        out.append(hclk // div * (1 if div == 1 else 2))    # a divided bus doubles its timer clock
        pclks.append(hclk // div)
    return out + pclks


def tell():
    hclk, t1, t2, p1, p2 = tree()
    machine = self.GetMachine()
    for names, timer_hz, bus_hz in ((APB1, t1, p1), (APB2, t2, p2), (("nvic",), hclk, hclk)):
        for name in names:
            try:
                machine["sysbus." + name].Frequency = bus_hz if name.startswith("usart") else timer_hz
            except Exception:
                pass                    # this chip does not have that one


if request.IsInit:
    regs = {0x00: 0x00000063, 0x08: 0, 0x0C: 0x00001000, 0x94: 0x0C000600}
    told = False            # the machine does not exist yet when this is first run
elif request.IsWrite:
    o, v = request.Offset, request.Value
    for on, ready in READY.get(o, ()):
        v = (v | (1 << ready)) if v & (1 << on) else (v & ~(1 << ready))
    if o == 0x08:
        v = (v & ~0xC) | ((v & 3) << 2)       # SWS follows SW
    regs[o] = v
    if o in (0x00, 0x08, 0x0C):
        tell()
elif request.IsRead:
    if not told:
        tell()
        told = True
    request.Value = regs.get(request.Offset, 0)
