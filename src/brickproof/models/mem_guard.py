# Stands in for an address range that does not exist on the chip (past the end of
# RAM, past the end of flash). Renode answers such an access with 0 and carries on;
# silicon raises a bus fault. This stops the CPU there and latches the first such
# address in the flash model's test registers, where the engine reads it.
#
# The engine rewrites the two lines below when it copies this file, one copy per hole.
GUARD_BASE = 0x20005000
FAULT_REG = 0x40022118

if request.IsRead or request.IsWrite:
    bus = self.GetMachine().SystemBus
    if bus.ReadDoubleWord(FAULT_REG) == 0:
        pc = 0
        for c in bus.GetCPUs():
            pc = c.PC.RawValue
        bus.WriteDoubleWord(FAULT_REG, GUARD_BASE + request.Offset)
        bus.WriteDoubleWord(FAULT_REG + 4, pc)
    for c in bus.GetCPUs():
        c.IsHalted = True
    if request.IsRead:
        request.Value = 0
