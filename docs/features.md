# Features and what proves them

Every feature BrickProof has, and the check that shows it still works. A restructuring is
done when every row still has its proof and the parity check passes (see the end).

**Proof** names a CI campaign (a scenario in `tests/scenarios.yaml`: the adapter in
`examples/demo_ab_bootloader/` or `adapters/` and how it is run), a unit test file in `tests/`, or a Renode test in
`tests/renode/` (CI job `model-rules`). **Unit only** means the logic is tested against a
simulated device but no CI job runs it end to end in an emulator. **Not in CI** means
nothing automatic checks it today.

## Chips and emulators

| Feature | Proof |
|---|---|
| STM32F103 (Renode): pages, halfword programs, PGERR on a non-erased cell, WRP and RDP option bytes | demo `adapter` and its 15 other builds; `tests/renode/test_f1_rules.py` |
| STM32F411 (Renode): sectors, PSIZE, AND programming, OPTCR, PCROP, RDP level 2 | demo `f411` and its 19 other builds; `tests/renode/test_f4_rules.py`, `test_option_bytes.py` |
| STM32L476 (Renode): 2 KB pages, 64-bit programs, ECC and the NMI | demo `l476` and its 12 other builds; `tests/renode/test_l4_rules.py`, `test_stm32l4.py` |
| nRF52840 (Renode): NVMC CONFIG, two writes per word, UICR, ERASEALL, partial erase, ACL | demo `nrf52` and its 10 other builds; `tests/renode/test_nrf52_rules.py`, `test_nrf52_flash.py` |
| STM32H563 (m33mu): 128-bit programs, WRPSG, bank swap | demo `h563` and its 11 other builds (scenarios on m33mu); `test_m33mu.py` |
| RCC models: timers and SysTick follow the firmware's clock setup, `clock.hse` | every STM32 demo on Renode; MCUboot `f411` (25 MHz crystal) |
| Real flash and RAM sizes, memory guard over address holes | `bug-pop_after_switch` on every chip; `test_workdir.py` |
| Flash timing `typical` / `max` / `none` | demo `f411-watchdog` (a one-second erase); `test_trace.py` (costs). `max` and `none`: unit only |
| Hardware watchdog (`hardware_watchdog`) | demo `watchdog`, `f411-watchdog`, `f411-bug-watchdog` |
| Low power: Stop, Standby, `reset_on` | demo `standby`, `f411-standby`, `bug-standby_ram`; `tests/renode/test_pwr_rules.py`. `reset_on`: Renode test only |
| External SPI NOR flash (3 and 4-byte addressing, BP/TB/SEC, status registers, /WP) | demo `f411-ext`, `f411-ext-bug-consume_first`; `tests/renode/test_spinor_rules.py`, `test_spinor_4byte_rules.py` |
| I2C EEPROM (24-series, pages, wrap) | demo `f411-ee`, `f411-ee-bug-no_invalidate`; `tests/renode/test_eeprom_rules.py`, `test_eeprom.py` |
| Worn pages (`flash.worn`) | `test_worn.py`. Unit only |
| `pins` held at a level | OpenBLT adapter. Not in CI |

## What a run tests

| Feature | Proof |
|---|---|
| Baseline (the update with no cut) and the golden trace | every campaign |
| Clean cuts at every distinct flash state (`plan: every`) | every demo campaign; `test_plan.py` |
| Sampled phases (`plan: phases`, `per_phase`, `small`) | e2e (Three-Tier), MCUboot, `action (renode)`; `test_plan.py` |
| Computed cuts checked against real ones (`real_every`, `auto`) | MCUboot (`--real-every 4`); `test_plan.py` |
| Program cuts rewound to land before their operation | `test_runner.py` |
| Self-check of the emulated flash against the golden run (exit 3) | every campaign; `test_runner.py` |
| Torn erases and programs (`--torn`, measured and modelled shapes) | demo correct builds, `bug-resume_copy`, `l476-bug-no_ecc_nmi`, `f411-ee-bug-no_invalidate`; `test_torn.py`, `test_torn_fit.py` |
| A second cut during recovery (`--depth 2`) | demo correct builds, `bug-retry_limit` on every chip, e2e; `test_depth.py` |
| Damaged update images (`content_faults`) | demo correct builds on every chip, MCUboot `f411` and `nrf52840`; `test_content.py` |
| Bit errors at rest (`bit_errors`) | demo correct builds on every chip, MCUboot; `test_bit_errors.py` |
| A broken UART link (`link_cuts`) | e2e (Three-Tier); `test_link.py` |
| Hand-picked cuts (`at_op`, `on_erase`, `at_ops` ranges) | e2e; `test_runner.py` |
| Random soak (`--soak`, `--seed`) | `test_soak.py`. Unit only |
| `--full` (everything in one run) | Not in CI |
| `--quick` (a first look: phase edges and one cut per long phase) | `test_cli_output.py`. Unit only |
| Progress and time left after each cut (terminal only); a failure's reproduce and export commands | `test_cli_output.py` |
| Parallel emulators (`-j N`, `-j auto`), results independent of N | every `-j 3` campaign; `test_pool.py` |
| `--shard K/N` | MCUboot `f411` (4 shards); `exhaustive.yml` (20 shards, run by hand) |
| `--cut N`, `--fail-fast` | bug builds (`--fail-fast`); `--cut`: `test_runner.py`, unit only |
| A hung run repeated once before it is called locked up | `nrf52-bug-trust_header`; `test_runner.py` |

## How a result is judged

| Feature | Proof |
|---|---|
| Oracle: an approved image installed byte for byte and the CPU running inside it | every campaign with `oracle:`; `test_oracle.py` |
| `stable_for`: no reset in the next seconds | `nrf52-bug-boot_loop`, e2e; `test_oracle.py` |
| Rollback check (an older image staged must not run) | demo correct builds (`rollback:`) |
| Fault handlers detected (HardFault, BusFault, NMI) | `bug-pop_after_switch`, `l476-bug-no_ecc_nmi` |
| A stray write with no flash operation behind it | `bug-early_unpg` on every chip |
| Refused programs, write protection, protected reads, PCROP reads | `bug-no_erase`, `bug-protected_slot`, `bug-self_lock`; `tests/renode/test_f4_rules.py` |
| Lock-up detection (`MachineHung`, adaptive hang limit) | `bug-trust_header` on every chip; `test_session_lifecycle.py`, `test_runner.py` |

## Drivers

| Feature | Proof |
|---|---|
| `builtin: staged_slot` | every demo campaign, MCUboot |
| `builtin: storage` (key-value store or file system workload) | scenarios `storage-*`: NVS, littlefs (pass), ZMS, settings on FCB (must fail); `test_storage.py` |
| `file: driver.py` (protocol updates, `export_state` / `import_state`, `judging`) | e2e (Three-Tier); OpenBLT and wolfBoot adapters (not in CI) |

## Commands

| Command | Proof |
|---|---|
| `brickproof setup` (download Renode, checked against its SHA-256) | `test_setup.py`. Unit only |
| `brickproof init` (questions, then one probe boot) | `test_init.py`. The probe boot: not in CI |
| `brickproof check` | `test_check.py`; `run` makes the same checks before every CI campaign |
| Unknown adapter keys refused, with the nearest real key (`adapter_keys.py`) | `test_adapter_keys.py`, which also checks that the adapter reference documents every key |
| `brickproof run` | every CI campaign |
| `brickproof demo`, `demo --list` | `docker`, `package` |
| `brickproof trace` | `test_trace.py`. The command itself: not in CI |
| `brickproof export` | `test_export.py`. Unit only |
| `brickproof adapter-from-zephyr` | `test_zephyr_adapter.py` |
| `extends:` in adapters | 67 of the demo's 72 adapters extend another (five base adapters); `test_adapter.py` |

## Reports

| Feature | Proof |
|---|---|
| JSON | every CI campaign (it feeds the parity check) |
| JUnit, HTML | every CI campaign writes them; `test_report.py` |
| SARIF 2.1.0 | `test_report.py`. Unit only |
| Regulation map (UN R156, EU CRA) in the HTML | `test_report.py` |
| Reproduce and export commands for each failure | `test_report.py` |

## How BrickProof is shipped

| Feature | Proof |
|---|---|
| PyPI package `brickproof-fw`, the demo inside it | `package` (wheel and sdist, installed clean) |
| GitHub Action (`action.yml`), m33mu built and cached by it | `action (renode)`, `action (m33mu)` |
| Docker image | `docker` |
| Release workflow (`release.yml`) | run on a tag |
| Exhaustive run over many machines (`exhaustive.yml`) | run by hand |

## Real targets

| Target | Proof |
|---|---|
| Three-Tier bootloader (F103), built from source | e2e |
| MCUboot F411 swap-scratch, F411 overwrite-only, nRF52840 swap-move | scenarios `mcuboot-*` |
| Zephyr NVS, littlefs, ZMS, settings on FCB | scenarios `storage-*` |
| OpenBLT (F103) | Not in CI (firmware built by hand) |
| wolfBoot F411, wolfBoot H563 | Not in CI (firmware built by hand) |
| Torn-write measurement kit and fit (`hardware/torn_f103`, `tools/torn_fit.py`) | `test_torn_fit.py` |

## The parity check

`tests/parity/baseline.json` holds, for every campaign CI runs, the verdict, the coverage
and every cut's outcome, taken from the reports of a green run on main (its `source` says
which). `tools/parity.py compare tests/parity/baseline.json <reports>` must say "every
result the same" after a change that is not meant to change results; the CI job `parity`
runs it on every push. A change that is meant to change results (a new chip rule, a target
rebuilt) regenerates the baseline in the same pull request with
`tools/parity.py fingerprint <reports> -o tests/parity/baseline.json`, so the diff shows
what moved.
