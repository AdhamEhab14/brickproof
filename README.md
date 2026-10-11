# BrickProof

Pull the plug on your firmware update, in an emulator, at every flash operation, and check
that the device still comes back.

BrickProof runs your firmware in [Renode](https://renode.io), cuts power just before a flash
erase or program during an update, powers the device back up, and checks it recovered: some
valid image runs, the update was not lost, and an older image cannot sneak back in. It does
that for every flash operation you ask for, and tells you which ones brick the device.

**Status:** early development. The engine came out of the power-cut tests of
[Three-Tier-STM32-Secure-Bootloader](https://github.com/AdhamEhab14/Three-Tier-STM32-Secure-Bootloader),
where it found three real bugs. STM32F1 targets only for now.

## Quick start

You need Python 3.10+ and [Renode 1.17](https://github.com/renode/renode/releases)
(put `renode` on PATH or set `RENODE_PATH`). No toolchain and no board: the demo firmware is
committed prebuilt.

```bash
git clone https://github.com/AdhamEhab14/brickproof
cd brickproof
pip install -e .
brickproof run examples/demo_ab_bootloader/adapter.yaml
```

The demo is a small A/B bootloader updating its app from v1 to v2. BrickProof first checks
that the update works when nothing interrupts it, then cuts power at every flash state the
update goes through, one per line:

```
PASS baseline (no cut)   168 ops                       2.2s  runs v2
PASS op-0                op 0     erase 0x0801E400     1.8s  runs v2
PASS op-1                op 1     program 0x0801E400   1.7s  runs v2
...
```

Which operations get cut is not guesswork either. After a power loss only flash is left, so
two cuts that leave the same flash are the same test: BrickProof cuts only at distinct flash
states, and tells you how many there are and how many it covered. The demo is cut at every
one (`plan: every`). A long update can be cut at every state of its short phases and sampled
in its long ones (`plan: phases`), and the report says exactly which phases were sampled.

Power does not always fail between two operations. With `--torn` (or `torn: true` in the
adapter) BrickProof also boots the device from torn states: an erase with only some of its
bits flipped, a halfword with only some of its bits written. These shapes follow what flash
cells do but are a model, not a measurement, so they are reported on their own line.

Recovery writes flash too, and power can fail again while it does. With `--depth 2` (or
`depth: 2` in the adapter) BrickProof also cuts during the recovery from each first cut. A
flash state it has already tested is skipped, because the same flash is the same test.

The verdict does not rest on what the firmware says about itself. An oracle checks from
outside that the bytes installed are exactly an approved image and that the CPU is running
inside it, not sitting in a fault handler. `runs v2` at the end of a line is its finding.

Each cut lands just before the operation it names. BrickProof checks that itself: after every
cut it compares the emulated flash, byte for byte, with what the uninterrupted run predicts
for that point, and stops if they differ.

To see what an update does to flash, and what a run would cut, without cutting anything:

```bash
brickproof trace examples/demo_ab_bootloader/adapter.yaml
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

(The notes on the right are added here; the tool prints the rest.) Operation 0 erases a page
that is already erased, so cutting after it shows nothing new: 168 operations, 167 states.
`-o FILE` saves every operation as JSON lines.

Now run one of the bug builds. Each puts back a real bug, and BrickProof should catch it:

```bash
brickproof run examples/demo_ab_bootloader/bug-consume_first.yaml --fail-fast
```

| Bug build | The mistake | What a cut does |
|---|---|---|
| `bug-consume_first` | marks the staged image used before copying it | no valid image left: bricked |
| `bug-trust_header` | copies the header first and trusts it without a CRC | boots a half-copied image |
| `bug-naive_floor` | rewrites the anti-rollback floor in place, after the install | v1 can be installed again |
| `bug-pop_after_switch` | pops saved registers after switching to the app's stack | reads past the end of RAM: bus fault on every boot, no cut needed |
| `bug-no_erase` | copies the new image over the old one without erasing | the chip refuses to program cells that are not erased |
| `bug-no_unlock` | never unlocks the flash controller | the chip ignores every write: the update silently does nothing |
| `bug-resume_copy` | after an interrupted install, skips the erase and writes only what is missing | survives all 167 clean cuts; a torn state leaves a half-written cell the chip will not program again |
| `bug-retry_limit` | gives up on an update after two interrupted attempts | survives any single cut, clean or torn; two cuts in a row leave no image |

The last three are not power-loss bugs. They are mistakes a plain emulator lets through and a
real chip does not, so they fail before any cut is made. The stack one was found by a real
board in another bootloader after the emulator had passed it, because emulated RAM was far
bigger than the chip's. BrickProof gives the emulated chip its real memory sizes, treats any
access outside them as a fault, and makes flash behave like flash: a cell that is not erased
cannot be programmed, and a write with the controller locked does nothing.

Exit codes: `0` every cut recovered, `1` at least one failed, `2` adapter error, `3` BrickProof
itself failed (including its own flash self-check). `--json FILE` writes the results for CI.

## Testing your own firmware

Write an adapter: one YAML file that says what to load, the real flash and RAM sizes of the chip,
which images are approved (the `oracle` section), and where to cut.
If your bootloader applies an image waiting in a staging slot on the next boot (MCUboot's
overwrite mode, most OTA designs), the built-in `staged_slot` driver does the rest, and the
demo's [adapter.yaml](examples/demo_ab_bootloader/adapter.yaml) is the template. If the update
is started over a protocol (UART, CAN, UDS), add a small `driver.py`, like the one for the
Three-Tier bootloader in [adapters/three_tier_f103](adapters/three_tier_f103).

## Layout

| Path | What |
|---|---|
| `src/brickproof/engine/` | Renode driver in lock-step virtual time, work-folder setup |
| `src/brickproof/models/` | Flash controller models that count operations and cut power (STM32F1 so far) |
| `src/brickproof/platforms/` | Base Renode platforms the models plug into |
| `src/brickproof/plan.py` | The cut planner: distinct flash states, exhaustive or sampled |
| `src/brickproof/torn.py` | Torn states: an erase or a program left half done |
| `src/brickproof/oracle.py` | The outside judge: approved image installed, and really running |
| `src/brickproof/trace.py` | The golden-run trace: phases, replay to any operation |
| `src/brickproof/drivers/` | Built-in drivers (`staged_slot`) |
| `examples/demo_ab_bootloader/` | The demo firmware, its source, prebuilt files and adapters |
| `adapters/` | Adapters for real projects (Three-Tier bootloader) |
| `docs/decisions.md` | Why things are the way they are |

## Licence

Apache-2.0, see [LICENSE](LICENSE).
