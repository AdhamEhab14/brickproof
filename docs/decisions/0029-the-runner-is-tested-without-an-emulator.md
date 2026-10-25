# The runner is tested without an emulator

2026-10-10

`runner.campaign()` (baseline, cuts, rewind, self-check, skip and fail-fast rules, lock-up
handling) is separate from `run()` (start Renode, stage the update). `tests/fake_device.py`
is a simulated device with the session's interface and a tiny correct updater that can be
broken on purpose (no recovery, bus fault, lock-up, different writes on the second run).
17 tests in `tests/test_runner.py` run in a fraction of a second, on Python 3.10, 3.12 and
3.13 (new `compat` CI job).

Removed `tests/test_three_tier_e2e.py`: it was skipped by default, CI never ran it, and it had
drifted from the code. The CI `e2e` job runs the same thing through the CLI.
