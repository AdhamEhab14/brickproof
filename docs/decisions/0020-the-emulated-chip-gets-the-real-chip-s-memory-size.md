# The emulated chip gets the real chip's memory sizes

2026-10-10

Renode's stock STM32F103 has 256 MB of RAM and a 512 MB flash region. The real F103RB has
20 KB and 128 KB. The Three-Tier bootloader's bench test showed what that costs: a jump to
the app that popped from the new stack, one word past the end of RAM, bus-faulted on the
board and ran fine in the emulator. Three power-cut bugs were found by emulation; this one
was found by hardware, only because the emulated chip was too generous.

So:
- `ram.size` is a required adapter field (`flash.size` already was).
- The engine appends `sram: size:` and `flash: size:` to the run's platform file. The stock
  flash region starts at 0 (boot alias), so its size is set to end where the real flash ends.
- At start-up the session reads both sizes back from Renode and refuses to run on a mismatch
  (exit 3). A platform quietly ignoring the override would otherwise make every result
  describe a different device.

General rule this adds: any place the emulator is more forgiving than silicon is a place a
bug can hide. RAM size was one. Still open: unmapped reads return 0 in Renode, where silicon
bus-faults.
