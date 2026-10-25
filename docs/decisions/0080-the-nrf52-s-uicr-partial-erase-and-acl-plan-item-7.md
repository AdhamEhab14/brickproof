# The nRF52's UICR, partial erase and ACL (plan item 7)

2026-10-16

From the nRF52840 Product Specification (NVMC, UICR, ACL chapters) and the register fields
in Nordic's MDK (nrf52840_bitfields.h, nrfx v3.0.0), which settles what the specification
pages leave unclear: ACL PERM's WRITE is bit 1 and READ bit 2, ERASEPAGEPARTIALCFG's
DURATION is 7 bits of milliseconds (10 after reset).

**UICR.** It is flash, with the code area's rules, and the engine already had a place for
memory like it: the STM32 option bytes. So the nRF52's option bytes are now its UICR,
0x400 bytes at 0x10001000 (the last register, REGOUT0, is at 0x304), after the code area
in an image. Images saved for the nRF52 before this are 0x400 bytes shorter. ERASEALL
erases the UICR too, which an STM32 mass erase does not do to its option bytes, so the
geometry says which (`mass_erase_ob`) and the replay and `value_before` follow it.
`read_protected: true` writes APPROTECT as Enabled (0x00); what APPROTECT does to a debugger
is not modelled, since the engine is not a debugger. Partial erase does not apply to the
UICR (the specification says so), and the model ignores it there.

**Partial erase.** The specification: a page is erased once the partial erase time spent on
it reaches tERASEPAGE, and its bits are undefined until then. Undefined is not something a
replay can reproduce, so the model makes it definite: each 0 bit of the page needs its own
share of tERASEPAGE (an integer hash of its position, spread evenly), and reads 1 once the
time spent passes it. The same function is in the model and in `trace.py`, and a Renode
test checks that the model's page equals the replay's after 1, 4 and 8 steps. The page so
far is old data with bits flipped to 1, never anything a program could not have reached;
firmware reading it as data before the erase is done sees a mix, as it would on the chip.
Each step is an operation (traced as `Q`, kind `partial_erase`, with the time so far), so
a cut can fall between any two. The time spent is kept per page in model memory, not in the
image: after a power cut a page starts from zero again, so firmware that starts its erase
over erases for longer than it needs, which is the safe side of not knowing. A completed
partial erase counts as one erase cycle for wear. Torn states are not made for a partial
step: it is already a part of an erase.

**ACL.** Eight regions, each register written once until a reset, enforced once its address
is on a page boundary and its size a whole number of pages. On the chip a blocked access is
a bus fault. Here a blocked write or erase is refused and fails the run as write protection
(the STM32 models' registers and message), and a blocked read is counted and fails it as a
protected read (the PCROP registers). The specification does not say whether ERASEPAGE and
ERASEALL are blocked in a region; the model blocks them, on the side of reporting.

**A Renode quirk for the rule tests:** a single `b .` stops Renode from taking a new PC from
the monitor, so test snippets end in `nop` and a branch back to it.
