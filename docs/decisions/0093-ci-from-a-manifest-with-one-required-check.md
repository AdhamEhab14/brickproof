# CI from a manifest, with one required check

2026-10-25

CI was 90 jobs and 387 runner-minutes on every push, 45 to 65 minutes from push to result.
60 of the jobs were one demo build each and spent most of their time setting up Python and
Renode for a campaign of a few seconds to a few minutes. The branch ruleset named 78 of them,
so a new bug build meant a YAML file, a matrix entry and a ruleset edit, and a pull request
that only touched documentation ran all 90.

Now `tests/scenarios.yaml` lists every campaign with its flags, the exit code it must give
and the minutes it took on a runner (taken from the reports of the green run the parity
baseline comes from). `tools/scenarios.py` shares the list out over jobs, longest first into
the emptiest job, runs each campaign with a time limit of three times its usual minutes, and
checks every exit code; one stuck campaign is stopped and counted, and the rest of its job
still runs and uploads. Eight Renode jobs take about 34 minutes each, about as long as the
Three-Tier e2e job, the longest single one, so more jobs would not finish sooner. The H563
campaigns are one m33mu job.

The flags of every campaign are the ones the old matrices used, so the parity check applies
unchanged: the new CI is accepted only once its reports give every result of the baseline.

`.github/actions/setup` installs Python and BrickProof and takes Renode, m33mu and Arm's
toolchain from the cache, in place of the same steps copied into every job; the unit job no
longer installs a compiler with apt either. A `changes` job skips the emulator jobs when a
pull request touches only documentation. Main, every night and a manual run get everything.
`ci-ok` is the one required check: it passes when every job that had to run passed.

The action job now runs on both emulators, so the action's own m33mu build is still used.
Its m33mu campaign is also a scenario, so its report stays out of the parity download.
