# A locked-up CPU is a failed cut, not a crash

2026-10-10

Found by the `trust_header` bug build: a cut at op 15 leaves a valid-looking header over an
erased body, the bootloader jumps to 0xFFFFFFFF, and the core faults while fetching its fault
vector. Renode's virtual time then stops advancing, so `RunFor` never returns, and BrickProof
died with a socket timeout (exit 3). On silicon this is a locked-up, dead device.

Now `run_for` has a wall-clock limit (60 s + 120 x the virtual seconds asked for). Past it,
the session raises `MachineHung`, the runner marks the cut FAIL ("the device locked up"),
restarts Renode in place (same session object, so drivers keep working) and moves on.
Cost: about 2 minutes per hung cut. Fine while hangs are rare; revisit if a target hangs a lot.
