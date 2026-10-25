# A second chip family (STM32F411), and what it took

2026-10-11

"STM32F1 only" was a limit of the tool, so it got a second family that is different where it
matters. Done in two steps, each merged on its own.

**Step 1: the engine stopped assuming pages and halfwords** (PR #19). Two things were baked
in: an erase wipes a fixed-size page, and a program writes 16 bits. Now `FlashGeometry.unit_at`
answers what an erase at an address wipes (a uniform page, or one of a list of sectors), and
every traced program carries its size in bytes (the flash model logs the value with as many
hex digits as it wrote). Replay, the planner, torn states and the rewind after a cut use
those. F1 results did not move: demo 167/167.

**Step 2: the F411.** Renode's stock F4 flash controller keeps no trace, enforces nothing and
cannot stop the CPU, so the platform file unregisters it (`flash_controller: @ none`) and puts
`models/stm32f4_flash.py` at the same address. What it models, from RM0383:
- sector erase by SNB, mass erase, KEYR lock;
- programming by PSIZE (1, 2, 4 or 8 bytes). There is no "erase first" refusal on this chip:
  the cell becomes old AND new and no flag is raised. The model stores exactly that, so a
  bootloader that skips the erase ends up with neither image (`f411-bug-no_erase` fails its
  baseline with "the device did not come back", where the F1 build fails with "refused");
- write protection, one nWRP bit per sector, in force from the last reset;
- option bytes through OPTCR and OPTSTRT. The firmware does not erase or program them, the
  chip does. One OPTSTRT is modelled as an erase of the option bytes and two programs (USER
  and RDP, then nWRP), each with its complement, so a cut can fall between them. Erased
  option bytes read as RDP level 1 at the next reset, and going back to level 0 mass-erases
  the main flash first.
Not modelled: PGPERR and PGAERR (the model does not see how wide a store was or where a
128-bit row ends), PCROP, RDP level 2.

Not verified on hardware: that a real F411 is left with erased option bytes when power fails
inside OPTSTRT. The sequence is the documented one (erase, then program), but how long the
window is and what the bytes look like in it is a guess until the Black Pill is on the bench.
It goes on the same list as the torn-shape calibration.

**The demo runs on both chips from one source.** What differs is in `common/chip_f103.h` and
`common/chip_f411.h`: the flash map (on the F411 each part gets its own sectors: bootloader
in sector 0, the two floor copies in sectors 1 and 2, the slots in sectors 5 and 6), erase and
program, and the option-byte mistake of `self_lock`. The F103 bootloaders were rebuilt from the
shared source; their code changed (inlining), their behaviour did not.

Measured on the F411 demo, 2026-10-11, Renode 1.17.0:
- correct build: 89 operations, 88/88 cuts at every distinct state, 260/260 torn states,
  47/47 new states after a second cut during recovery (177 more led to a state already tested);
- `f411-bug-no_erase`, `no_unlock`, `pop_after_switch`, `protected_slot`: fail the baseline;
- `f411-bug-consume_first`: 84 of 88 cuts fail.
`resume_copy` has no F411 build: an F4 can program a half-written cell again (a torn cell has
only lost bits the target also clears), so resuming a copy is correct there. That the same
source is a bug on one chip and fine on the other is the reason the chip's rules are modelled.
