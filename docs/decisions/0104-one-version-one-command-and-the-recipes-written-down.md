# One version, one command, and the recipes written down

2026-10-26

Working on BrickProof needed things only its author knew: which files hold the version (four;
a release once failed on the one forgotten), how to run the tests without installing (a
PYTHONPATH that differs on Windows), and every step of adding a demo bug build, a target or
a chip.

- **One version.** `src/brickproof/__init__.py` holds it; `pyproject.toml` reads it from there
  (`dynamic = ["version"]`), and so does the release workflow's tag check.
  `tests/test_version.py` checks that the GitHub Action examples a user copies name it and
  that the changelog has its section or an Unreleased one on top.
- **One command.** `python tools/dev.py check` (lint and the unit tests), `test`, `renode`,
  `scenario ID`, `parity FOLDER` and `docs`, from anywhere in the checkout, on this
  checkout's source.
- **The recipes.** `CONTRIBUTING.md`: set-up, how a change is checked (the CI, the parity
  check and how to update its baseline from a pull request's own run), and the steps for a
  bug fix, a demo bug build, a target, an adapter key, a chip family and a decision record.
