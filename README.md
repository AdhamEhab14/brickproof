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

The demo is a small A/B bootloader updating its app from v1 to v2. BrickProof cuts power at
every one of the update's flash operations, one per line, after first checking that the update
works when nothing interrupts it:

```
PASS baseline (no cut)   168 ops                    2.9s
PASS op-0                op 0     erase 0x0801E400  2.0s
PASS op-1                op 1     program           1.8s
...
```

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

The last one is not a power-loss bug. A real board found it in another bootloader after the
emulator had passed it, because emulated RAM was far bigger than the chip's. BrickProof now
gives the emulated chip its real memory sizes and treats any access outside them as a fault.

Exit codes: `0` every cut recovered, `1` at least one failed, `2` adapter error, `3` BrickProof
itself failed. `--json FILE` writes the results for CI.

## Testing your own firmware

Write an adapter: one YAML file that says what to load, the real flash and RAM sizes of the chip,
and where to cut.
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
| `src/brickproof/drivers/` | Built-in drivers (`staged_slot`) |
| `examples/demo_ab_bootloader/` | The demo firmware, its source, prebuilt files and adapters |
| `adapters/` | Adapters for real projects (Three-Tier bootloader) |
| `docs/decisions.md` | Why things are the way they are |

## Licence

Apache-2.0, see [LICENSE](LICENSE).
