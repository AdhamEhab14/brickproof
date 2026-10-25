# Each emulator gets its own temp folder; start-up is one at a time

2026-10-11

With twelve emulators, Renode died at `LoadPlatformDescription` with "Access is denied" from
its temporary-files manager. Not a race between starting processes (it happened with starts
serialised): Renode keeps `renode-<pid>` folders in the temp directory and, on start-up,
looks up the process of every one it finds. Thirty `renode-<pid>-crash` folders were lying
there from Renodes killed earlier in this work, and Windows had reused some of those pids for
protected processes, whose look-up is refused.

- every session starts Renode with `TMP`/`TEMP`/`TMPDIR` pointing into its own work folder,
  so it sees no other instance's leftovers, and its own go when the work folder is removed;
- Renodes are brought up one at a time (the whole machine creation, not only the process
  start), and a failed start is tried again, three times in all;
- the leftovers in the shared temp folder were removed.

Twelve emulators then start and run the Three-Tier target (setup 77 s).
