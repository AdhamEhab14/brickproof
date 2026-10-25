# The stall was Renode's clock missing a wake-up

2026-10-24

The 2026-10-23 entry left open what held Renode's CPU thread back. A probe on CI took .NET
stack dumps (`dotnet-stack`) of the Renode that was stuck, 14 of them over four stalls.
Every one showed the clock thread (the monitor's, running `RunFor`) in
`MasterTimeSource.RunFor` waiting on a handle, and the CPU thread waiting for its next
grant.

Renode's source explains the wait. When a time handle reports that it did not use all of
its quantum, the clock waits on `blockingEvent` before going on, with a 10 ms timeout and
the comment that without it "sometimes it blocks forever". The event is cleared when the
CPU's handle looks inactive and set again when it becomes active. At the start of a
`RunFor` the clock can read "inactive" just before the CPU thread starts and sets the
event, then clear it after it was set: it stays cleared for the rest of the slice. That
costs nothing until the CPU keeps stopping short of its quantum, which is what a flash
model does all through programming (a translation block restart when programming is
switched on, time skipped for each operation). Then every quantum waits out the 10 ms,
and a one-second slice took 430 to 565 s. That is why every stall was in a busy flash
slice, at a random one, with both threads mostly asleep.

Fix: the flash models (F1, F4, L4, nRF52) call `ReportHandleActive()` on the emulation's
master time source and on the machine's own, the call Renode itself makes when a CPU
becomes active, each time they skip time or switch the store hook on. That sets the event
again; when nothing waits on it, it does nothing. Measured on CI before: 9 stalls in 192
baselines of the F411 MCUboot update. After: none in 128 (if nothing had changed, none in
128 would happen about one time in 450), the slowest slice 23 s on the slowest runner,
and every run the same 391,974 operations, so the update itself is untouched. A unit test
checks that every flash model makes the call wherever it skips time or restarts a block.

Kept: the repeat of a hung run (2026-10-23), for any other emulator trouble; a real
lock-up still costs two runs. Not done: reporting the race to Renode upstream; that is
Adham's call.
