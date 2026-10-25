# The docs, split by what a reader wants

2026-10-25

The README was 357 lines: the pitch, a tutorial, every option, the layout and the limits,
one after the other. `docs/` held an adapter reference, a 2,000-line decisions file and a
few notes, with no index.

Now the README says what BrickProof is and what it found, and gives the three commands to
run the demo, the two to test your own firmware and the CI snippet; everything else is a
link. The text moved, not rewritten:

| Was in | Now |
|---|---|
| README, quick start | `docs/getting-started.md` |
| README, what a run covers | `docs/guide/what-a-run-covers.md` |
| README, testing your own firmware | `docs/guide/testing-your-firmware.md` |
| README, the reports, CI, Docker | `docs/guide/results-and-ci.md` |
| README, options and exit codes | `docs/reference/cli.md`, with the commands added |
| README, limits | `docs/reference/limits.md` |
| README, layout | `docs/architecture.md`, with how a run works added |
| `docs/adapter.md` | `docs/reference/adapter.md` (the old path keeps a pointer) |
| `docs/decisions.md` | `docs/decisions/`, one numbered record per decision and an index (the old path keeps a pointer) |

`docs/README.md` is the index. One file per decision also means two pull requests no longer
both append to the same file. `tests/test_docs_links.py` checks that every relative link in
every Markdown file leads somewhere, since a move like this is how links break.
