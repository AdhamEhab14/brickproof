# A parity check before restructuring

2026-10-25

The project is about to be reorganised (CI, layout, code), and the rule is that no feature
is lost. That needs proof, not care. Two things now give it.

`docs/features.md` lists every feature with what proves it: a CI campaign, a unit test, a
Renode rule test, or, honestly, nothing. Writing it found features no CI job runs end to
end: `--full`, `--soak`, worn pages, the `trace`, `export` and `setup` commands, `init`'s
probe boot, and the OpenBLT and wolfBoot targets.

`tools/parity.py` reduces each campaign's JSON report to what decides its result (verdict,
coverage, each cut's outcome; no timings) and compares a run with
`tests/parity/baseline.json`, taken from the 84 reports of main's green run 40115285524
(a3f3854). A CI job runs it after every campaign. Cuts are matched by name, so one cut more
or less is one line, not a shifted list.

Checked against main's previous green run, it found two things. The Three-Tier e2e target
differs, as it should: #43 builds it with Arm's toolchain instead of Ubuntu's, so its
binary and flash states changed (12,109 distinct states before, 11,897 after). And
`nrf52-bug-trust_header`'s failing cut gave a different message: in that run the first
attempt hung and the repeat on a fresh emulator (2026-10-23) did not, but ran 1,190 s and
was stopped by the stray-write check instead. Firmware that jumps into erased flash can be
caught by more than one check, and a fresh emulator can take another path through that
garbage than one that has run before. The verdict is the same, so a changed message on a
cut that fails either way is a warning in the parity check, not a failure. Why the fresh
emulator behaves differently there is still open.
