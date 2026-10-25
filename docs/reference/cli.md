# Command-line options

## Commands

| Command | What it does |
|---|---|
| `brickproof setup` | download the emulator (Renode) for this system, checked against its SHA-256 |
| `brickproof init` | write an adapter by answering a few questions, then boot the firmware once to find the rest |
| `brickproof check ADAPTER` | find what is wrong with an adapter, without an emulator |
| `brickproof run ADAPTER` | run an adapter's power cuts |
| `brickproof demo [NAME]` | run the bundled demo bootloader; `--list` shows every build |
| `brickproof trace ADAPTER` | run the update uninterrupted and show its flash operations, in phases |
| `brickproof export ADAPTER --cut N` | write the flash a cut leaves, to put on a real board |
| `brickproof adapter-from-zephyr BUILD --images DIR` | write an MCUboot adapter from a Zephyr build |

`brickproof <command> --help` lists every command's options.

## Options of `run` and `demo`

| Option | What it does |
|---|---|
| `--full` | everything in one run: clean cuts, `--torn`, `--depth 2` and the adapter's damaged-image tests, on one emulator per core, with a long update sped up automatically (most cuts powered up from their computed state) |
| `--plan every` / `--plan phases` | cut every distinct flash state, or sample long phases |
| `--torn` | also boot from torn erases and programs |
| `--depth 2` | also cut during the recovery from each first cut |
| `-j N` / `-j auto` | run N emulators side by side; the results do not depend on N |
| `--real-every N` | on a long update, make every Nth cut in the emulator and compute the rest |
| `--soak MINUTES --seed N` | instead of the plan, random cuts and torn states until the time is up or one fails |
| `--shard K/N` | run every Nth cut, starting with the Kth: splits a long campaign over N machines |
| `--cut N` | run one operation alone, to reproduce a result |
| `--fail-fast` | stop at the first failure |
| `--json`, `--junit`, `--html FILE` | reports |
| `--sarif FILE` | the failures as SARIF 2.1.0, for GitHub code scanning |

## Exit codes

Exit codes: `0` every cut recovered, `1` at least one failed, `2` adapter error, `3` BrickProof
itself failed (including its own flash self-check).
