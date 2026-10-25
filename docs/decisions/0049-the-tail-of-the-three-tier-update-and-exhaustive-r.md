# The tail of the Three-Tier update, and exhaustive runs off the laptop

2026-10-12

**The tail.** The 47 operations after the firmware's own reset (state page rewritten, Slot B
erased), which the emulator never reached before the reset fix, were each cut on their own:
47/47 recovered, and 90/90 torn states of the same operations survived. Run locally with the
exact-program models, Renode 1.17.0, bootloader v2.0.0.

**The exhaustive run was stopped and is not a result.** The local run with `--plan every`
got to about 5,000 of 11,874 cuts with no failure, on 12 emulators, before it was stopped to
free the machine. It also predates the reset fix and the exact-program models, so it would
have covered the update only up to the reset, with the old models. Nothing is claimed from it.

**Shards.** Twelve emulators for most of a day is not something to ask of a laptop, so a
campaign can now be split: `--shard K/N` makes every Nth cut starting with the Kth. The list
of cuts is the same in the same order on every machine, so N shards make exactly the whole
campaign (tested). A shard's report says it is one, and its regulation map counts only the
cuts it made. `.github/workflows/exhaustive.yml` runs the Three-Tier campaign at every
distinct flash state over 20 runners, started by hand, and a last job adds the shards up
and fails if a cut failed or the shards do not make the whole.
