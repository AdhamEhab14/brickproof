"""The flash models' test registers, which the engine reads and writes to arm cuts and
learn what happened, and the operation codes of their trace (models/*_flash.py)."""

# test-only registers of the BrickProof flash models (see models/stm32f1_flash.py)
REG_OPCOUNT = 0x100
REG_CUTPOINT = 0x104
REG_CUT_FIRED = 0x108
REG_CUT_KIND = 0x10C
REG_CUT_ADDR = 0x110
REG_CUT_PAGE = 0x114
REG_FAULT_ADDR = 0x118
REG_FAULT_PC = 0x11C
REG_TRACE = 0x120
REG_PENDING = 0x124
REG_AUDIT = 0x128
REG_REFUSED = 0x12C
REG_REFUSED_AT = 0x130
REG_RESYNC = 0x138
REG_COMPARE = 0x13C
REG_CMP_FROM = 0x140
REG_CMP_LEN = 0x144
REG_PROTECTED = 0x148
REG_PROTECTED_AT = 0x14C
REG_PCROP_READS = 0x150         # STM32F4: data reads of proprietary-code (PCROP) sectors
REG_PCROP_AT = 0x154
REG_ECC_BROKEN = 0x160          # STM32L4: double words whose ECC does not match (internal)
ECC_MAP = 0x94000000            # STM32L4: the flash model's ECC map, a byte per double word
STATE_PWR_FLAGS = 0x90000000 + 4 * 41     # the PWR model's SBF and WUF (models/stm32_pwr.py)
STATE_PWR_ASLEEP = 0x90000000 + 4 * 45    # and the Standby a wake is due for
STATE_RESETS = 0x90000000 + 4 * 60        # resets the flash model has seen since power-up
EXPECT_BASE = 0x92000000         # bpExpect: an image for the flash model to compare flash with
TRACE_KINDS = {"E": "erase", "M": "mass_erase", "P": "program", "P?": "program", "X": "refused",
               "W": "protected", "Q": "partial_erase"}
NEVER = 0xFFFFFFFF
CUT_ERASE = 1
CUT_PROGRAM = 2
