# Demo speed

2026-10-10

About 6 s per cut on the demo (vs 45 s on Three-Tier, whose recovery redoes a 40 KB copy).
Most of it is per-command monitor round trips, not emulation: one cut is about 30 monitor
commands plus three boots. Worth profiling before the planner work, because it multiplies
every campaign.
