# Every target folder the same, and committed firmware checked

2026-10-25

The six targets in `adapters/` had grown one at a time. Five had a README with "Running it"
and "What it found"; the first one, the Three-Tier bootloader, had none. There was no list
of them, and nothing showed what a target folder should hold.

`adapters/README.md` now lists every target with its chip, its update, where its firmware
comes from, whether CI runs it and what it found, and says what a target folder holds. The
Three-Tier folder has its README.

The prebuilt firmware CI runs (the demo's 78 files, MCUboot's three boards, the storage
workload) had a README saying how it was built, but nothing that noticed if a binary
changed. Each prebuilt folder now has a `SHA256SUMS`, and `tests/test_prebuilt.py` fails
when a file differs from it or is added or removed without it. The demo's
`build.py --prebuilt` writes it; for the others the README says how.
