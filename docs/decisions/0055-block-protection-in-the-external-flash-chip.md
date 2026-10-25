# Block protection in the external flash chip

2026-10-13

The SPI NOR model let firmware erase and program anywhere. A real chip with block protection
set ignores those commands, silently: no error bit, the data just stays. Firmware that sets
protection at the factory and forgets to clear it before an update passes a plain emulator
and fails on every device.

**Model.** Status register 1 (BP0-2, TB, SEC) and register 2 (CMP), read with 05h and 35h,
written with 01h (one or two bytes) and 31h after a write enable, from the Winbond W25Q16JV
datasheet's protection tables (read 2026-10-13): BP = 0 protects nothing and BP = 11x
everything; with SEC = 0, BP = 001 protects the top 64 KB (the bottom with TB) and each step
doubles it; with SEC = 1 the steps are 4, 8, 16 and 32 KB; CMP protects the complement. The
64 KB step is the 16 and 32 Mbit parts'; it is a constructor argument (`protectUnit`). A
command that touches a protected byte is ignored, as on the chip, and a chip erase is ignored
if any part is protected.

**A refusal is counted, traced and fails the run**, the same way the internal flash's write
protection does (the same two state words, a `W` line in the trace), with a message that names
the status register rather than the option bytes.

**The status registers are part of the flash image.** They are non-volatile: a power cut
leaves them as they were. So an image is now the flash, the option bytes, the external chip,
and its two status registers, and every cut starts from the registers it should. Writing the
status register is not an operation of its own (it is not counted or cut).

**Adapter.** `external_flash.status` gives the registers as the device ships (register 1, or
both as 0xSSRR), so a board that leaves the factory protected is tested as it is.

Not modelled: the /WP pin and the SRP/SRL bits (the pin is taken as high, so the register can
always be written), the volatile status register writes (50h), and the individual block locks
(WPS = 1). 4-byte addressing is left out on purpose: it matters only above 16 MB, and an image
holds the whole chip.
