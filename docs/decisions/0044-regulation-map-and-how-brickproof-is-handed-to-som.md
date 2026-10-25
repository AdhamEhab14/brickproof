# Regulation map, and how BrickProof is handed to someone else

2026-10-11

**Regulation map.** A report now says where its evidence fits in UN R156 (7.2.1.1, 7.2.2.1.1,
7.2.2.1.2) and the Cyber Resilience Act (Annex I, Part I (2)(f) and (2)(h), Part II (7)). The
clause wording was read from the UNECE consolidated text and the Official Journal on
2026-10-11; the summaries are paraphrases with links, and `docs/regulations.md` gives the
sources. Per clause a run is marked shown, not shown or not tested, worked out from the run:
a failing run shows nothing, the integrity clauses need the oracle, and the power check of
7.2.2.1.2 is outside what a run can show. It is headed "a map, not a verdict", because whether
a regulation is met is not a tool's call.

**The demo is in the package.** `examples/demo_ab_bootloader` is also the package
`brickproof.demo` (setuptools `package-dir`), so `pip install` brings it and `brickproof demo`
runs with nothing else to fetch. Checked by installing the wheel into a clean environment.

**Three ways in, each built and used in CI:** the wheel and sdist (`package` job: builds
both, installs the wheel clean, rebuilds a wheel from the sdist and compares the file lists),
the GitHub Action (`action.yml`, composite; the `action` job uses it as another repository
would; inputs reach the script through the environment, not by being pasted in), and the
Docker image (`docker` job builds it, runs the demo inside, and checks a bug build exits 1).

**Release.** A `v*` tag builds, checks the tag matches the package version, creates the GitHub
release from the changelog section, and pushes the image to GHCR. The PyPI upload uses trusted
publishing and stays off until the repository variable `PYPI_PUBLISH` is `true`, because the
PyPI side has to be set up once by the account that owns the project (`docs/releasing.md`).
