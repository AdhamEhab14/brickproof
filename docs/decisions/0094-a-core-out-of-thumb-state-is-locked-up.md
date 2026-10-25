# A core out of Thumb state is locked up

2026-10-26

The demo's `nrf52-bug-trust_header` gave different results on different CI runs: usually
"locked up" after 3.4 minutes, once a stray-write failure after 21 minutes, and once it ran
past its 17.9-minute limit. The bug was caught every time, but a test whose length and
message depend on the runner is not one to trust.

Timing every slice of its failing cut showed why. The bootloader jumps through the
half-written image's erased reset vector (0xFFFFFFFF). On the chip that is a fault, and the
core sits in its fault handler for good: a dead device. Renode takes the jump as an
exception return (2026-10-11), and on the nRF52, where flash starts at address 0, it then
runs on with the xPSR's T bit clear: a one-instruction loop at 0x28c (`Default_Handler`),
the stack pointer at 0x20, 64 million instructions per emulated second, each costing about
4 us of wall time. A 0.3 s slice took 77 to 108 s. Whether that passed the wall-clock hang
limit depended on the runner, and when it did not, the run went on for many minutes until
an earlier exception frame written into the vector table was caught as a stray write.

A Cortex-M always runs in Thumb state; a core with T clear has faulted. So every slice of
emulated time (`run_for`, `run_until_cut`, `sample_cpu`) now reads `cpu CPSR` in the same
monitor line as its `RunFor`, at no extra round trip, and a core without the T bit is
locked up at once, before the slice's pace is learned. Healthy firmware reads 0x01000000 or
0x81000000 on every chip here. The cut now ends "locked up" every time, in about 3.5
minutes, and its result is the parity baseline's. The 41 Renode rule tests pass.

The same check changed three results, as it should. The F103, F411 and L476
`trust_header` demos had also been crawling with T clear, for 290 to 550 s, until an
exception frame landed in the vector table and was caught as a stray write. They are now
"locked up", the right name for a dead device, in about 2.5 minutes each instead of 6 to 12;
the parity baseline is updated with exactly those three messages, and their minutes in
`tests/scenarios.yaml` with the new times.
