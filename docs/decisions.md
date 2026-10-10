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
