# The runner, one module per part

2026-10-26

`runner.py` was 967 lines holding everything a campaign does: the result types, the golden
run, judging a result, clean cuts, torn states, the soak, damaged images, bit errors, a
broken link, cuts during recovery, the campaign itself and starting the emulators. Adding a
kind of test or fixing one meant finding your way through all of it.

It is now the package `brickproof/campaign/`, one module per part: `results`, `golden`,
`judge`, `cuts`, `faults`, `depth`, `core` and `bringup`, from 47 to 176 lines each. The
move was mechanical: each top-level definition went over whole, with its decorators and the
comments above it, and a check found every one of the old file's 825 lines of code and 26
comments in the new modules. `_failed` moved to `judge`, where the other verdict helpers
are, since four modules use it. Each module imports only what it uses.

`runner.py` stays, re-exporting every name it used to define, so `from brickproof import
runner` and everything that calls `runner.campaign`, `runner.run` and the rest work as
before. One test patched `runner.find_renode`; it now patches it where `find_emulator` looks
it up, `campaign.bringup`. `brickproof.campaign` is in the package list, and the wheel
carries it.
