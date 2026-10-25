# Range cuts and exit codes

2026-10-10

`at_ops: {from, to, step}` expands to one cut per operation. Op counts are deterministic, so
the first cut that never fires ends its range (SKIP), and the rest are not run. Exit codes
separate "found a problem" (1) from "the tool broke" (3), so CI can expect a bug build to fail
without a crash looking like a catch.
