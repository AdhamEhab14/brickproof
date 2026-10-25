# The oracle waits for the device to stay up

2026-10-18

A review of the oracle found a false pass: four samples 20 ms apart cover 80 ms, and a
device in a reset loop with a period longer than that, banner and all, passed. Nothing
counted resets. The Renode flash models already run a handler after every machine reset
(for the hardware watchdog), so they now also count resets in state word 60, which
outlives resets; `power_cycle` clears it after its own reset. Once the oracle has seen an
accepted image running it lets `oracle.stable_for` seconds pass (default 1, above the
STM32 IWDG's reset timeout of about 0.4 s) and fails on any reset in that window, or if the
image is no longer running at the end. The second look after the driver's own checks does
not wait again. m33mu does not count resets; there only the later look is made.

Measured on `nrf52-bug-boot_loop` (a trial boot under a watchdog with a second reload
register the app does not feed): cut 98 passes with `stable_for: 0` and fails with the
default, "reset 2 time(s) in the next 1.0 s". The cost is one virtual second per verdict.

Two planner fixes from the same review. `plan.make` called a state new when the previous
operation changed flash, so a state met twice was cut twice and counted as two distinct
states; it now dedupes by content, as the depth exploration already did. And `changes()`
had no case for the nRF52's `partial_erase`, so it took each step for a no-op and the state
after it was never planned for a cut.

The first CI run with the wait put the Three-Tier e2e job past its hour: measured locally,
one virtual second there costs about 12 real seconds (the FBL polls its UART flat out), so
a cut went from 15.8 s to 28.7 s. That adapter now sets `stable_for: 0.25`. A longer wait
would not buy anything there anyway: its Boot Manager stretches the watchdog to about 26 s,
which no wait per cut could cover, and a short one still sees resets the firmware asks for.
