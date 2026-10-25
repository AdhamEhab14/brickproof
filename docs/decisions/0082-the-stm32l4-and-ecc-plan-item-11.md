# The STM32L4, and ECC (plan item 11)

2026-10-16

Renode has no STM32L4 platform, so `platforms/stm32l476.repl` is written out here, as the
nRF52840's is: the core, flash (also at 0), SRAM1 and SRAM2, USART1-3 (Renode's STM32F7_USART
has the L4's register layout), GPIO A-C, the IWDG, and two models of ours, the flash
controller (`stm32l4_flash.py`) and an RCC (`stm32l4_rcc.py`: MSI at 4 MHz from reset, HSI16,
HSE, the PLL, and the frequencies handed to the timers, USARTs and SysTick). The register
layout and bit positions come from ST's CMSIS header for the L476 (cmsis_device_l4). The
flash is the one the L4, G0, G4, WB and WL share, so the model covers that whole family.

**The rules.** A program writes a 64-bit double word as two word stores, the first at the
8-byte boundary; the operation is the second store. SIZERR for a store that is not 32 bits,
PGAERR for a first word off the boundary or a second word anywhere else, PROGERR for a
double word that is not erased unless the new value is all zeros, PGSERR for any program
while an earlier error flag is still set. The last one is a common firmware mistake (not
clearing SR after a failed program makes every later one fail) that plain memory never
shows. Page erase (PER, PNB, BKER for bank 2), bank erase (MER1, MER2), option bytes at
0x1FFF7800 as five words with their complements, written by OPTSTRT as an erase and five
programs, loaded at reset (a mismatch loads as all ones and sets OPTVERR, as on the F1),
RDP 1 to 0 erasing both banks first, level 2 for good, IWDG_SW cleared starting the watchdog.

**ECC.** Every double word carries 8 check bits written with it. A program or erase that
finishes leaves them right; one cut short leaves them wrong, and on the chip a read of that
double word sets ECCD in ECCR (with the address) and raises an NMI. This is where L4 and G0
bootloaders brick after a power loss: an erase cut short leaves a page that reads as noise
and faults on every read, and a bootloader that never expected an NMI from a flash read
hangs in its default handler. The engine keeps an ECC map, one byte per double word, as
the last part of every flash image, so it is saved, restored, replayed and compared like the
flash. Replaying a finished operation marks what it wrote sound. A torn state marks broken
the double words its operation touched; for a torn erase only those that were not blank,
since a blank double word had nothing to erase. Correctable single-bit errors (ECCC) are not
modelled: broken is always ECCD. The model checks data reads (not instruction fetches)
only while the map has a broken double word, since
watching costs time. The NMI is raised through the core's own ICSR.NMIPENDSET, which Renode
was checked to honour.

Reading the 128 KB map back costs about 13 s, so the engine reads it only when the model
counts a broken double word, and otherwise knows it is all zeros.

**Times** from the STM32L4 datasheets' flash table (the L412 and L475 give the same, the
L476's own table not found to compare): 81.69 us per double word (90.76 at most), 22.02 ms
per page (24.47), 22.13 ms per bank (24.59).

**Not modelled:** bank 2's write-protected areas and PCROP (the adapter refuses them), fast
programming (FSTPG), the data and instruction caches, dual-bank swap (BFB2).

**The demo** runs on it: `common/chip_l476.h`, 2 KB pages, Slot A and B in bank 1. Its
bootloader handles the NMI (clears ECCD, notes it) and treats whatever it was reading as
invalid: an image whose header or body faulted, a floor record that faulted. The floor record
is two double words, the magic last. `BUG_NO_ECC_NMI` leaves the NMI to the default handler.
Results: the correct build 194/194 (every clean cut, every torn state); the bug build passes
every clean cut and fails its first torn state, a cut inside the floor record's program; the
other bug builds as on the F411. tests/renode/test_l4_rules.py checks the program errors,
page erase in both banks, and an ECC error's ECCD, address and clearing.
