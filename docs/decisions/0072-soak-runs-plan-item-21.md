# Soak runs (plan item 21)

2026-10-16

The planned campaign covers what a plan can: every distinct state, or the edges and samples
of long phases. A soak spends a time budget on random tests instead, for long unattended
runs on a machine with nothing else to do. `--soak MINUTES --seed N` draws, after the
baseline, a random operation and either a clean cut before it (60%) or that operation left
half done in a random torn shape (40%; a shape that does not apply there becomes a clean
cut). Each test powers up from the computed state, which every real cut checks, so a test
costs one boot. Draws come in batches of one per emulator and stop at the first failure,
which keeps its usual reproduce and export commands. The same seed draws the same tests.

Not in a soak yet: content faults and cuts in a row. Content faults are a fixed small set,
better run by the plan, and a cut during recovery needs that recovery traced first, which
is the depth exploration's job.

**Checked** in Renode: `brickproof demo resume_copy --soak 10 --seed 1` (a bug only a torn
program shows) failed at its 10th test, a torn program at op 73, after about 10 seconds. The
correct demo with `--soak 3 --seed 1`: 1,038 tests (885 cuts, 153 torn states), no failure.
