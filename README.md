# BrickProof

Pull the plug on your firmware update, in an emulator, at every point where it matters, and
check that the device still comes back.

BrickProof runs your firmware in [Renode](https://renode.io), cuts power during an update,
powers the device back up, and checks that it recovered: an approved image is installed, it is
really running, the update was not lost, and an older image cannot sneak back in. It tells you
which cuts brick the device, and how to reproduce each one.

It came out of the power-cut tests of
[Three-Tier-STM32-Secure-Bootloader](https://github.com/AdhamEhab14/Three-Tier-STM32-Secure-Bootloader),
where it found three real bugs. Supported chips: STM32F1 and STM32F4 (F411).

## Quick start

You need Python 3.10+ and [Renode 1.17](https://github.com/renode/renode/releases) (put
`renode` on PATH or set `RENODE_PATH`). No toolchain, no board, no firmware of your own: a demo
comes with the package.

```bash
git clone https://github.com/AdhamEhab14/brickproof
cd brickproof
pip install .
brickproof demo
```

The demo is a small A/B bootloader updating its app from v1 to v2. BrickProof first checks
that the update works when nothing interrupts it, then cuts power at every flash state the
update goes through, one per line:

```
PASS baseline (no cut)   168 ops                       2.2s  runs v2
PASS op-0                op 0     erase 0x0801E400     1.8s  runs v2
PASS op-1                op 1     program 0x0801E400   1.7s  runs v2
...
167/167 cuts recovered
coverage: 167 cut(s) over 167 distinct flash states (168 operations): every state is cut
```

Now run a build with a known bug. BrickProof should catch it:

```bash
brickproof demo self_lock --fail-fast
```

`brickproof demo --list` shows all of them:

| Build | The mistake | What happens |
|---|---|---|
| `consume_first` | marks the staged image used before copying it | a cut leaves no valid image: bricked |
| `trust_header` | copies the header first and trusts it without a CRC | boots a half-copied image |
| `naive_floor` | rewrites the anti-rollback floor in place, after the install | an older image can be installed again |
| `pop_after_switch` | pops saved registers after switching to the app's stack | reads past the end of RAM: bus fault on every boot |
| `no_erase` | copies the new image over the old one without erasing | the chip refuses to program cells that are not erased |
| `no_unlock` | never unlocks the flash controller | the chip ignores every write: the update silently does nothing |
| `early_unpg` | stores every second cell after programming mode is off again | the chip ignores those stores: half the image is never written |
| `protected_slot` | (a device setting) the app slot is write-protected | the chip refuses every erase and program there |
| `resume_copy` | after an interrupted install, skips the erase and writes only what is missing | survives every clean cut; a torn write leaves a cell the chip will not program again |
| `retry_limit` | gives up on an update after two interrupted attempts | survives any single cut; two cuts in a row lose the update |
| `self_lock` | write-protects its own flash from the bootloader, in the field | a cut while the option bytes are erased, and the retry mass-erases the flash |

The first three are the bugs BrickProof found in the Three-Tier bootloader. `pop_after_switch`
was found by a real board after an emulator had passed it. The rest are mistakes a plain
emulator lets through and a chip does not.

The demo also builds for an **STM32F411**, a chip that differs from the F103 in everything a
power cut touches: an erase wipes a whole sector of 16 to 128 KB, a program writes a word and
is never refused (the cell ends up as old AND new), and the chip rewrites its own option
bytes. `brickproof demo f411` runs the correct build, and `brickproof demo f411-bug-no_erase`
and the other `f411-bug-*` builds have the same mistakes. `resume_copy` is missing there on
purpose: an F4 does let a half-written cell be programmed again, so it is not a bug on that chip.
It has one of its own instead, `f411-bug-watchdog`: on a device with a hardware watchdog, a
sector erase that takes a second gets the chip reset half way through, on every attempt.
`watchdog` and `f411-watchdog` are the correct build on such a device, and `hold_pg` and
`f411-hold_pg` are the correct build writing flash the other common way, with programming
mode left on over a whole run of cells.

## What a run covers

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
cuts again. A flash state already tested is skipped.

**The chip's rules.** A plain emulator is more forgiving than silicon. BrickProof gives the
emulated chip its real RAM and flash sizes, faults on memory that is not there, refuses to
program a cell that is not erased or a store of the wrong width, ignores a store made while
programming mode is off, enforces write protection, and models the option bytes.
Erases and programs take the time the datasheet gives them (a 128 KB sector erase is a second
during which the CPU stands still), so watchdogs and timeouts behave as on the board.
`flash.timing: max` in the adapter uses the slowest figures the datasheet allows. A reset
the firmware or a watchdog causes reboots the device as on the chip, and a hardware watchdog
set in the option bytes runs from reset.

**What the update costs the flash.** Each run reports how long the chip spends erasing and
programming, and which page or sector is erased most often per update, set against the
endurance the datasheet promises.

**An outside judge.** The verdict does not rest on what the firmware says about itself. An
oracle checks that the bytes installed are exactly an approved image and that the CPU is
running inside it, not in a fault handler. `runs v2` at the end of a line is its finding.

**A check on itself.** After every cut, the emulated flash is compared byte for byte with
what the golden run predicts for that point. If they differ, the run stops.

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

(The notes on the right are added here; the tool prints the rest.)

## Options

| Option | What it does |
|---|---|
| `--plan every` / `--plan phases` | cut every distinct flash state, or sample long phases |
| `--torn` | also boot from torn erases and programs |
| `--depth 2` | also cut during the recovery from each first cut |
| `-j N` / `-j auto` | run N emulators side by side; the results do not depend on N |
| `--real-every N` | on a long update, make every Nth cut in the emulator and compute the rest |
| `--cut N` | run one operation alone, to reproduce a result |
| `--fail-fast` | stop at the first failure |
| `--json`, `--junit`, `--html FILE` | reports |

The HTML report is one self-contained page: the verdict, what was covered and what was
sampled, each failure with a command that reproduces it, the SHA-256 of every firmware file
tested, and where the evidence fits in UN R156 and the EU Cyber Resilience Act
([how that map is made](docs/regulations.md)).

Exit codes: `0` every cut recovered, `1` at least one failed, `2` adapter error, `3` BrickProof
itself failed (including its own flash self-check).

## Testing your own firmware

Write an adapter: one YAML file that says what to load, the real flash and RAM sizes of the
chip, what is write-protected, which images are approved (the `oracle` section), and how to
plan the cuts.

If your bootloader applies an image waiting in a staging slot on the next boot (MCUboot's
overwrite mode, most OTA designs), the built-in `staged_slot` driver does the rest, and the
demo's [adapter.yaml](examples/demo_ab_bootloader/adapter.yaml) is the template. If the update
is started over a protocol (UART, CAN, UDS), add a small `driver.py`, like the one for the
Three-Tier bootloader in [adapters/three_tier_f103](adapters/three_tier_f103). Every key is explained in
[docs/adapter.md](docs/adapter.md).

```bash
brickproof run my_adapter.yaml --torn --depth 2 -j auto --html report.html
```

## In CI

```yaml
- uses: AdhamEhab14/brickproof@v0.1.0
  with:
    adapter: test/brickproof.yaml
    args: --torn --depth 2 -j 3
```

The job fails if any cut does not recover, and the JSON, JUnit and HTML reports are uploaded
as an artifact.

## Docker

```bash
docker run --rm ghcr.io/adhamehab14/brickproof              # the demo
docker run --rm -v "$PWD:/work" ghcr.io/adhamehab14/brickproof run adapter.yaml --html report.html
```

## Layout

| Path | What |
|---|---|
| `src/brickproof/engine/` | Renode driver in lock-step virtual time, work-folder setup |
| `src/brickproof/models/` | The flash controller model (operation counting, cuts, the chip's rules, option bytes) and the memory guard |
| `src/brickproof/platforms/` | Base Renode platforms the models plug into |
| `src/brickproof/trace.py` | The golden-run trace: phases, replay to any operation |
| `src/brickproof/plan.py` | The cut planner: distinct flash states, exhaustive or sampled |
| `src/brickproof/torn.py` | Torn states: an erase or a program left half done |
| `src/brickproof/oracle.py` | The outside judge: approved image installed, and really running |
| `src/brickproof/runner.py`, `pool.py` | A campaign: baseline, cuts, torn states, depth, over one or many emulators |
| `src/brickproof/report.py`, `regulations.py` | JUnit and HTML reports, and the regulation map |
| `src/brickproof/drivers/` | Built-in drivers (`staged_slot`) |
| `examples/demo_ab_bootloader/` | The demo firmware, its source, prebuilt files and adapters |
| `adapters/` | Adapters for real projects (Three-Tier bootloader) |
| `docs/decisions.md` | Why things are the way they are, with the measurements behind them |

## Limits

- The device is emulated. Torn-operation shapes are a model until compared with hardware.
- Flash is modelled for STM32F1 (pages, halfword programming) and STM32F411 (sectors, byte
  to double-word programming). Another family needs a model of its flash controller in
  `src/brickproof/models/`; the engine itself no longer assumes either chip.
- Flash timing uses datasheet figures (typical or slowest), not measurements, and does not
  vary with temperature, voltage or age. Wear is counted per update, not simulated.
- Not modelled: low-power modes, so the two option bits that decide whether entering one
  resets the chip have no effect.

## Licence

Apache-2.0, see [LICENSE](LICENSE).
