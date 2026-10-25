# What a run covers

**Clean cuts.** A golden run traces every flash operation of the update. After a power loss
only flash is left, so two cuts that leave the same flash are the same test: BrickProof cuts
only at distinct flash states and tells you how many there are and how many it covered.
`plan: every` cuts all of them. `plan: phases` cuts all of them in short phases and samples
long ones, and the report says which phases were sampled.

**Torn operations** (`--torn`). Power can fail inside an erase or a program. BrickProof also
boots the device from those states: an erase with only some bits flipped, a cell with only
some bits written. The shapes follow what flash cells do, but they are a model until compared
with real hardware, so they are counted on their own line.

**Cuts during recovery** (`--depth 2`). Recovery writes flash too. BrickProof traces it and
cuts again. A flash state already tested is skipped. `--depth 3` and beyond go on cutting
during the recovery from those, and `--depth exhaustive` until a level finds no flash state
not already tested (or the state limit, 2,000 by default, is reached).

**Bad update content** (`scenario.content_faults`). Not a power cut: the image itself is
wrong. BrickProof stages damaged versions of the update (truncated at several lengths, one
bit flipped in each region the adapter names, such as header, body and signature, erased, or
images made elsewhere: another key, an older version) and the bootloader must refuse each
one and keep the old image running, as the oracle sees it from outside.

**Worn pages** (`flash.worn`). A page past its endurance programs badly: the chip reports
success and the data read back is not what was written. BrickProof models one worn range:
programs there leave bit 0 of each cell as it was. A bootloader that writes an image there
and does not read it back cannot tell.

**Bit errors at rest** (`scenario.bit_errors`). A stored image loses a bit while the device
is off. BrickProof flips seeded random bits in the installed image and powers up: the CPU must
not run the damaged image, nor end in a fault handler. Staying in the bootloader is right.

**A broken link** (`scenario.link_cuts`). For updates sent over a protocol, the link breaks
part-way through the host's session while the device keeps its power: only the first N
bytes arrive. After a pause the host starts again, and the device must take the new
session and end up running.

**Flash storage libraries.** The built-in `storage` driver tests a key-value store or a file
system instead of a bootloader: every value a finished write left must be there after a cut,
nothing half-written may come back, and the store must still take and keep a new write
([adapters/zephyr_storage](../../adapters/zephyr_storage)).

**The chip's rules.** A plain emulator is more forgiving than silicon. BrickProof gives the
emulated chip its real RAM and flash sizes, faults on memory that is not there, refuses to
program a cell that is not erased or a store of the wrong width, ignores a store made while
programming mode is off, enforces write protection, and models the option bytes.
Erases and programs take the time the datasheet gives them (a 128 KB sector erase is a second
during which the CPU stands still), so watchdogs and timeouts behave as on the board.
`flash.timing: max` in the adapter uses the slowest figures the datasheet allows. A reset
the firmware or a watchdog causes reboots the device as on the chip, and a hardware watchdog
set in the option bytes runs from reset.

**External flash.** Many products keep the new image in an SPI NOR flash chip next to the
microcontroller. BrickProof models that chip too: its page programs and erases are cut,
torn and traced together with those of the internal flash, in the order they really happen
(`external_flash` in the adapter, `brickproof demo f411-ext`).

**What the update costs the flash.** Each run reports how long the chip spends erasing and
programming, and which page or sector is erased most often per update, set against the
endurance the datasheet promises.

**An outside judge.** The verdict does not rest on what the firmware says about itself. An
oracle checks that the bytes installed are exactly an approved image and that the CPU is
running inside it, not in a fault handler, and that it keeps running without a reset for a
second more: a device stuck in a boot loop is not recovered. `runs v2` at the end of a line
is its finding.

**A check on itself.** After every cut, the emulated flash is compared byte for byte with
what the golden run predicts for that point. If they differ, the run stops.

To see what an update does to flash, and what a run would cut, without cutting anything:

```bash
brickproof trace examples/demo_ab_bootloader/f103/adapter.yaml
```

```
op 0          erase         1 ops    1 states  cut all   0x0801E400                 spare rollback-floor page
ops 1-6       program       6 ops    5 states  cut all   0x0801E400 .. 0x0801E40A   new floor record
op 7          erase         1 ops    1 states  cut all   0x08002000                 Slot A
ops 8-157     program     150 ops  150 states  cut all   0x08002200 .. 0x0800232A   app body
ops 158-165   program       8 ops    8 states  cut all   0x08002000 .. 0x0800200E   header, last
ops 166-167   program       2 ops    2 states  cut all   0x08010000 .. 0x08010002   mark the staged image used
plan (every): 167 cut(s) over 167 distinct flash states (168 operations): every state is cut
```

(The notes on the right are added here; the tool prints the rest.)
