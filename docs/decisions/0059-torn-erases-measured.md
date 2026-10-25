# Torn erases, measured

2026-10-14

The torn shapes were guesses until now. Measured on a Nucleo-F103RB with a small firmware
(running from RAM) that starts an operation and resets the chip a counted number of cycles
later (DWT, 125 ns), then reads what is left; every delay three times.

- **Erase** (22 ms when not stopped): stopped at once, 69% of the bytes were 0xFF and 4.5% of
  the old 0 bits were still 0; at 5 us 91% and 1.2%; at 15 us 97% and 0.35%; from 50 us the
  page was always fully erased. The bits still 0 were scattered over the whole page, nearly
  always one in a byte, and the same cells in every repeat. Their count fits each old 0 bit
  staying 0 on its own with one probability (4.5% predicts 31% of the bytes showing a 0;
  measured 31%). Never a half page, never a byte keeping its old value.
- **Program** (55 us): untouched up to 0.5 us, complete from 0.6 us; nothing in between.

So two shapes are added from the measurements, `erase-early` (each old 0 bit stays 0 with
probability 4.5%) and `erase-late` (0.35%). They are drawn after the old shapes from the
same seed, so the old shapes' bytes, and old reports' reproduce commands, do not change. The
guessed shapes stay: they are harder than anything seen, and passing them still means
something. What is not known: a reset stops the flash cleanly, a power loss lets the supply
sag. Whether the 22 ms after the first 50 us is the chip finishing what a reset cannot stop
needs a switch on the supply.
