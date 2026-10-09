# BrickProof

Pull the plug on your firmware update, in an emulator, at every flash operation, and check
that the device still comes back.

BrickProof runs a firmware binary in [Renode](https://renode.io), cuts power just before
each flash erase and program during an update, reboots, and checks recovery invariants
with an oracle that shares no code with the firmware under test.

**Status:** early development. The engine is being extracted from the power-cut harness of
[Three-Tier-STM32-Secure-Bootloader](https://github.com/AdhamEhab14/Three-Tier-STM32-Secure-Bootloader),
where it found three real bugs.

## Try it

You need Python 3.10+, [Renode 1.17](https://github.com/renode/renode/releases) (set `RENODE_PATH`
or put `renode` on PATH), and the first target, the Three-Tier bootloader, built with its test keys:

```bash
git clone https://github.com/AdhamEhab14/Three-Tier-STM32-Secure-Bootloader
cd Three-Tier-STM32-Secure-Bootloader
cmake -S . -B build-test -G Ninja "-DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake" -DBL_TEST_KEYS=ON
cmake --build build-test
```

Then, from this repo:

```bash
pip install -e ".[dev]" -r adapters/three_tier_f103/requirements.txt
brickproof run adapters/three_tier_f103/adapter.yaml --target ../Three-Tier-STM32-Secure-Bootloader
```

Each line of output is one real power cut during the bootloader's FBL self-update, the flash
operation it landed on, and whether the device came back.

## Layout

| Path | What |
|---|---|
| `src/brickproof/engine/` | Renode driver in lock-step virtual time, work-folder setup |
| `src/brickproof/models/` | Flash controller models that count operations and cut power (STM32F1 so far) |
| `src/brickproof/platforms/` | Base Renode platforms the models plug into |
| `adapters/` | One folder per target: `adapter.yaml` plus a `driver.py` that knows its update protocol |
| `docs/decisions.md` | Why things are the way they are |

## Licence

Apache-2.0, see [LICENSE](LICENSE).
