# An external SPI NOR flash chip

2026-10-12

"Internal flash only" was a limit that leaves out a common design: the new image waits in
an SPI NOR chip beside the microcontroller, and often some metadata does too.

**The chip model is C#, not Python.** A Renode Python peripheral sits on the system bus; an
SPI device does not. Renode compiles C# at run time (`include @file.cs`), checked on the
portable Windows build, so `models/BpSpiNor.cs` is loaded that way and attached to the SPI
controller the adapter names, with its chip select on a GPIO. It implements the 25-series
commands in single-line mode with three address bytes. Its own first test, by hand through
the monitor: JEDEC ID, write enable, a program read back, a sector erase.

**One count for both memories.** The model reads and writes the same state words the
internal flash model uses (operation count, cut point, cut flag, trace switch, in bpState)
and appends to the same trace file. So operations of the two memories are numbered in the
order they happen, "cut at operation N" needs no notion of which memory N is on, and the
planner, the torn states and the cuts during recovery work on the pair with no special case.

**In the image the chip comes last:** internal flash, option bytes, external chip. Its bytes
have no bus address, so they get a name (0xA0000000 by default) that traces, staging slots
and oracle images use. Its contents are loaded, saved and compared through files, by methods
of the model: reading a megabyte back through the monitor as text would take minutes.

**What an operation is.** A page program is one operation however many bytes it carries (up
to a 256-byte page, wrapping inside the page as the chip does), and it ANDs into what is
there. An erase says how much it took (4, 32, 64 KB or the chip), since that depends on the
command. Nothing happens without a write enable first. Torn shapes are the same as for the
internal flash, over the bytes of the operation.

**Time.** From the Winbond W25Q16JV datasheet (read 2026-10-12): page program 0.4 ms typical,
3 ms at most; 4 KB sector erase 45 / 400 ms; 32 KB block 120 / 1600 ms; 64 KB block
150 / 2000 ms; chip erase 5 / 25 s; at least 100,000 program-erase cycles per sector. The
time is skipped as for the internal flash, so the busy bit never reads as set. Wear is judged
against each memory's own endurance.

**Demo.** `f411-ext`: the staged image and the rollback floor are in the chip. The floor's
magic goes in with a program of its own, after the rest of the record, so a page program cut
short cannot leave a record that looks complete. `f411-ext-bug-consume_first` marks the staged
image used (a page program in the chip) before copying it.

Not modelled: quad and dual modes, four address bytes, the protection bits of the status
register, suspend and resume, and any external memory that is not SPI NOR. (The protection bits came
on 2026-10-13, below.)
