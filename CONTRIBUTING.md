# Working on BrickProof

## Set up

```bash
git clone https://github.com/AdhamEhab14/brickproof && cd brickproof
pip install -e ".[dev]"
brickproof setup                 # Renode, for the tests that need an emulator
python tools/dev.py check        # lint and the unit tests: about 20 seconds
```

`python tools/dev.py help` lists the rest: the Renode rule tests, one campaign from the
scenario list, the parity check, the docs' links.

## How a change is checked

Every pull request runs lint, the unit tests on Python 3.10, 3.12 and 3.13, and the package
build. Unless it only touches documentation, it also runs every campaign in
[tests/scenarios.yaml](tests/scenarios.yaml) (the demo on five chips, MCUboot, Zephyr's
stores), the Three-Tier end-to-end test, the flash models' chip rules, the GitHub Action,
the Docker image and the quick start a new user follows. Then the **parity check** compares
every campaign's results (verdict, coverage, each cut's outcome) with
[tests/parity/baseline.json](tests/parity/baseline.json). `ci-ok` is the one required check.

A change that is not meant to change any result must leave parity at "every result the
same". A change that is meant to (a new chip rule, a rebuilt target) updates the baseline in
the same pull request, from that pull request's own CI run, so the diff shows exactly what
moved:

```bash
gh run download <run id> -p "reports-*" -D reports
python tools/parity.py fingerprint reports -o tests/parity/baseline.json --source "CI run <id>: <why>"
```

[docs/features.md](docs/features.md) lists every feature and what proves it; a new feature
gets its line there.

## Recipes

**Fix a bug.** Write the test that fails first: against the simulated device in
`tests/fake_device.py` when it is about the campaign's logic (`tests/test_runner.py` shows
how), in `tests/renode/` when it is about a chip rule, or as a scenario when it takes a
whole campaign. Then fix it, `python tools/dev.py check`, and open the pull request.

**Add a bug build to the demo.** In
[examples/demo_ab_bootloader/firmware](examples/demo_ab_bootloader/firmware): a `BUG_...`
option in `bootloader/main.c` and its line in `build.py`, then
`python build.py --prebuilt` (it refreshes `prebuilt/` and its `SHA256SUMS`). Add the adapter
in the chip's folder, extending the correct build (`extends: f411.yaml`, a few lines), and one
line in `tests/scenarios.yaml` with `expect: 1` and `--fail-fast`. Its first CI run reports
it as a new campaign; add it to the baseline from that run.

**Add a target.** One folder in [adapters/](adapters) laid out as
[adapters/README.md](adapters/README.md) says: a README (what is updated, Running it, What it
found), the adapter, a `driver.py` if a host drives the update, and for CI a `prebuilt/` with
how it was built and a `SHA256SUMS`. Then its row in `adapters/README.md` and its lines in
`tests/scenarios.yaml`.

**Add an adapter key.** Read it in `src/brickproof/adapter.py`, add it to
`src/brickproof/adapter_keys.py` (keys not there are refused as typos), and document it in
[docs/reference/adapter.md](docs/reference/adapter.md): `tests/test_adapter_keys.py` checks
both.

**Add a chip family.** A flash controller model in `src/brickproof/models/` (start from the
closest one; it keeps the test registers of `engine/flash_regs.py` and the
`# @FLASH_COMMON@` line where the shared helpers go), a platform in
`src/brickproof/platforms/`, the chip in `CHIPS` in `adapter.py` and in
`engine/workdir.py`, rule tests in `tests/renode/`, and the demo built for it
(`firmware/common/chip_<name>.h` and an adapter folder) with its scenarios.

**Record a decision.** When a choice needs its reasons kept (a measurement, a trade-off,
something tried and dropped), add the next numbered file to
[docs/decisions/](docs/decisions/README.md) and its row in the index.

## Releasing

[docs/releasing.md](docs/releasing.md). The version is in one place,
`src/brickproof/__init__.py`.

## Style

Code and comments say what is done and why, in plain words, the way the code around them
does. Documentation too, without em dashes. Commit messages say what changed and why it was
worth changing.
