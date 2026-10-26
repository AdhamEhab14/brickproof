# Releasing

1. Set the version in one place, `__version__` in `src/brickproof/__init__.py` (the package
   reads it from there), turn `## Unreleased` in `CHANGELOG.md` into its section, and set the
   GitHub Action examples in `README.md` and `docs/guide/results-and-ci.md` to the new tag.
   `tests/test_version.py` fails until all of these agree. Merge that to `main` with all
   checks green.
2. Tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

The `Release` workflow then builds the sdist and the wheel, checks the wheel installs and
brings the demo, creates the GitHub release with the changelog section as its text, and pushes
the Docker image to `ghcr.io/adhamehab14/brickproof`.

## PyPI

The package name is `brickproof-fw` (`brickproof` on PyPI belongs to an unrelated project).
The command is still `brickproof`.

Uploading is off until it has been set up once, by the account that will own the project:

1. On PyPI, add a *pending trusted publisher* for project `brickproof-fw`: owner `AdhamEhab14`,
   repository `brickproof`, workflow `release.yml`, environment `pypi`.
2. In the GitHub repository settings, create an environment named `pypi`, and a repository
   variable `PYPI_PUBLISH` with the value `true`.

From the next tag on, the `pypi` job uploads the same files the GitHub release carries. No
token is stored anywhere: PyPI trusts the workflow's identity.
