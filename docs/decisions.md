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
