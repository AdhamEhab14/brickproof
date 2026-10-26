# How BrickProof is built

## How a run works

1. **Bring-up.** The adapter is read and checked (`adapter.py`, `check.py`), a work folder is
   made with the chip's platform and flash model (`engine/workdir.py`), and one emulator per
   job is started and booted (`engine/session.py`, or `engine/m33mu.py` for the H5).
2. **The golden run.** The update runs once with no cut. The flash model counts and logs
   every erase and program; that trace (`trace.py`) is what the update does to flash, and
   replaying it gives the flash at any point.
3. **The plan.** Cuts go only where the flash differs from every state already chosen
   (`plan.py`): all of them, or the edges and samples of long phases. Torn states (`torn.py`)
   and a second cut during recovery are added when asked for.
4. **Each cut.** From the same starting flash, the update runs again with power cut at one
   operation; the flash is checked byte for byte against the replay, the device is powered
   up, and the oracle (`oracle.py`) and the driver judge whether it recovered
   (`campaign/cuts.py`, `campaign/judge.py`, spread over the emulators by `pool.py`).
5. **The verdict.** Every result goes into the JSON, JUnit, HTML and SARIF reports
   (`report.py`), with the command that reproduces each failure.

## Where the code is

| Path | What |
|---|---|
| `src/brickproof/engine/` | Renode and m33mu drivers in lock-step virtual time, work-folder setup |
| `src/brickproof/models/` | The flash controller model (operation counting, cuts, the chip's rules, option bytes) and the memory guard |
| `src/brickproof/platforms/` | Base Renode platforms the models plug into |
| `src/brickproof/trace.py` | The golden-run trace: phases, replay to any operation |
| `src/brickproof/plan.py` | The cut planner: distinct flash states, exhaustive or sampled |
| `src/brickproof/torn.py` | Torn states: an erase or a program left half done |
| `src/brickproof/oracle.py` | The outside judge: approved image installed, and really running |
| `src/brickproof/campaign/` | A campaign, one module per part: `results`, `golden` (the uninterrupted update), `judge` (one verdict), `cuts` (power cuts, torn states, soak), `faults` (damaged images, bit errors, a broken link), `depth` (cuts during recovery), `core` (the whole campaign), `bringup` (the emulators and `brickproof run`). `runner.py` re-exports the names other code imports |
| `src/brickproof/pool.py` | Shares the cuts over several emulators, results in a fixed order |
| `src/brickproof/report.py`, `regulations.py` | JUnit and HTML reports, and the regulation map |
| `src/brickproof/export.py` | A cut's flash as files for a real board |
| `src/brickproof/drivers/` | Built-in drivers (`staged_slot`) |
| `examples/demo_ab_bootloader/` | The demo: its adapters in one folder per chip (`f103/`, `f411/`, `l476/`, `nrf52/`, `h563/`), and in `firmware/` its source, prebuilt files and build script |
| `adapters/` | Real targets, one folder each (Three-Tier bootloader, MCUboot, Zephyr storage, OpenBLT, wolfBoot on the F411 and the H563); [adapters/README.md](../adapters/README.md) lists them and what each found |
| `hardware/torn_f103/`, `tools/torn_fit.py` | The firmware that measured torn writes on a real STM32F103, its results, and the tool that turns them into `torn.py`'s numbers |
| `docs/decisions/` | Why things are the way they are, with the measurements behind them: one record per decision |
| `docs/features.md`, `tools/parity.py` | Every feature and the check that proves it; the parity check that keeps every result the same through a change |
| `tests/scenarios.yaml`, `tools/scenarios.py` | Every campaign CI runs and the exit code it must give; the runner that shares them out over CI jobs |
