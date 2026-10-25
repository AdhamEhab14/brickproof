# Torn flash writes on a real STM32F103

The firmware that measured what an STM32F103 leaves in flash when a page erase or a halfword
program is cut short. The `erase-early` and `erase-late` shapes in `src/brickproof/torn.py`
come from its results ([docs/decisions/0059](../../docs/decisions/0059-torn-erases-measured.md)).

It starts an erase (or a program), resets the chip a counted number of CPU cycles later
(DWT, 125 ns at the reset clock), reads back what is left and prints it. It sweeps the delay
over the first half millisecond of an erase in 5 us steps and the first 3 us of a program in
single cycles, three times each. Its place is kept in RAM that start-up does not clear, and
the code that starts the operation and resets runs from RAM, so the CPU keeps counting while
the flash is busy. It runs by itself in about 20 seconds.

Only the last two pages (0x0801F000 and 0x0801F800) are erased and written, about 300 times
in a run. The chip is rated for 10,000.

| File | What |
|---|---|
| `main.c`, `link.ld` | the firmware |
| `torn_f103.bin` | the build that made the results below (Ubuntu's arm-none-eabi-gcc) |
| `capture.py` | records what the board prints into `torn_results.txt` |
| `results/` | the runs on a Nucleo-F103RB, 2026-10-14: v1 (coarse, up to a full erase), v2 (this firmware) |

## Running it

```bash
arm-none-eabi-gcc -mcpu=cortex-m3 -mthumb -Os -nostdlib -ffreestanding -T link.ld main.c -lgcc -o torn_f103.elf
arm-none-eabi-objcopy -O binary torn_f103.elf torn_f103.bin
ST-LINK_CLI -c SWD -ME -P torn_f103.bin 0x08000000 -V
pip install pyserial
python capture.py COM5        # the board's ST-LINK virtual COM port
```

Then press the reset button. Lines scroll by until `DONE`. To turn the results into the
numbers `torn.py` uses:

```bash
python tools/torn_fit.py hardware/torn_f103/results/nucleo-f103rb-v2.txt
```

## What the lines mean

```
CAL erase_cycles=N program_cycles=N     an uncut erase and program, in 125 ns cycles
E <step> <delay> r<repeat> <bytes FF> <bits 1> <map> [H <bytes with 0..8 bits set> B <first 32 bytes>]
P <step> <delay> r<repeat> <value> <value read again>
```

The erased page was all zeros before, so every bit still 0 is one the erase had not reached.
The map has one character per 16 bytes of the 1 KB page: `#` all erased, `.` all still zero,
`x` mixed.

A reset stops the operation cleanly, which is close to but not the same as the supply
dropping. A switch on the supply (plan item 27) would measure that.
