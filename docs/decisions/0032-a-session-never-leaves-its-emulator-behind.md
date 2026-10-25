# A session never leaves its emulator behind

2026-10-11

Found two idle `renode.exe` from the day before: probe scripts whose start-up had failed (a
platform Renode rejected). The constructor raised before anything could call `close()`, so
the process stayed. The handoff had warned that leftovers slow later runs.

Now: start-up is wrapped, and any failure closes the session before the error goes up.
`close()` is safe at any point and more than once. Every live session is in a weak set that
an `atexit` hook closes, for scripts that die without cleaning up. Tested with a stand-in
process, no emulator needed.
