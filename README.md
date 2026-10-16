# BrickProof

Pull the plug on your firmware update, in an emulator, at every point where it matters, and
check that the device still comes back.

BrickProof runs your firmware in [Renode](https://renode.io), cuts power during an update,
powers the device back up, and checks that it recovered: an approved image is installed, it is
really running, the update was not lost, and an older image cannot sneak back in. It tells you
which cuts brick the device, and how to reproduce each one.

It came out of the power-cut tests of
[Three-Tier-STM32-Secure-Bootloader](https://github.com/AdhamEhab14/Three-Tier-STM32-Secure-Bootloader),
where it found three real bugs. That bootloader's fixed release has since been cut at every one
of the 12,109 distinct flash states of its self-update, with no failure. Supported chips: STM32F1, STM32F4 (F411) and Nordic nRF52840.

Run on bootloaders that are not ours, it found:

- **OpenBLT** (STM32F1): a cut near the end of a programming session can leave a program
  that the bootloader starts although it is not completely written. Confirmed on a real
  Nucleo-F103RB. Details and the adapter: [adapters/openblt_f103](adapters/openblt_f103).
- **wolfBoot** (STM32F411): with partitions of one sector, as in its own Black Pill example,
  the last step of an update erases the bootloader itself. Confirmed in wolfBoot's own
  simulator: [wolfSSL/wolfBoot#937](https://github.com/wolfSSL/wolfBoot/issues/937). Details
  and the adapter: [adapters/wolfboot_f411](adapters/wolfboot_f411).

It also ran on **MCUboot**, on two boards with two upgrade modes: the STM32F411 Black Pill
(one-sector slots, swap with scratch, 57 cuts) and the nRF52840 DK (swap with move, 156
cuts). No failure on either.
[adapters/mcuboot](adapters/mcuboot).

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

And for an **nRF52840**, which has no flash keys at all: one register (CONFIG) says whether a
store is a program, whether an erase is allowed, or neither. `brickproof demo nrf52` and the
`nrf52-bug-*` builds have the mistakes that apply there (`early_unpg` becomes a store made
with CONFIG back to read-only). It has one of its own, `nrf52-bug-nwrite`: progress kept by
clearing one more bit of the same word after each step. An STM32F4 takes that; the nRF52
promises only two writes to a word between erases.

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

**Bad update content** (`scenario.content_faults`). Not a power cut: the image itself is
wrong. BrickProof stages damaged versions of the update (truncated at several lengths, one
bit flipped in each region the adapter names, such as header, body and signature, erased, or
images made elsewhere: another key, an older version) and the bootloader must refuse each
one and keep the old image running, as the oracle sees it from outside.

**A broken link** (`scenario.link_cuts`). For updates sent over a protocol, the link breaks
part-way through the host's session while the device keeps its power: only the first N
bytes arrive. After a pause the host starts again, and the device must take the new
session and end up running.

**Flash storage libraries.** The built-in `storage` driver tests a key-value store or a file
system instead of a bootloader: every value a finished write left must be there after a cut,
nothing half-written may come back, and the store must still take and keep a new write
([adapters/zephyr_storage](adapters/zephyr_storage)).

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
| `--shard K/N` | run every Nth cut, starting with the Kth: splits a long campaign over N machines |
| `--cut N` | run one operation alone, to reproduce a result |
| `--fail-fast` | stop at the first failure |
| `--json`, `--junit`, `--html FILE` | reports |

The HTML report is one self-contained page: the verdict, what was covered and what was
sampled, each failure with a command that reproduces it and one that exports its flash
for a real board, the SHA-256 of every firmware file
tested, and where the evidence fits in UN R156 and the EU Cyber Resilience Act
([how that map is made](docs/regulations.md)).

To check a failure on a real board, export the flash that cut leaves and program it:

```bash
brickproof export my_adapter.yaml --cut 3232 -o op-3232.bin        # add --torn KIND for a torn state
```

It writes `op-3232.bin` (the chip's flash; option bytes and an external flash chip get files
of their own) and `op-3232.txt` with the ST-LINK or nrfjprog commands. The bytes are the ones
the run powered the emulator up from.

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
- uses: AdhamEhab14/brickproof@v0.2.0
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
| `src/brickproof/export.py` | A cut's flash as files for a real board |
| `src/brickproof/drivers/` | Built-in drivers (`staged_slot`) |
| `examples/demo_ab_bootloader/` | The demo firmware, its source, prebuilt files and adapters |
| `adapters/` | Adapters for real projects (Three-Tier bootloader, OpenBLT, wolfBoot, MCUboot) |
| `hardware/torn_f103/`, `tools/torn_fit.py` | The firmware that measured torn writes on a real STM32F103, its results, and the tool that turns them into `torn.py`'s numbers |
| `docs/decisions.md` | Why things are the way they are, with the measurements behind them |

## Limits

- The device is emulated. Two of the torn erase shapes are measured on a real STM32F103,
  with the erase stopped by a reset; the others, and every torn program, are models. A real
  power loss, which lets the supply sag, is not measured yet.
- Flash is modelled for STM32F1 (pages, halfword programming), STM32F411 (sectors, byte
  to double-word programming) and nRF52840 (4 KB pages, word programming, at most two
  writes to a word between erases). Another family needs a model of its flash controller in
  `src/brickproof/models/`; the engine itself does not assume any of them.
- Flash timing uses datasheet figures (typical or slowest), not measurements, and does not
  vary with temperature, voltage or age. Wear is counted per update, not simulated.
- An external flash chip is modelled as SPI NOR with the 25-series commands in single-line
  mode. Quad mode, four-byte addressing and other kinds of external memory are not.
- Not modelled: low-power modes, so the two option bits that decide whether entering one
  resets the chip have no effect.

## Licence

Apache-2.0, see [LICENSE](LICENSE).
