# A bundled demo target comes before the W2 tracer (roadmap change)

2026-10-10

A new user should not have to clone and build someone else's bootloader to see the tool work.
`examples/demo_ab_bootloader` is a small A/B bootloader (under 1 KB) and app, committed
prebuilt, so `pip install` plus one command runs it with no toolchain and no board. Three
build options put back the three real bugs BrickProof found in the Three-Tier bootloader,
in the form they would take in an A/B design, so the demo shows a catch, not only a pass.
It also gives every later feature (tracer, planner, oracle) a second target from day one, so
none of them gets shaped around one bootloader by accident.

The Three-Tier bootloader stays as the real-world target and its own CI job.
