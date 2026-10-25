# Every cut is checked against the golden run replayed

2026-10-10

From the image before the update plus the trace, `trace.Replay` computes the exact flash just
before any operation. After each cut (and after the baseline) the runner compares real
emulated flash with it, on every page the update touches. A difference raises
`SelfCheckFailed` and ends the run with exit 3: either the tool is wrong (trace, rewind,
cut model) or the update differs from run to run, and in both cases the results could not be
trusted. `scenario.check_states: false` turns it off for an update that is not deterministic
(a random nonce written to flash, for example).

This is the "generated state must equal a real cut, byte for byte" cross-check from the
original harness, done for every cut instead of one hand-picked case. It also means the
replay can later stand in for a real cut where that is cheaper.
