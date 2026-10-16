# Decisions

One entry per design choice, newest last, so a later session knows why things are the way they are.

## 2026-10-09: Name and package

The project is called BrickProof and the command is `brickproof`, but the PyPI name `brickproof`
belongs to an unrelated Databricks testing tool (v0.0.11). We publish as **`brickproof-fw`**.
GitHub: `AdhamEhab14/brickproof`.

## 2026-10-09: Licence: Apache-2.0

Permissive like MIT, so companies can adopt it without legal review friction, plus an explicit
patent grant, which automotive and IoT companies care about. The ported harness code came from
the MIT-licensed Three-Tier bootloader repo, written by the same author.

## 2026-10-09: Port the harness, don't rewrite it

`engine/session.py` is the bootloader's `tests/renode/renode_session.py` with the target-specific
parts moved into the adapter: ELF names, the held B1 button (now `reset:` monitor commands),
the flash geometry, and the repo root. The flash model is the bootloader's `models/flash.py`
unchanged apart from its header comment.

## 2026-10-09: Flash geometry by text rewrite

Renode's Python peripherals take no parameters. The engine copies each flash model into the run's
work folder and rewrites its `PAGE`, `FLASH_BASE` and `FLASH_SIZE` lines. A unit test fails if a
model loses one of those lines.

## 2026-10-09: Everything Renode loads goes into a work folder

The Renode monitor breaks on paths with spaces (`D:\Embedded projects\...`). Each run copies the
firmware into a temp folder and starts Renode there, so monitor commands only see relative,
space-free paths. Paths inside the `.repl` file are quoted strings and may contain spaces.

## 2026-10-09: Adapter = YAML + driver.py

The YAML holds data (geometry, firmware, reset commands, cut list). The driver holds the target's
update protocol: `prepare()` stages the update once, `start_update()` triggers it, `alive()` and
`check_recovered()` judge the result. The driver may use the target's own host tools: for the
Three-Tier bootloader it imports `host/bl_host.py` and `host/sign_tool.py`, so the firmware
gets exactly the bytes the real host would send.

## 2026-10-09: Every cut starts from the same image

After `prepare()` the engine dumps flash once. Each cut restores that image and power-cycles
before starting the update, so cuts are independent and can later run in parallel instances.

## 2026-10-09: W1 cuts are real cuts only

Cut positions are either `on_erase: <page>` or `at_op: N` (operation N counted from the start of
the update). No generated or torn states yet; those come with the cut planner (W3).

The W1 cut list stays inside the SBL phase on purpose. A cut *before* the SBL starts (ops 0 to 6:
the Boot Manager state page) should leave the old FBL running, but the driver's
`check_recovered()` asks for the new one (Slot B wiped). "Old or new image, both fine" is the
oracle's job (W4, invariant I1), not the driver's.

## 2026-10-09: Liveness is still judged by the driver (temporary)

`alive()` = the bootloader answers GET_VER. That is target code judging the target, which is the
circularity the independent oracle (W4) has to remove. Accepted for W1 only.

## 2026-10-09: W1 speed measurement (the kill-criterion number)

Local run, Windows 11, Renode 1.17.0, Three-Tier FBL self-update, 5 real cuts:
setup 26 s (boot, stage, one flash dump), then 42 to 70 s per cut, 272 s total.
Most of a cut is the Boot Manager redoing the 40 KB copy in emulation.

The update has about 11,900 flash operations (7 before the SBL, 40 erases, 11,848 halfword
programs). Cutting at every one at ~45 s each would take about 150 hours, far over the 2 h
budget in the risk table. So "every op" cannot be brute force. Options for W3, in the order
we will try them:
1. Equivalence classes: inside a uniform loop (the copy) the post-cut states differ only in
   how many halfwords landed; cut real at the loop's edges plus a sample, and use generated
   states (cheap to inject) for the rest.
2. Parallel Renode instances (cuts are already independent).
3. Move the flash model to C# so Renode snapshots work and restore is instant.

## 2026-10-10: A bundled demo target comes before the W2 tracer (roadmap change)

A new user should not have to clone and build someone else's bootloader to see the tool work.
`examples/demo_ab_bootloader` is a small A/B bootloader (under 1 KB) and app, committed
prebuilt, so `pip install` plus one command runs it with no toolchain and no board. Three
build options put back the three real bugs BrickProof found in the Three-Tier bootloader,
in the form they would take in an A/B design, so the demo shows a catch, not only a pass.
It also gives every later feature (tracer, planner, oracle) a second target from day one, so
none of them gets shaped around one bootloader by accident.

The Three-Tier bootloader stays as the real-world target and its own CI job.

## 2026-10-10: Built-in `staged_slot` driver

Most bootloaders apply an image that waits in a staging slot on the next boot (MCUboot
overwrite mode, most OTA designs). For those, the driver needs no target code: put the image
in the slot, reset, read what booted from the UART. Options are regexes (`alive`, `expect`)
and an optional rollback probe (stage an older image after recovering; it must not run).
Targets with a protocol-started update still write a `driver.py`.

## 2026-10-10: A reset re-initialises the flash model

Measured: after `machine Reset` the Python flash model's op counter is 0 and its cut point is
cleared. So for a boot-time update the engine resets with the machine paused (`settle=0`),
arms the cut, then lets it run. A driver says it needs this with `update_on_boot = True`.

## 2026-10-10: Flash starts erased (0xFF)

Renode's flash memory starts as 0x00; real erased flash reads 0xFF. The session now fills
flash with 0xFF before loading firmware. Firmware that checks "is this slot empty" would
otherwise see a state that cannot exist on silicon.

## 2026-10-10: Range cuts and exit codes

`at_ops: {from, to, step}` expands to one cut per operation. Op counts are deterministic, so
the first cut that never fires ends its range (SKIP), and the rest are not run. Exit codes
separate "found a problem" (1) from "the tool broke" (3), so CI can expect a bug build to fail
without a crash looking like a catch.

## 2026-10-10: Demo speed

About 6 s per cut on the demo (vs 45 s on Three-Tier, whose recovery redoes a 40 KB copy).
Most of it is per-command monitor round trips, not emulation: one cut is about 30 monitor
commands plus three boots. Worth profiling before the planner work, because it multiplies
every campaign.

## 2026-10-10: A locked-up CPU is a failed cut, not a crash

Found by the `trust_header` bug build: a cut at op 15 leaves a valid-looking header over an
erased body, the bootloader jumps to 0xFFFFFFFF, and the core faults while fetching its fault
vector. Renode's virtual time then stops advancing, so `RunFor` never returns, and BrickProof
died with a socket timeout (exit 3). On silicon this is a locked-up, dead device.

Now `run_for` has a wall-clock limit (60 s + 120 x the virtual seconds asked for). Past it,
the session raises `MachineHung`, the runner marks the cut FAIL ("the device locked up"),
restarts Renode in place (same session object, so drivers keep working) and moves on.
Cost: about 2 minutes per hung cut. Fine while hangs are rare; revisit if a target hangs a lot.

## 2026-10-10: Demo results (local, Windows 11, Renode 1.17.0)

| Build | Result | First failing cut |
|---|---|---|
| correct | 168/168 cuts recovered, 18 min | none |
| `bug-consume_first` | caught | op 7: floor already raised to 2, staged v2 marked used, v1 refused: no bootable image |
| `bug-trust_header` | caught | op 15: half-written header trusted, CPU locks up |
| `bug-naive_floor` | caught | op 158: floor page erased, not yet rewritten; v1 accepted again |

168 is exactly the count the code predicts: floor record 7, Slot A erase 1, body 150,
header 8, consume 2.

## 2026-10-10: Where a cut's time goes (profiled)

Each `emulation RunFor` costs about 100 ms of wall time however short it is, plus about 37 ms
of UART polling after it. So the cost of a cut is the number of RunFor calls, not the amount
of emulated time. The demo made about 43 per cut; 40 of them were the rollback probe waiting
its whole 2 s timeout, in 0.05 s steps, for a banner that must not appear.

Fix: the probe waits for any image to announce itself, then checks which one it was.
Demo cut: 6.5 s -> about 1.9 s. Rule for new drivers: never wait for the absence of something
in small steps; wait for a positive event, then inspect.

Still to do: the one-off 128 KB flash dump (`sysbus ReadBytes`) takes 4.8 s of setup.

## 2026-10-10: The emulated chip gets the real chip's memory sizes

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

## 2026-10-10: Real RAM size was not enough: memory guards

Experiment: the demo bootloader with the bench bug put back (`ldmia sp!, {r4, lr}` right
after `msr msp`, the same instruction the other bootloader had) boots its app with 256 MB of
RAM, and ALSO with the real 20 KB. Renode answers a read of unmapped memory with 0 and
carries on. Silicon bus-faults. So shrinking RAM is necessary but does not catch the bug.

Fix: every range that does not exist on the chip gets a `mem_guard` Python peripheral
(F103: end of RAM up to 0x22000000, end of flash up to 0x1FFF0000). Any access stops the CPU
and latches the address and PC in the flash model's test registers (0x118, 0x11C). The runner
reads the latch before each reset (a reset clears it) and fails the run with
"bus fault: the firmware touched 0x20005000 (PC 0x080000C4)".

Limits, stated plainly:
- Stopping the CPU is not what silicon does (it takes the BusFault/HardFault vector). Firmware
  that recovers from bus faults on purpose would be judged wrongly. None of our targets does.
- Only the holes next to RAM and flash are guarded. A peripheral that Renode does not model
  is NOT a hole (it exists on the chip), so it is not guarded.

## 2026-10-10: Baseline run before any cut

The run now starts with the same update left to finish (`baseline (no cut)`), judged like a
cut. If it fails, no cuts are run and the exit code is 1. Reasons: a broken update makes
every cut result meaningless, and a bug that needs no power cut (like the stack one, which
faults on every boot) has to be reported somewhere. It also prints the update's operation
count. New scenario field `update_time`: virtual seconds an uninterrupted update needs.

Demo bug builds are now four: three power-loss bugs BrickProof found, plus
`bug-pop_after_switch`, the one a board found first.

## 2026-10-10: Three-Tier adapter follows v2.0.0, and CI pins the tag

The bootloader's `main` moved to v2.0.0 a day after the adapter was written, and CI checked
out `main`: the adapter's 1.6.0 test FBL was refused, no cut ever fired, and the e2e job sat
in timeouts. CI now checks out the `v2.0.0` tag, and the adapter signs its FBL as 2.1.0.
Moving to a newer bootloader release is a deliberate adapter change, not something a push
to another repo does to us.

Run against v2.0.0 with real RAM and the memory guards: baseline + 5/5 cuts, no bus fault.
The baseline's operation count is blank for this target: the bootloader resets itself after
the update, which resets the flash model's counter.

## 2026-10-10: Flash model state lives in memory, not in script variables

A firmware reset re-runs the Python model's `IsInit` and wiped its op count, cut point and
fault latch. For a bootloader that resets itself mid-update that meant: the baseline's op
count read 0, and a cut could not land after the reset. The test registers (0x100 to 0x124)
are now backed by a small `bpState` memory at 0x90000000, which Renode keeps across a reset.
`power_cycle()` clears them on purpose. The hardware registers (CR, keys) still reset, as on
the chip.

## 2026-10-10: Golden-run tracer

With the trace register set, the flash model appends every operation to a file: `E addr`,
`P addr value`. An erase knows its address. A program does not: the CPU writes the halfword
straight into flash memory, so when PG is cleared the model compares flash with a shadow copy
to find what changed (the page being filled first, then every page by fingerprint, which is
native code). A program that writes what is already there changes nothing; its address is
then inferred as "the next halfword" and marked `inferred`.

Cost: demo 168 ops in 1 s. Three-Tier FBL self-update 20,527 ops in 33 s (434 s before the
fingerprints). Note the count: the SBL copies the whole 40 KB region, padding included, so
the update is 20,527 operations, not the 11,900 estimated on 2026-10-09 from the image size.

`brickproof trace adapter.yaml` prints the update as phases (runs of operations walking
forward through flash). The demo is six: erase the spare floor page, write the floor record,
erase Slot A, copy the body, copy the header, clear the staged magic. Phases are the
equivalence classes the cut planner will sample from.

Limit: an operation is counted when PG goes from 0 to 1. Firmware that keeps PG set across
several halfwords would have them counted as one. Both targets clear PG each time (so does
ST's HAL).

## 2026-10-10: A program cut used to land AFTER its halfword. Now it lands before.

Found when the trace put addresses on cut results. The model halts the CPU when PG is set,
but Renode finishes the instruction block it is in, and the store of the halfword is in that
block. Measured on the demo: 17 of 17 program cuts had already written their halfword.

Why it matters: an erase cut stops before the erase. So with program cuts landing after, the
state "page erased, nothing programmed yet" was never tested, and every result was labelled
one operation early.

Fix: after a program cut fires, the runner looks up the operation in the golden run. If the
halfword is in flash, it writes back the value that was there before (`trace.value_before`).
Every cut now means exactly "just before op N". The state after the last operation is the
baseline's.

Correction to the entry "Demo results" above: `bug-naive_floor` was said to fail at op 158
because "the floor page was erased, not yet rewritten". Wrong. In that build ops 151 to 158
copy the header, 159 and 160 clear the staged magic, and the floor page is erased at 161.
The cut "at 158" had landed after the last header halfword: install complete, floor still
at 1, so v1 is accepted again. Same bug, wrong description, and the reason was this landing
problem.

## 2026-10-10: Every cut is checked against the golden run replayed

From the image before the update plus the trace, `trace.Replay` computes the exact flash just
before any operation. After each cut (and after the baseline) the runner compares real
emulated flash with it, on every page the update touches. A difference raises
`SelfCheckFailed` and ends the run with exit 3: either the tool is wrong (trace, rewind,
cut model) or the update differs from run to run, and in both cases the results could not be
trusted. `scenario.check_states: false` turns it off for an update that is not deterministic
(a random nonce written to flash, for example).

This is the "generated state must equal a real cut, byte for byte" cross-check from the
original harness, done for every cut instead of one hand-picked case. It also means the
replay can later stand in for a real cut where that is cheaper.

## 2026-10-10: The flash model enforces the chip's programming rules

Audit question: where else is the emulator more forgiving than silicon? Flash. Renode's flash
is plain memory, and the CPU writes into it directly:
- program a halfword that is not erased: silicon refuses (PGERR, cell unchanged, unless the
  value is 0x0000); Renode stores it.
- store into flash with PG clear or the controller locked: silicon ignores it; Renode stores it.

So "forgot to erase" and "forgot to unlock" pass in a plain emulator and brick a board.

The model now keeps a shadow copy of flash in a hidden memory (`bpShadow`) that only real
operations update. When PG is cleared it finds the halfword(s) written by comparing flash with
the shadow, and applies the rule: a refused program gets its old value written back and PGERR
set in SR, like the chip, and is counted. Any other difference between flash and shadow is a
write with no operation behind it; an audit register reports the first such address.

The runner reads both at the same points as the bus-fault latch and fails the run:
- `flash rule broken: 4 program(s) over cells that were not erased, first at 0x0800224E`
- `flash changed at 0x08002004 with no flash operation behind it`

The engine has to declare its own writes (image load, restore, rewind) with a resync, or they
would look like stray writes.

Costs measured in the model: whole-flash compare 0.8 ms, the usual one-halfword check 26 us.

Side effects that are improvements:
- firmware that keeps PG set across several sequential halfwords now has each one found,
  counted and traced (was: one operation);
- the trace no longer needs its own shadow; it logs what the rule check already found.

Two more demo bug builds prove the rules: `bug-no_erase` and `bug-no_unlock`, both caught at
the baseline. The Three-Tier bootloader v2.0.0 passes with enforcement on: no refused program,
no stray write, on the update path and on the recovery paths of its five cuts.

Not modelled, stated plainly: write protection (WRP option bytes), read protection, the option
bytes themselves, flash timing (every operation is instant), and wear.

## 2026-10-10: The runner is tested without an emulator

`runner.campaign()` (baseline, cuts, rewind, self-check, skip and fail-fast rules, lock-up
handling) is separate from `run()` (start Renode, stage the update). `tests/fake_device.py`
is a simulated device with the session's interface and a tiny correct updater that can be
broken on purpose (no recovery, bus fault, lock-up, different writes on the second run).
17 tests in `tests/test_runner.py` run in a fraction of a second, on Python 3.10, 3.12 and
3.13 (new `compat` CI job).

Removed `tests/test_three_tier_e2e.py`: it was skipped by default, CI never ran it, and it had
drifted from the code. The CI `e2e` job runs the same thing through the CLI.

## 2026-10-10: Renode charges per monitor line, so commands share lines

Profiled again after the flash checks pushed a demo cut from 1.9 s to 3.9 s. Measured:
every monitor line costs 40 to 60 ms in Renode whatever it holds (a RAM write, `version`,
a register read), sending many lines in one socket write changes nothing, but several
commands on ONE line separated by `;` cost about the same as one (8 writes: 77 ms, not 500).
Reading memory back as text is slow on top of that: 128 ms per KB.

So:
- `cmd_batch` joins commands with `;` (40 per line). A power cycle is one line instead of ten.
  UART injection, which is two commands per byte, gains the most.
- status is read in groups: `cut_status()`, `violations()`, `run_until_cut()` (run and check
  in one line).
- the per-cut self-check no longer reads pages back. The expected image is loaded into a
  hidden memory (`bpExpect`, a file load is fast) and the flash model compares natively. It
  now covers the whole flash, not only the pages the update touches, and is quicker.

Demo cut: 3.9 s -> 1.7 s with every check on (whole-flash compare, rule enforcement, audit).
What is left is mostly emulation itself (`RunFor`, about 0.28 s per boot with the model's
per-access overhead) plus the one-off flash dump at setup (about 7 s).

## 2026-10-11: The oracle

Until now "did it recover?" was answered by the driver: a UART banner, a version reply. That
is the firmware vouching for the firmware. `oracle.py` judges from outside, using nothing
the firmware says, and shares no code with any target:

- **what is installed:** the bytes in flash are exactly one of the approved images (compared
  inside the flash model, so it costs one monitor line whatever the image size);
- **what is running:** the PC, sampled several times, stays inside that image, and the core's
  exception number is not a fault (2 to 6: NMI, HardFault, MemManage, BusFault, UsageFault).

An adapter lists the approved images and which of them a scenario accepts after a cut
(`accept: [v2]` = the update must not be lost; `[old, new]` = either is fine). A driver can
add images it creates at run time with `oracle_images()`.

A verdict now needs three voices to agree: the chip rules (bus fault, refused program, stray
write), the oracle, and the driver. The oracle is asked twice: after recovery, and again
after the driver's checks, because a rollback probe stages an older image and reboots.

What it caught on its first day:
- `bug-trust_header`, cuts at ops 163 to 165 (the last three halfwords of the body): the app
  boots and prints "APP v2", so the driver said PASS. The oracle: "no approved image is
  installed at 0x08002000: the closest is v2, and flash differs from it at 0x08002326".
  These three cuts were false passes before.
- A mistake of its own: the Three-Tier test update is the old FBL plus 16 bytes, so the old
  image matched the new one on its own length and every result said `old_fbl`. When several
  images match, the longest is the one really there. Covered by a test.

It also let the Three-Tier adapter drop its "Slot B must be wiped" check, which was only true
after the SBL had started, and add cuts at ops 0 to 6 (the Boot Manager's state page). There
the device keeps the old FBL and runs it; from op 7 on the Boot Manager completes the update
and the new FBL runs. 12 cuts, all pass, and each line says which image it ended on.

Limits:
- The oracle is consulted after the driver says the device is up. The driver is still what
  decides "booting has finished". A target with a slow recovery needs that wait.
- "Running inside the image, not in a fault handler" is evidence of life, not proof of
  correct behaviour. A firmware stuck in its own `while(1)` in thread mode passes it; that is
  what the driver's own signs of life are for.
- Without an `oracle:` section a run still works, and the CLI says the verdicts then rest on
  the driver alone.

## 2026-10-11: A session never leaves its emulator behind

Found two idle `renode.exe` from the day before: probe scripts whose start-up had failed (a
platform Renode rejected). The constructor raised before anything could call `close()`, so
the process stayed. The handoff had warned that leftovers slow later runs.

Now: start-up is wrapped, and any failure closes the session before the error goes up.
`close()` is safe at any point and more than once. Every live session is in a weak set that
an `atexit` hook closes, for scripts that die without cleaning up. Tested with a stand-in
process, no emulator needed.

## 2026-10-11: The cut planner

Hand-picked cuts were the weakest part of a result: 12 cuts of a 20,527-operation update, with
no account of what the other 20,515 would have shown. `plan.py` chooses cuts from the golden
run and says what they cover.

**The exact part.** When power is lost, RAM and the CPU state go with it; only flash remains.
So two cuts that leave the same flash are the same test. The planner replays the trace and
keeps only operations that begin a new flash state: an erase of an already-erased page, or a
program of the value already there, adds none. Three-Tier FBL self-update: 20,527 operations,
11,874 distinct states. (13 of the 40 page erases hit pages that were already erased, and
8,640 programs write 0xFFFF over erased flash.) Demo: 168 operations, 167 states.

**The judgement part.** `plan: every` cuts at every distinct state: exhaustive for a single
power loss at operation boundaries. `plan: phases` does that only in short phases (12 states
or fewer). In a long one it takes the two operations at each end plus `per_phase` evenly
spaced samples, on the argument that recovery treats "k halfwords copied" alike for most k.
That is a judgement, not a proof, so the plan table says per phase whether it was "cut all"
or "N sampled", the summary says how many states exist against how many were cut, and the
JSON report carries the same under `coverage`. A result must not claim more than was run.

Demo: `plan: every`, 167 cuts. Three-Tier: `{mode: phases, per_phase: 4}`, 23 cuts (all 7
states of the Boot Manager's state page, 8 of the 27 erase states, 8 of the 11,840 copy
states). `--plan every` on Three-Tier would be 11,874 cuts, about three days at 22 s each on
one emulator; that needs parallel instances, which the design allows (cuts are independent)
but is not built yet.

Listed cuts still work and run first; a planned cut at the same operation is not repeated.

## 2026-10-11: Torn operations

A clean cut falls between two operations. A real one can fall inside one. `torn.py` builds
the states that leaves, following what flash cells do:
- an erase moves bits 0 to 1; cut short, some of the page's 0 bits have flipped, the 1 bits
  stay 1;
- a program moves bits 1 to 0; cut short, some of the bits due to become 0 have.

Which bits get there first is not knowable from here, so each torn operation is tried as a
few shapes that obey those rules: for an erase, half the page done, a random scatter, almost
all done (one byte in 64 still old); for a program, only the low byte's bits, only the high
byte's, a random subset. Shapes equal to the state before or after the operation are dropped
(those are the clean cuts), so a program with a single bit to clear has no torn state.
Seeded, so a run is repeatable.

A torn state is built, not provoked: the flash before the operation comes from replaying the
golden run (the same replay every real cut is checked against), the half-done operation is
applied to that image, and the device is powered up from it. No update run is needed, so a
torn state costs less than a clean cut.

They matter more with the flash rules enforced: a half-programmed cell is not erased, so
recovery code that writes to it again without erasing first is refused, as on the chip.

Honesty about what this is: the shapes are a model. Until the hardware rig has compared them
with real interrupted operations on a real STM32, a pass means "survives these plausible
shapes". Results are labelled `torn` and counted on their own line, never mixed into the
clean-cut count.

Use: `scenario.torn: true` (or a list of shapes) in the adapter, or `--torn`. Torn states
are made for each operation a clean cut was placed in front of, after all clean cuts.

Proof that torn states earn their place, measured 2026-10-11 with a seventh demo bug build,
`bug-resume_copy` ("resume instead of restart": after an interrupted install, skip the erase
and write only the halfwords still missing):
- clean cuts only, `plan: every`: 167/167 pass. A clean-cut tool calls it safe.
- with torn states: fails at `op-7 erase-half`. Half of Slot A still holds the old image, the
  resume path programs over it, and the chip refuses (`flash rule broken ... 0x0800224E`).
It takes the torn states and the flash rules together to see it.

Three-Tier v2.0.0 with torn states: 23/23 clean cuts and 59/59 torn states pass.

CI: the correct demo build and the Three-Tier run use `--torn`; `adapter.yaml` itself does
not turn it on, so a first local run stays short.

## 2026-10-11: Cuts during recovery (depth)

One cut followed by an undisturbed recovery is not the whole story: recovery writes flash
too, and power can fail again while it does. `runner.explore()` goes level by level:

1. a state a cut left behind is powered up and its recovery is traced, like an update;
2. cuts are planned over that trace with the same planner;
3. each gives a flash state (the parent's flash with the recovery replayed to that point);
4. a state already tested, at any level, is skipped: the same flash is the same test;
5. each new state is powered up and judged, and becomes a parent for the next level.

Two things keep this honest and affordable:
- **The first new cut of every recovery is made for real** in the emulator, and the computed
  state is checked against it byte for byte (`SelfCheckFailed` otherwise). The rest are
  powered up from the computed state directly, which skips re-running the recovery up to the
  cut. That is sound for the same reason the planner's reduction is: only flash survives.
- **Known states are skipped.** A bootloader that recovers by simply starting the update
  again lands, when cut a second time, on states a first cut already produced.

Limits, stated plainly:
- Parents are chosen with the depth plan (`phases`, 2 samples per long phase by default), not
  from every first-cut state, or the count would be the square of the update's length.
- The state space need not be finite. The demo's floor record carries a sequence number that
  grows with every install attempt, so every extra level finds new states. `levels` bounds
  the depth (default 2) and `max_states` the count (default 2000); a run that hits the cap
  says so.
- Torn states are not explored deeper.

Use: `scenario.depth: 2` (or a mapping with `levels`, `mode`, `per_phase`, `small`,
`max_states`), or `--depth 2`. Results are named by lineage, `op-7 > op-58`, and counted on
their own line.

Proof that depth earns its place, measured 2026-10-11 with an eighth demo bug build,
`bug-retry_limit` (give up on an update after two interrupted attempts, a common way to stop
boot loops):
- one cut, `plan: every` plus torn states: 168/168 clean cuts and 489/489 torn states pass;
- `depth: 2`: fails at `op-1 > op-1`. The first cut leaves attempt one recorded, the recovery
  records attempt two, a second cut right there makes the next boot give up, and the update
  is lost for good (`the installed image is v1; this scenario accepts only v2`).

## 2026-10-11: Depth 2 on the Three-Tier bootloader (measured)

`depth: {levels: 2, per_phase: 0, small: 4}` on v2.0.0, local run: 23/23 clean cuts, then
13/13 new states after a second cut during the Boot Manager's recovery; 119 more second cuts
led to a state a first cut had already produced. The recovery mostly retraces the update's
own steps, which is why interrupting it again is safe. 14 minutes in all. CI, correct demo
build with `--torn --depth 2`: 167/167 clean cuts, 485/485 torn states, 95/95 deeper states
(324 known).

## 2026-10-11: Reports and reproducing one result

A run has to leave evidence someone else can read and check.
- `--junit FILE`: one test case per result, class name by kind (baseline, cut, torn, depth-N),
  coverage and firmware hashes as properties. A failure carries its reason, where it cut and
  a command to reproduce it.
- `--html FILE`: one self-contained page (no outside resources, light and dark): verdict,
  a tile per kind, failures first with a reproduce command each, what was covered and what
  was sampled, how to read it and what is not modelled, the SHA-256 of every firmware file
  tested, then every run.
- Both are built from the same dictionary as the JSON report (`runner.as_dict`), so the three
  cannot disagree. It now also carries the start time, the tool version and the input hashes.
- `--cut N` (repeatable) runs only those operations and ignores the adapter's plan, torn and
  depth settings unless given again on the command line. It is what a report's reproduce
  command uses: `brickproof run adapter.yaml --cut 159`.

Left out on purpose: a mapping of results to regulation clauses (UN R156, CRA). The handoff
asks for one, with the clause wording verified first. Until someone has checked that wording
against the published texts, a report states what was tested and what was not, and no more.

## 2026-10-11: What the lock-up really is, and noticing it sooner

Single-stepped the `trust_header` lock-up. The bootloader does `bx` to 0xFFFFFFFF, read from
an erased vector. Renode takes that value as an exception-return code, pops a frame from a
stack pointer that is 0xFFFFFFFC, gets zeros from memory that is not there, and lands at PC 0
with the Thumb bit clear. From there `RunFor` never returns, and Renode logs nothing. On the
chip the same jump is a fault taken while fetching the fault vector: a true lock-up. So
"the device locked up" is the right verdict; only the way of noticing is ours.

Tried and dropped: a block of "branch to self" at the top of memory, so the core would spin
with time passing. It is never reached, because of the exception-return path above.

Kept: the wall-clock limit on a slice of emulated time now follows the machine. It is twenty
times the slowest rate this session has measured (starting from a pessimistic guess), never
under 30 s and never over the old fixed allowance. A healthy slice takes a second or two, so
30 s cannot call a slow but live device dead; that would be a false failure and is worse than
waiting. A locked-up demo cut now costs 54 s instead of 114 s.

## 2026-10-11: Renode's shared command history was most of the cost of everything

Trying to start eight emulators at once crashed them: Renode saves its monitor command
history after every command, by rewriting the whole file, and by default that file is one per
user (`%APPDATA%\renode\history`, `~/.config/renode/history`). Two Renodes writing it collide.

It was also the "fixed 40 to 60 ms per monitor line" measured the day before. The file had
grown to 25 MB (670,000 lines) and was rewritten for every command, which is why the cost
crept from 60 to 100 ms as this project ran. Measured with 20 `version` commands:
shared history 67 ms per line, own history file 1.6 ms.

Each session now writes a `renode.config` with `history-path` in its own work folder and
starts Renode with `--config`. (`--config` alone, or redirecting `APPDATA`, does not move the
history: the path is a setting inside the config file.)

Effect on one emulator, full demo, every clean cut: 580 s -> 181 s.

## 2026-10-11: Several emulators (`--jobs`)

Cuts are independent, each starts by restoring flash, so they can be shared out. `pool.py`
hands out work by index and releases results strictly in item order, so the tests run, their
order in the output and the place where `--fail-fast` stops are the same for any number of
emulators. Tested: one against four simulated devices give identical results for clean cuts,
torn states, depth, depth with torn, listed cuts and fail-fast.

- ports: `free_port()` never hands the same port out twice in a process;
- Renode processes start one at a time until their monitor answers, then work in parallel;
- a driver that signs its update at run time shares the prepared state with the other
  emulators (`export_state` / `import_state`), so all of them start the same update;
- depth exploration runs each level in three steps (trace all parents in parallel, decide in
  parent order which states are new, test those in parallel) to stay deterministic;
- `Golden.replay` is one per thread.

Full demo with `--torn --depth 2 -j 8`: 201 s for 747 runs, same counts as one emulator.

Torn states can now also be explored at depth (`depth: {torn: true}`): the half-done versions
of each recovery operation.

## 2026-10-11: `real_every`: most planned cuts from the computed state

On a long update most of a cut's time is running the update up to the cut. Every cut made in
the emulator has its flash compared with the golden run replayed to that point, and they have
always matched. So with `plan: {real_every: N}` (or `--real-every N`) only every Nth planned
cut, plus the last, is made in the emulator; the others are powered up from the replayed
state. The real ones keep the check running through the whole campaign, and the report says
how many of each there were. A listed cut with an `expect` is always made for real.

## 2026-10-11: Each emulator gets its own temp folder; start-up is one at a time

With twelve emulators, Renode died at `LoadPlatformDescription` with "Access is denied" from
its temporary-files manager. Not a race between starting processes (it happened with starts
serialised): Renode keeps `renode-<pid>` folders in the temp directory and, on start-up,
looks up the process of every one it finds. Thirty `renode-<pid>-crash` folders were lying
there from Renodes killed earlier in this work, and Windows had reused some of those pids for
protected processes, whose look-up is refused.

- every session starts Renode with `TMP`/`TEMP`/`TMPDIR` pointing into its own work folder,
  so it sees no other instance's leftovers, and its own go when the work folder is removed;
- Renodes are brought up one at a time (the whole machine creation, not only the process
  start), and a failed start is tried again, three times in all;
- the leftovers in the shared temp folder were removed.

Twelve emulators then start and run the Three-Tier target (setup 77 s).

## 2026-10-11: Write protection and option bytes

Another place where plain emulated flash is more forgiving than the chip: a page the option
bytes write-protect can be erased and programmed in Renode. On an STM32F1 it cannot.

**Model.** The option bytes are 16 real bytes at 0x1FFFF800 (RDP, USER, Data0/1, WRP0..3, each
with its complement). As on the chip, they are loaded into `FLASH_WRPR` and `FLASH_OBR` at
reset, so a change takes effect after the next reset. An erase or a program in a protected
unit is refused with WRPRTERR, changes nothing, and is counted; the run fails with
`write protection: N ... operation(s) ... were refused, first at 0x...`. A mass erase is
refused if anything is protected. Read protection also write-protects the first unit.

**Adapter.** `flash.write_protected: [{from, size}]` and `flash.read_protected` say what the
option bytes hold when a test starts. Ranges must fit the chip's protection units (4 KB on
the F103). The demo ships with its bootloader's 8 KB locked, the Three-Tier adapter with the
Boot Manager's 16 KB locked, as deployed.

**Option bytes can be reprogrammed, and a cut can fall there.** `OPTKEYR`, `OPTER` and `OPTPG`
are implemented, and those operations are counted, traced and cut like any other. To make
that work the option bytes are part of the flash image: an image is the flash followed by the
16 bytes, so dump, restore, replay, the per-cut self-check and the planner all cover them
(`trace.locate` is the one place that maps an address into an image).

**The hazard this exposes, and models.** Reprogramming option bytes means erasing all of them
first. Erased, the RDP byte reads as "read protection on" at the next reset. If power fails
between the erase and the rewrite, the chip boots protected, and when firmware then writes the
unprotected value, the chip removes protection the only way it can: by mass-erasing the main
flash. The model does that mass erase when RDP is written to 0xA5 while protection was loaded
at reset. `bug-self_lock` (the demo locking its own pages from the bootloader) is caught by it:
cut at op 1, the device never comes back. `bug-protected_slot` (the app slot protected by
mistake) is caught at the baseline.

A fix along the way: the rewind of a program cut compared the cell with the traced value.
An option byte is traced as the chip stores it (byte plus complement), but at the moment of
the cut the cell holds what was written. It now compares with the value before the operation.

Not modelled: the USER and Data option bytes have no effect; option byte error (OPTERR) for a
bad complement is not raised.

## 2026-10-11: Regulation map, and how BrickProof is handed to someone else

**Regulation map.** A report now says where its evidence fits in UN R156 (7.2.1.1, 7.2.2.1.1,
7.2.2.1.2) and the Cyber Resilience Act (Annex I, Part I (2)(f) and (2)(h), Part II (7)). The
clause wording was read from the UNECE consolidated text and the Official Journal on
2026-10-11; the summaries are paraphrases with links, and `docs/regulations.md` gives the
sources. Per clause a run is marked shown, not shown or not tested, worked out from the run:
a failing run shows nothing, the integrity clauses need the oracle, and the power check of
7.2.2.1.2 is outside what a run can show. It is headed "a map, not a verdict", because whether
a regulation is met is not a tool's call.

**The demo is in the package.** `examples/demo_ab_bootloader` is also the package
`brickproof.demo` (setuptools `package-dir`), so `pip install` brings it and `brickproof demo`
runs with nothing else to fetch. Checked by installing the wheel into a clean environment.

**Three ways in, each built and used in CI:** the wheel and sdist (`package` job: builds
both, installs the wheel clean, rebuilds a wheel from the sdist and compares the file lists),
the GitHub Action (`action.yml`, composite; the `action` job uses it as another repository
would; inputs reach the script through the environment, not by being pasted in), and the
Docker image (`docker` job builds it, runs the demo inside, and checks a bug build exits 1).

**Release.** A `v*` tag builds, checks the tag matches the package version, creates the GitHub
release from the changelog section, and pushes the image to GHCR. The PyPI upload uses trusted
publishing and stays off until the repository variable `PYPI_PUBLISH` is `true`, because the
PyPI side has to be set up once by the account that owns the project (`docs/releasing.md`).

## 2026-10-11: A second chip family (STM32F411), and what it took

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

## 2026-10-11: Flash operations take time, and an update's wear is counted

**Timing.** Until now an erase or a program took no time at all in the emulator. On the chip
a page erase is 20 to 40 ms and a 128 KB sector erase is one to two seconds, and for all of
it the CPU stands still: it runs from flash, and flash cannot be read while it is being
erased or programmed. Anything that counts time through that (a watchdog, a timeout, a
tick-based retry) sees it on the board and did not see it here.

The flash models now skip that much virtual time when an operation starts (`cpu.SkipTime`,
measured: an erase made to cost 30 ms moved the next operation 30.09 ms later). The CPU
executes nothing in between, which is what the stall is. Skipping costs almost no host time,
unlike a busy loop on BSY, which would call into the Python model hundreds of thousands of
times per erase. BSY therefore never reads as set: by the time the firmware can look, the
operation is over. For code running from RAM that is a simplification (it could do other
work while BSY is set); for the wait loop every such driver has, it is the same thing.

Figures, from the datasheets (read 2026-10-11):
- STM32F103x8/xB, DS5319 table 28: 16-bit program 40 / 52.5 / 70 us (min / typ / max), page
  erase and mass erase 20 to 40 ms. No typical erase time is given; 30 ms is used.
- STM32F411xC/xE: word program 16 us typical, 100 max. Sector erase depends on the sector
  and on PSIZE; at 32 bits: 16 KB 250 / 500 ms, 64 KB 550 / 1100 ms, 128 KB 1 / 2 s
  (typ / max); slower at 16 and 8 bits. Mass erase 4 / 8 s.
- Rewriting the F4 option bytes has no figure. It is taken as one 16 KB erase. A guess.

`flash.timing` in the adapter picks `typical` (the default), `max` (the slowest the datasheet
allows, the one to use when the question is whether a watchdog survives) or `none`.

Checked against the one real measurement there is: the Three-Tier self-update takes "about
2 s" on the Nucleo board. The trace adds up to 2.3 s of flash time with typical figures
(40 erases, 20,480 programs). Same order, slightly high, as expected from a typical erase
time that is a midpoint and not a measurement.

What it found straight away: the F411 demo set PSIZE only when programming, so its first
erase ran at the reset value (8 bits) and took 400 ms where 250 would do. Fixed in the demo.
And adapters had time limits that only held because operations were free: the F411 demo's
`update_time: 0.5` is less than its two sector erases. The limits were raised, and a failed
baseline now says so when the flash operations alone take longer than `update_time`.

What it costs: a run now covers more virtual time, because a recovery that copies 40 KB
really is two seconds long. The Three-Tier adapter asked "are you alive?" once, 1.5 s after
power-up, which was after the recovery when flash was instant and is in the middle of it
now, so every cut in the copy failed in CI. The driver now asks up to four times. To keep
the extra virtual time from turning into round trips to the emulator, the three waits that
polled in fixed 10 to 50 ms steps (for a cut, for a boot banner, for a serial reply) now
double their step while nothing happens. Measured on one Three-Tier cut: 71 `RunFor` calls
for 9.3 virtual seconds. Saving up the 53 us skips of single programs and skipping a
millisecond at a time was tried and made no measurable difference, so it was dropped.

**Wear.** Each run reports the page or sector erased most often in one update, and what that
means against the endurance the datasheet promises (10,000 cycles on both chips). It is a
count from the golden trace, not a model of cells ageing: it tells you that a bootloader
erasing its metadata page six times per update will wear that page out six times sooner.

**Not modelled, still.** Cells do not get slower or weaker with use, and nothing here varies
with temperature or supply voltage.

## 2026-10-12: Resets the firmware causes now reboot it, and the hardware watchdog

**A reset made inside the emulator left the device dead.** Found while modelling the
watchdog. When the engine resets the machine it also sets the CPU's vector table to the
flash base, because Renode's Cortex-M starts with it at address 0, where an STM32 has its
flash aliased and Renode's platforms have nothing. A reset the emulator makes by itself (a
watchdog, a firmware reset request) got no such follow-up. Measured on both chips with a
bootloader that sits in its "no image" loop under a hardware watchdog: after the first
reset, vector table 0x00000000, PC 0xEFFFFFFE (locked up), no second boot banner.

Fix: Renode runs a per-machine `reset` macro after every machine reset. The session now
defines it (vector table, then the adapter's `reset:` lines). Same test afterwards: the
banner repeats every 0.4 s on the F103 and every 0.5 s on the F411.

What this had been hiding: the Three-Tier self-update ends with the firmware resetting
itself, and what the Boot Manager does after that reset never ran. The golden trace went
from 20,527 operations to 20,574: the state page is rewritten (one erase, six programs) and
Slot B is erased (40 pages). Those 47 operations are now part of the trace and get cut like
the rest. Every earlier Three-Tier result, including the exhaustive run, covers the update up
to that reset and not the tail after it.

**The hardware watchdog.** The USER option byte's WDG_SW bit is now honoured. With it cleared
(`flash.hardware_watchdog: true`), a handler on the machine's reset event starts the
independent watchdog after every reset, before the first instruction, as the chip does.
Renode's own watchdog model does the counting; the F103 platform gets one (the stock file has
none, 40 kHz LSI), the F411's is the stock one (32 kHz). Checked by stopping the CPU right
after reset: 3 watchdog resets in 1.5 s on the F103, 2 on the F411, none with the option off.
A reset while the power is "off" after a cut does not wake the device: a halted CPU stays
halted across a machine reset (checked: no flash change, no operation, no banner in 1.5 s).

OBR on the F1 now shows the USER and Data bytes as loaded at reset, where it used to read
as all ones.

Together with flash timing this makes a classic visible. The demo is now watchdog-aware (the
app and the bootloader feed it, and the bootloader gives it its longest timeout before
erasing). `f411-bug-watchdog` leaves that last step out: a 128 KB sector erase takes a
second, the watchdog waits half a second, the chip stands still for the erase and is reset
in the middle of it, and the next boot starts the same erase again. It fails the baseline.
`watchdog` and `f411-watchdog` are the correct build on a device with a hardware watchdog
and must pass every cut. The F103 has no bug build for this: its page erases are a tenth of
the watchdog's timeout.

The Three-Tier adapter used to map plain memory over the watchdog's registers. It now gets
the real one. The bootloader passes with it.

Not modelled: the other two USER bits (nRST_STOP, nRST_STDBY: whether entering a low-power
mode resets the chip), because Renode does not model those modes for these chips. And a
reset in the middle of an erase leaves the erase finished here, where the chip would leave
the sector half erased; the torn states cover that shape, but only at the cuts, not at a
watchdog reset.

## 2026-10-12: The flash models hear each program store

**What was wrong.** A program is a store by the CPU straight into Renode's flash memory,
and a Python peripheral does not see it. The models therefore worked backwards: when PG
was cleared they compared flash with their shadow copy and took what differed as what had
been programmed, looking first at the cell after the last one. To allow for firmware that
leaves PG set over a few cells, a difference right after the expected cell was accepted too.

That allowance was a hole. Firmware that programs one halfword properly and stores the next
one after clearing PG leaves exactly that pattern, and the F103 model accepted the stray
store as a program. On the chip that store is ignored and half the image is never written.
Checked with a build that does this (`bug-early_unpg`): the old F103 model passed its
baseline, "runs v2". A false pass, the worst kind of mistake for this tool. (The old F4
model happened to catch it, through a different path.)

The same guesswork had two smaller costs: a program that wrote the value already there had
its address inferred, and a cut could not fall between two stores made under one PG.

**What it does now.** Renode can report every memory access of a CPU to a hook
(`SetHookAtMemoryAccess`). Hearing all of them would be far too slow, so the model turns it
on when PG is set and off when it is cleared. One detail makes it work: the store usually
sits in the same translated block as the write to CR, and a block already translated has
no hook in it. `RequestTranslationBlockRestart` ends the block after the CR write, and the
store is then translated with the hook. Measured on the demo: 172 stores reported for 172
programs, each with its address, width and value.

The hook is called after the store has landed, so the model applies the chip's rules there
and puts the old value back when the chip would not have written: the programming rule and
write protection as before, and now also the width (an F4 store that is not as wide as PSIZE
says sets PGPERR and writes nothing; an F1 programs halfwords only). A cut is the same move:
old value back, CPU halted, block ended. So a program cut lands exactly before its store
with no help from the runner, and it can land between two stores under one PG.

Whatever differs from the shadow at an audit was stored with PG clear. There is nothing left
to guess, and no inferred addresses: the Three-Tier trace used to have 8,640 of them.

A reset removes the hook (the machine's reset event), so a watchdog reset in the middle of
a program does not leave the CPU reporting every access for the rest of the run.

**Demo.** Two builds for each chip: `hold_pg` writes whole runs of cells under one PG and
must pass every cut, and `bug-early_unpg` is the mistake above and must fail its baseline.

## 2026-10-12: The tail of the Three-Tier update, and exhaustive runs off the laptop

**The tail.** The 47 operations after the firmware's own reset (state page rewritten, Slot B
erased), which the emulator never reached before the reset fix, were each cut on their own:
47/47 recovered, and 90/90 torn states of the same operations survived. Run locally with the
exact-program models, Renode 1.17.0, bootloader v2.0.0.

**The exhaustive run was stopped and is not a result.** The local run with `--plan every`
got to about 5,000 of 11,874 cuts with no failure, on 12 emulators, before it was stopped to
free the machine. It also predates the reset fix and the exact-program models, so it would
have covered the update only up to the reset, with the old models. Nothing is claimed from it.

**Shards.** Twelve emulators for most of a day is not something to ask of a laptop, so a
campaign can now be split: `--shard K/N` makes every Nth cut starting with the Kth. The list
of cuts is the same in the same order on every machine, so N shards make exactly the whole
campaign (tested). A shard's report says it is one, and its regulation map counts only the
cuts it made. `.github/workflows/exhaustive.yml` runs the Three-Tier campaign at every
distinct flash state over 20 runners, started by hand, and a last job adds the shards up
and fails if a cut failed or the shards do not make the whole.

## 2026-10-12: The Three-Tier self-update, cut at every distinct flash state

Run on GitHub's runners with the `exhaustive` workflow (run 38242798665), 20 shards,
`--plan every --real-every 25`, Renode 1.17.0, bootloader v2.0.0 with its test keys, BrickProof
at commit e6f8191. It took 2 h 46 min from start to the last shard.

- the update: 20,574 flash operations, 12,109 distinct flash states
- cuts: 12,109, one at every state. 520 were made in the emulator, each compared byte for
  byte with the state the golden run predicts; 11,589 were powered up from that computed state
- failed: 0. All 20 shards reported, and their cuts add up to the whole campaign

What this does and does not say. Every clean single power cut the update can meet leaves the
bootloader recovering to an approved image, in the emulator, with the chip rules modelled
here. Torn states and second cuts during recovery were not part of this run; CI covers those
on the planned sample (torn at every sampled cut, depth 2), and the tail after the reset was
done with torn states at every operation. Nothing here has been checked against the board.

The count of distinct states is higher than the 11,874 of earlier notes for two reasons: the
tail after the firmware's own reset is now part of the update, and the models no longer infer
the address of a program that wrote what was already there.

## 2026-10-12: Flash is also at address 0

Found the first time a bootloader that is not ours was run. An STM32 that boots from its main
flash shows that flash at address 0 as well as at 0x08000000, and some firmware uses the
low address: wolfBoot's STM32F4 port programs through it. The platforms had flash at one
address only. On the F411 nothing was mapped at 0, so those stores went nowhere, the flash
model saw erases and no programs, and the update could not work. On the F103 Renode's stock
file maps one huge memory from 0, so a store at 0x00002000 landed in different bytes from
0x08002000.

Now the flash memory is registered at both addresses (one memory, so a read, a store or an
instruction fetch at either address is the same byte), it has its real size on both chips,
and a store through the low address while PG is set is a program like any other. The gap
between the end of the alias and 0x08000000 is guarded like the other holes, where the F103
used to read zeros. Both demos give the same traces as before.

This is the kind of gap the demo and our own bootloader could never show, because both
were written by people who knew what the emulator had.

## 2026-10-12: An oracle for a bootloader and a program side by side

The oracle was written for one slot that holds the old image or the new one. A bootloader
that reprograms the application in place (no second slot) does not fit that: after a cut
there is no approved application at all, by design, and the right state is "the bootloader
is intact and running, waiting to be given the program again".

Images can now be approved at different addresses. At each address the installed one is
found as before (longest match). If more than one address has an approved image, the core
must be running inside one of those that the scenario accepts, and it may move from one to
the other between two looks, because a bootloader hands over. With a single address nothing
changes, messages included.

Two things the same outside project showed (both dealt with in the next entry):
- Emulated peripheral clocks do not follow the firmware's clock setup. Renode gives a timer
  a fixed input clock (10 MHz by default), so firmware that sets a prescaler for the 72 MHz
  it configured sees time run 7.2 times too slowly. An adapter can state the clock in its
  extra platform lines, which is what the Three-Tier adapter already does for its UARTs.
  The proper fix is for the RCC model to tell the peripherals.
- An input pin nobody drives reads low. Firmware that reads a button at start-up needs the
  adapter to set the pin (`reset:` lines).

## 2026-10-12: Clocks follow the firmware, pins have a level, a dead device is noticed

Three gaps the outside bootloaders showed, closed.

**Clocks.** Renode gives each timer a fixed input clock (10 MHz in its STM32 files) and its
RCC models do not tell anyone what the firmware configured. OpenBLT keeps time with TIM1
and a prescaler for the 72 MHz it sets up, so its 500 ms took 3.6 s. Both chips now have an
RCC model of ours that works the tree out from the registers (source, PLL, AHB and APB
prescalers, and the doubling of a timer clock on a divided bus) and sets the frequency of
the timers and the SysTick whenever the firmware changes it. The F411 gets a new model in
place of Renode's; the F103 had ours already, without the tree. The board adds one number,
`clock.hse`. Checked: OpenBLT passes with no clock line in its adapter, and wolfBoot's test
application, which runs a PLL from a 25 MHz crystal and a TIM2 interrupt, behaves as before.
UART baud rates are not derived from this: Renode passes bytes whatever the divisor says.

**Pins.** `pins: {PC13: high}` holds an input at a level after every reset. It does not model
pull-ups or a floating pin; it lets the adapter say what the board does.

**A dead device.** A locked-up core never returns from a run, and the allowance before the
engine gives up grows with the length of the run. One 30-second wait for an update meant up
to ten minutes before "locked up" was reported. Long waits are now made in one-second
slices, so the same verdict comes after one slice's allowance.

## 2026-10-12: An external SPI NOR flash chip

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

## 2026-10-13: Block protection in the external flash chip

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

## 2026-10-13: A slow emulator is not a dead device

MCUboot's swap on the F411 is about 392,000 byte-wide programs. Its cut runs failed with
"the emulator hung before the cut fired", on four of the last cuts, and the baseline once
with "locked up". None of them was a hang. Measured, one second of emulated time at a time:

- a plain run: 13 to 19 s of wall time for each busy second, every time;
- a second run in the same Renode process, with or without a trace: most seconds the same,
  and a few, at different places each time, 95 to 201 s;
- with the step limit raised to 15 minutes the "hung" cut passed, taking 1152 s instead of
  about 150 s.

So Renode sometimes runs more than ten times slower than its usual pace for a while. The
hang limit allowed twenty times the slowest pace seen, with a fixed ceiling (180 s for a
one-second slice), and the wait for a cut never learned the pace at all: it kept the
starting guess, which gave a 0.16 s step 30 s. A step of 91 s was a "hang".

Now: fifty times the slowest pace seen (27 times was measured), no ceiling, and
`run_until_cut` learns the pace like `run_for`. A device that really locks up is still
caught; on a slow run it takes longer to say so, which costs time, not correctness. The
four cuts that had failed then passed, with three emulators side by side.

## 2026-10-13: MCUboot

`adapters/mcuboot` (then `adapters/mcuboot_f411`): MCUboot built with Zephyr v4.2.0 for `blackpill_f411ce`, its
default swap using scratch, the board's own layout (MCUboot 32 KB, then slot 0, slot 1 and
scratch at one 128 KB sector each), ECDSA-P256 signatures (RSA-2048 does not fit 32 KB with
Ubuntu's compiler). A small app prints its version; v2 is staged with `--pad --confirm`, so
only v2 is accepted after a cut.

The update is 391,974 operations (the Zephyr F4 driver programs a byte at a time) in 19
phases; 14.3 s of flash time on the chip. Result: the baseline and 57 planned cuts plus two
more, every one recovered to v2. One build mistake on the way, worth knowing: an app built
for MCUboot on this board must be linked for slot 0 (`zephyr,code-partition`), which the
board files do not choose; without it MCUboot jumps into an app linked for address 0 and
the app aborts.

## 2026-10-14: A third chip family, the nRF52840

Chosen over the STM32L4 because Renode emulates the nRF52840 (UARTE, timers, RTC, clock)
and has no L4 platform at all: the L4 would have meant a whole platform first. The nRF52 is
also a different vendor with different flash rules, and the home of MCUboot.

**The NVMC model** (`models/nrf52_flash.py`). Renode has none: its flash is plain memory.
CONFIG.WEN says what the flash does (Ren, Wen, Een). A program is a store while WEN is Wen,
heard through the CPU's memory-access hook as on the F4; it must be a whole, aligned 32-bit
word (narrower is a hard fault on the chip, refused and reported here), it can only clear
bits, and a word may be written twice between erases (nWRITE = 2; a third write is refused
and reported). How often each word was written lives in memory (`bpCounts`), not in the
model, because a CPU reset does not undo it on the chip. ERASEPAGE erases a 4 KB page and
ERASEALL everything. Times from the product specification, which gives only maximums: 41 us
a word, 85 ms a page, 169 ms for all. The test registers sit at 0x100..0x14C as on the STM32
models; the NVMC's own start at 0x400.

**The platform** is Renode's, written out (`platforms/nrf52840.repl`): the stock file applies
an SVD it downloads at every start, only to name registers in logs, and the download failing
prints an error the engine takes as Renode refusing a command. FICR gets CODEPAGESIZE and
CODESIZE, because Zephyr's flash driver takes the flash size from them; without them MCUboot
cannot read its own slots. The guards cover what is empty on this chip: after flash up to the
RAM alias at 0x00800000, after that alias up to FICR, between UICR and RAM, and after RAM up
to the peripherals. The engine no longer assumes an STM32: the RAM name and the CPU speed
(64 MHz here) come from the chip.

**Checked** with MCUboot on the nRF52840 DK (swap using move, the board's own partitions):
15,400 operations in 52 phases, baseline and 156 cuts, all recovered to v2.

Not modelled: partial erase, the UICR (not part of the flash image; ERASEUICR is ignored),
ACL protection, the cache.

## 2026-10-14: Torn erases, measured

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

## 2026-10-15: The demo on the nRF52840

The demo bootloader builds for a third chip with `-DNRF52` (`common/chip_nrf52.h`). Flash
map in 4 KB pages: bootloader 16 KB at 0, the two rollback-floor pages at 0x4000 and 0x5000,
Slot A at 0x10000 and Slot B at 0x30000, 128 KB each. There are no keys: `flash_unlock()`
does nothing, and each erase or program sets CONFIG (Een or Wen) and puts it back to Ren.
The UART is UARTE0, which sends by EasyDMA from RAM only, so the text goes through a RAM
buffer, a line at a time. The watchdog is only fed: the nRF WDT cannot change its timeout
once it runs.

Builds left out on this chip, and why: `no_unlock` (no keys to forget), `self_lock` (needs
the UICR, not modelled yet), `watchdog` (a 4 KB page erase takes 85 ms), `resume_copy` (a
half-written word may be written once more, as on the F4), and the external-flash builds
(F411 only). One build is new, `nwrite`, for the rule this chip adds: install progress kept
by clearing one more bit of the same word after each step, so the third step is a third
write.

The STM32 binaries are byte for byte what they were before the change (checked with
objcopy on every bootloader and app).

**Checked** in Renode: the correct build, 98 cuts over 98 distinct flash states, all
recovered to v2. Caught: `consume_first` (cut at the Slot A erase), `trust_header` (cut in
the copy: locked up), `naive_floor` (rollback accepted), `pop_after_switch` (bus fault at
0x20040000, baseline), `no_erase` (baseline), `early_unpg` (store with CONFIG not Wen,
baseline), `nwrite` (third write refused, baseline), and `retry_limit` with `--depth 2` (every
single cut recovers, 99 of them; two cuts in a row leave v1). `hold_pg`, the correct build
with CONFIG held at Wen, recovered at all 98 cuts.

## 2026-10-15: Exporting a failing state

Checking a finding on a board took a hand-made flash image (OpenBLT, 2026-10-13). `brickproof
export` makes it: one uninterrupted run, then the golden run replayed to just before the
operation (`trace.Replay`, the same bytes a computed cut powers up from, and checked against
every real cut). `--torn KIND` builds that operation's torn state with the adapter's seed, so
it is the state the campaign booted. The image is split the way a programmer writes it: the
flash, the option bytes (a file of their own, with a warning: a wrong value can lock the
chip), the external chip and its status registers. A state after cuts in a row has no export
command: it is the recovery's flash, and a replay of the second cut needs that first
recovery run.

The image is not run again to check it can be: that is what the campaign did.

**Checked** against the five OpenBLT images made by hand on 2026-10-13 and flashed to the
Nucleo (commit 7dfd266): with the bootloader and the program taken from the complete image,
one run of the update (3,335 operations), and the states before operations 2957, 2976, 3079
and 3148 and after the last one exported. All five are identical to the hand-made files,
byte for byte.

## 2026-10-15: The torn-write kit in the repository

`hardware/torn_f103` is the v2 firmware that gave the 2026-10-14 measurements, the binary that
ran (rebuilt with another compiler the bytes differ, so the measured one is kept), and both
runs' results. `tools/torn_fit.py` reads a run: per delay, the share of old 0 bits still 0 and
the share of bytes showing one against what independent bits predict; where the program goes
from untouched to complete. On the v2 run it gives 4.50% at 0 us and 0.35% at 15 us, the
values in `torn.py`, and a test keeps the two in step. The same reading will take the F411 and
nRF52840 kits (plan item 29) once they exist.

## 2026-10-15: Re-running the fixes from OpenBLT and wolfBoot

Both maintainers answered our reports with a fix within two days, so the adapters ran the
fixes.

**OpenBLT r1326** (`62786e72`) swaps the two writes in `FlashDone()`: the last data block now
goes before the boot block. Run with the same adapter (phases plan, 23 cuts): the data
blocks are fine, and 4 cuts fail, all in the boot block after its checksum word (0x10C),
because the block is still written from its start. The driver's message said "before the
last block", which no longer fits: it now says "before the rest of the program". Suggested
back to Feaser: the part of the block after the checksum first, then the part up to and
including it, so nothing is written twice (some of their targets allow one write per cell).

**wolfBoot PR #940** (`45a5909e`) moves the STM32F4 trailers to sectors 1 and 2. The driver
gets a `trailer` option, the address where the UPDATE trailer ends, because the update flag
is no longer at the end of the partition; `adapter-custom-trailer.yaml` sets it. 44 cuts, all
recovered, every state cut in the new trailer rewrite (erase the 16 KB sector, write 64
bytes back), which was the step most likely to fail. Run on this PC with 6 emulators: 86
minutes, each cut 10 to 12 minutes of byte-by-byte programming over 128 KB sectors.

## 2026-10-16: MCUboot and the nRF52840 in CI

MCUboot needs a Zephyr workspace to build, which is too much for every CI run and for a new
user. `build.py`'s output for both boards is committed in `adapters/mcuboot/prebuilt`
(built once on an ubuntu-latest runner: MCUboot `4eba8087`, Zephyr v4.2.0 `413b789`, Ubuntu's
arm-none-eabi-gcc 13.2.1), and the adapters point there unless `--target` says otherwise.
`mcuboot.elf` has its debug sections stripped: 1.1 MB down to 90 KB, symbols kept, the
loaded bytes checked identical.

Timing decided the CI settings. One uninterrupted update: 4 min on the F411 (391,974 byte
programs), 2 min on the nRF52840. Every cut then runs MCUboot's recovery, which on the F411
redoes the rest of a 128 KB byte-by-byte swap, about 5 minutes. The adapters' own plans (57
and 156 cuts) would take hours on a 4-core runner. CI therefore runs `--per-phase 1
--real-every 4`: every edge between phases is cut, one sample inside each long phase, and
three in four cuts start from the computed state (the real ones check it byte for byte). On
this PC with 6 emulators: nRF52840 111 cuts, all recovered, 3.5 min; F411 42 cuts, all
recovered, 56 min. So on a runner the F411 is split over four shards (`--shard K/4`), which
together make exactly those 42 cuts. First CI run: the shards took 8 to 19 minutes (a runner
goes through the F411 update in about a minute, four times faster than this PC), the
nRF52840 5 minutes.

The nRF52840 demo joins the `demo` matrix: the correct build with torn states and depth 2,
`hold_pg` with torn states, and the eight bug builds, each expected to fail.
`nrf52-bug-retry_limit.yaml` now sets `scenario.depth: 2` like its STM32 versions, so it is
caught without a command-line flag.

## 2026-10-16: Flash storage libraries (plan item 18)

**What is judged.** A store promises less than a bootloader: not "one of two images", but
"what I said I stored is there". The `storage` driver checks exactly that. The firmware runs
a fixed workload (80 writes and deletes over 8 keys) and says "C <step>" when each call
returned. Values carry their key, generation and length and a pattern made from them, so a
read tells a whole value from a half-written or mixed-up one.

**Which steps had finished, at any cut.** The verdict needs the commits made before the cut,
also for cuts that are computed or torn (never run in that emulator), so reading the UART at
cut time is not enough. Before the campaign the driver runs the workload one step at a time
("S" commands) and notes the flash operation count before and after each step. The workload
is deterministic, which the golden run's self-check already relies on, so a cut before
operation N has finished every step that ended at or before N; the step that started and had
not ended may or may not have taken effect, and both values are accepted. The runner now
tells a driver which update operation each result was cut at (`judging()`): the cut's
operation, the torn state's, or for cuts in a row the first cut's.

**After a cut**, three checks: the store mounts and was not formatted again; every key holds
its last finished value or the one under way, and nothing reads back half-written or fails
to read; and the store takes a new write (the probe key) that is still there after another
power cycle with the other keys unchanged. The last check is what catches a store that
mounts fine but has a damaged write position.

**The workload firmware** is one Zephyr app built four ways (NVS, ZMS, settings on FCB,
littlefs), on the nRF52840 DK, built once on a GitHub runner and committed as prebuilt like
MCUboot. Two things had to change for Renode: the DK's external QSPI flash is disabled (Renode
does not model the QSPI controller and Zephyr's driver waits for it at start-up for ever),
and the oracle's `.bin` files are objcopy's output from the ELF, not Zephyr's `zephyr.bin`,
which fills a gap between sections with 0xFF where loading the ELF leaves zeros. littlefs
needed its cache raised to 256 bytes so the values stay inline (with 64, every file takes a
4 KB block and 8 files do not fit 8 blocks), and a littlefs file left empty by a cut between
its creation (committed at open) and its data (committed at close) is read as absent.

**Results** (every distinct flash state cut, this PC, 6 emulators): NVS 2,158 of 2,158 (17
min), plus 754 cuts and 2,253 torn states with the phases plan; littlefs 3,228 of 3,228 (28
min); ZMS 130 of 2,327: every cut inside a value's data or ATE leaves the next write landing
on the half-written words, which on the nRF52 (two writes per word, old AND new) reads back
wrong. That is the open report zephyrproject-rtos/zephyr#121747; booting the exported op-5
state shows the overlap word by word.

**CI** runs NVS and littlefs with the adapters' phases plan, expecting no failure, and ZMS
with `--fail-fast`, expecting exit code 1 until #121747 is fixed upstream.

## 2026-10-16: Bad update content (plan item 12)

A bootloader that survives every power cut can still run an image that is wrong. Content
faults stage damaged versions of the update and let it run to the end. Judging uses only the
oracle and the driver's `alive()`: the image named by `keep` must still be installed, and the
CPU running inside it. The driver's own recovery check is not used, because it expects the
update to have happened.

The mutations are generic, so they need no knowledge of the image format: truncation (at a
quarter, a half, three quarters, and four bytes short, the rest erased), one bit flipped in
the middle of each region the adapter names, and an erased image. What needs the format
(another signing key, an older version, the wrong slot) comes from the adapter as finished
files (`images`). `image_size` keeps the part of the staged file after the image as it was:
MCUboot's staged image is padded to the slot with a trailer that asks for the upgrade, and
truncating that away would make MCUboot not try the image at all, which tests nothing.

**Checked** in Renode: the demo on the F103, F411 (internal and external staging) and nRF52
refuses all 7 and keeps v1; the `trust_header` bug build, which checks only the magic,
accepts 6 of 7 (all but the erased one; a truncated image left installed ran into erased
code and stored to flash, which the flash rules caught). MCUboot refuses all 8 on both boards
(F411 and nRF52840), a bit in its TLV area included. A first version cut a damaged image staged in the external
chip to nothing (it limited the copy to the internal flash's size), so `f411-ext` passed
nothing; the copy now stops at the end of the flash it is staged in.

In a sharded run only shard 1 makes the content faults: they are not cuts, and the other
shards would repeat them. Not done yet: a cut while a bad image is being checked or erased.

## 2026-10-16: A broken link instead of lost power (plan item 14)

An update sent over a protocol can also be lost to the link: the cable comes out, the host
crashes, a CAN bus goes quiet, while the device keeps its power. The bootloader then has a
half-received session to deal with, not a half-written flash.

The break is made in the session, not in the drivers: `uart_write` gets a byte budget, and
once it is used up the rest of what the host sends is dropped. Both protocol drivers send
everything through `uart_write`, so neither needed a change. The baseline counts the bytes
the host sends; link cuts are placed at the first byte, the last, and `points` evenly between.
After a cut the link stays down for `wait` virtual seconds, then the host runs the whole
update again (`start_update()`), and the result is judged like a power cut's.

**Checked** in Renode: OpenBLT 62786e72 (a 6,422-byte XCP session) recovered at all 10
points: after each, a new session installed the program and it ran. The Three-Tier
bootloader v2.0.0 (its 170-byte UPDATE_FBL frame) recovered at all 10: a partial frame
never started the self-update, and the frame sent again installed the new FBL. A unit test
checks that with a budget only that many bytes reach the device. Only the UART is covered:
the Three-Tier adapter drives its update over the UART too, and a CAN link would need the
same budget on the CAN frames.

## 2026-10-16: Bit errors at rest (plan item 16)

Flash cells lose charge over the years, and a bit in a stored image can flip while the device
is off. The test takes the flash the uninterrupted update left (the golden run replayed to its
end), flips seeded random bits in one region, powers up and samples the CPU from outside: it
must not execute inside that region, and must not be in a fault handler. Refusing to boot
counts as right, because running damaged code is the failure that matters.

The first run used the whole of each accepted image as the region and failed the correct demo
on 3 of 4 flips. All three were in the 0x1F0 bytes of padding between the demo's 16-byte header
and its body at +0x200, which nothing reads and its CRC does not cover: the image there is as
good as before. So the demo adapters name header and body. MCUboot hashes its whole header
area, so its default regions are right.

**Checked** in Renode: the demo on the F103, F411 and nRF52 refuses all 8 (4 in the header, 4 in
the body) and stays in its bootloader; `bug-trust_header` (magic only) runs every damaged body
(one run stored to flash from the damaged code, which the flash rules caught); MCUboot on the
F411 and the nRF52840 refuses all 4 on each.

## 2026-10-16: Worn pages (plan item 15)

A page past its rated cycles may still erase but no longer program reliably. The datasheets
say it differently per chip (on an F1 the data does not match after programming; the F4 may
or may not flag it; on the nRF52 nothing flags it), and they agree on the part that matters:
the program can look fine and the data is wrong. So one behaviour is modelled on all three:
in the `flash.worn` range a program is accepted and bit 0 of each cell keeps its old value.
No status flag is set, which is the hardest case for firmware.

The models get the range as two constants (`WORN_FROM`, `WORN_TO`, none by default), like
their geometry, so nothing changes for an adapter that does not set it. The value the model
stores is what goes into the trace and the shadow copy, so the replay and the self-check
follow the worn cells too.

Not modelled: a cycle count after which a page wears out (`fail_after` in the plan). Counting
erases per page across runs would need state that outlives a run, and one fixed worn range
already answers the question the plan asks: does the bootloader notice. The demo does not:
with its Slot A worn the copy of v2 is wrong, its CRC fails at boot, and the old image has
already been erased, so the update fails with no power cut at all. That is what an
overwrite updater that does not read back its writes does on such a chip.

## 2026-10-16: Power cuts many times in a row (plan item 17)

The exploration of cuts during recovery already went level by level, so depth 3 and beyond
needed no new machinery: each level's new states are the parents of the next, and a flash
state already tested is skipped. What was missing is a way to say "until nothing new turns
up": `depth: exhaustive` (or `--depth exhaustive`) runs levels until one brings no new state,
with `max_states` (2,000 by default) as the stop that keeps it finite. The report says how
deep it went.

**Checked** in Renode, this PC, 6 emulators: the demo at depth 3, 173 first cuts and 202 new
states, all recovered, 2 minutes. The Three-Tier bootloader v2.0.0 at depth 3: 37 first cuts,
10 broken links and 34 new states, all recovered, 13 minutes. The demo exhaustive stopped at
the 2,000-state limit after 20 cuts in a row, all recovered: it never runs out of new states,
because every interrupted install raises the rollback-floor record's sequence number, so each
further cut leaves flash never seen before. For such a design the limit is the answer; a
design whose recovery repeats itself exactly (the unit test's fake updater) stops at level 2.

## 2026-10-16: SARIF output (plan item 22)

`--sarif FILE` writes the failures as SARIF 2.1.0, so a CI run's failures appear as code
scanning alerts next to the code. One result per failure; the rule is its kind (power cut,
torn state, cuts in a row, bad content, broken link, bit error, or the update failing with
no cut), so alerts group by what went wrong. The location is the adapter file, not the
firmware the plan named: code scanning needs a file in the repository, and the firmware is a
build output that is usually not committed, while the adapter always is. A stable
fingerprint (adapter name and result name) lets GitHub match an alert across runs. The
message carries the reproduce and export commands.

**Checked**: the SARIF from a run of the demo's consume_first bug (15 failures) validates
against the SARIF 2.1.0 schema from schemastore.org. Not checked yet: an upload to a
repository's code scanning (it needs code scanning turned on there).

## 2026-10-16: Soak runs (plan item 21)

The planned campaign covers what a plan can: every distinct state, or the edges and samples
of long phases. A soak spends a time budget on random tests instead, for long unattended
runs on a machine with nothing else to do. `--soak MINUTES --seed N` draws, after the
baseline, a random operation and either a clean cut before it (60%) or that operation left
half done in a random torn shape (40%; a shape that does not apply there becomes a clean
cut). Each test powers up from the computed state, which every real cut checks, so a test
costs one boot. Draws come in batches of one per emulator and stop at the first failure,
which keeps its usual reproduce and export commands. The same seed draws the same tests.

Not in a soak yet: content faults and cuts in a row. Content faults are a fixed small set,
better run by the plan, and a cut during recovery needs that recovery traced first, which
is the depth exploration's job.

**Checked** in Renode: `brickproof demo resume_copy --soak 10 --seed 1` (a bug only a torn
program shows) failed at its 10th test, a torn program at op 73, after about 10 seconds. The
correct demo with `--soak 3 --seed 1`: 1,038 tests (885 cuts, 153 torn states), no failure.
