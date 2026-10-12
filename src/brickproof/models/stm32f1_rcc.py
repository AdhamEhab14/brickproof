# STM32F1 RCC for the emulator: ready flags follow the enable bits and SWS follows SW.
# It also works the clock tree out from CFGR and tells the timers and the SysTick, which
# Renode otherwise leaves counting from a fixed 10 MHz whatever the firmware configures.
# A prescaler written for 72 MHz then means what it says.
#
# Renode gives Python peripherals no parameters, so the engine rewrites the constant
# line below with the board's crystal when it copies this file.
HSE_HZ = 8000000
HSI_HZ = 8000000
APB1_TIMERS = ("timer2", "timer3", "timer4", "timer5", "timer6", "timer7", "timer12", "timer13", "timer14")
APB2_TIMERS = ("timer1", "timer8", "timer9", "timer10", "timer11")
AHB_DIV = (2, 4, 8, 16, 64, 128, 256, 512)


def tree():
    # (HCLK, timer clock on APB1, timer clock on APB2) as the registers describe them
    cfgr = regs.get(0x04, 0)
    sw = cfgr & 3
    if sw == 1:
        sysclk = HSE_HZ
    elif sw == 2:
        if cfgr & (1 << 16):
            source = HSE_HZ // (2 if cfgr & (1 << 17) else 1)
        else:
            source = HSI_HZ // 2
        sysclk = source * min(((cfgr >> 18) & 0xF) + 2, 16)
    else:
        sysclk = HSI_HZ
    hpre = (cfgr >> 4) & 0xF
    hclk = sysclk // (AHB_DIV[hpre - 8] if hpre >= 8 else 1)
    out = [hclk]
    for shift in (8, 11):
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
    regs = {0x00: 0x00000083, 0x04: 0x0}
    told = False            # the machine does not exist yet when this is first run
elif request.IsWrite:
    v = request.Value
    if request.Offset == 0x00: v &= ~((1 << 1) | (1 << 17) | (1 << 25))   # RDY flags are read-only
    elif request.Offset == 0x04: v &= ~0xC                                 # SWS is read-only
    regs[request.Offset] = v
    if request.Offset in (0x00, 0x04) or not told:
        told = True
        tell()
elif request.IsRead:
    v = regs.get(request.Offset, 0)
    if request.Offset == 0x00:
        if v & (1 << 0): v |= (1 << 1)      # HSION  -> HSIRDY
        if v & (1 << 16): v |= (1 << 17)    # HSEON  -> HSERDY
        if v & (1 << 24): v |= (1 << 25)    # PLLON  -> PLLRDY
    elif request.Offset == 0x04:
        v = (v & ~0xC) | ((v & 0x3) << 2)   # SWS = SW
    if not told:
        told = True
        tell()
    request.Value = v
