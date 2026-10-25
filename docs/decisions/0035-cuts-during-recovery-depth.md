# Cuts during recovery (depth)

2026-10-11

One cut followed by an undisturbed recovery is not the whole story: recovery writes flash
too, and power can fail again while it does. `runner.explore()` goes level by level:

1. a state a cut left behind is powered up and its recovery is traced, like an update;
2. cuts are planned over that trace with the same planner;
3. each gives a flash state (the parent's flash with the recovery replayed to that point);
4. a state already tested, at any level, is skipped: the same flash is the same test;
5. each new state is powered up and judged, and becomes a parent for the next level.

Two things keep this honest and affordable:
- **The first new cut of every recovery is made for real** in the emulator, and the computed
  state is checked against it byte for byte (`SelfCheckFailed` otherwise). The rest are
  powered up from the computed state directly, which skips re-running the recovery up to the
  cut. That is sound for the same reason the planner's reduction is: only flash survives.
- **Known states are skipped.** A bootloader that recovers by simply starting the update
  again lands, when cut a second time, on states a first cut already produced.

Limits, stated plainly:
- Parents are chosen with the depth plan (`phases`, 2 samples per long phase by default), not
  from every first-cut state, or the count would be the square of the update's length.
- The state space need not be finite. The demo's floor record carries a sequence number that
  grows with every install attempt, so every extra level finds new states. `levels` bounds
  the depth (default 2) and `max_states` the count (default 2000); a run that hits the cap
  says so.
- Torn states are not explored deeper.

Use: `scenario.depth: 2` (or a mapping with `levels`, `mode`, `per_phase`, `small`,
`max_states`), or `--depth 2`. Results are named by lineage, `op-7 > op-58`, and counted on
their own line.

Proof that depth earns its place, measured 2026-10-11 with an eighth demo bug build,
`bug-retry_limit` (give up on an update after two interrupted attempts, a common way to stop
boot loops):
- one cut, `plan: every` plus torn states: 168/168 clean cuts and 489/489 torn states pass;
- `depth: 2`: fails at `op-1 > op-1`. The first cut leaves attempt one recorded, the recovery
  records attempt two, a second cut right there makes the next boot give up, and the update
  is lost for good (`the installed image is v1; this scenario accepts only v2`).
