# The Three-Tier self-update, cut at every distinct flash state

2026-10-12

Run on GitHub's runners with the `exhaustive` workflow (run 38242798665), 20 shards,
`--plan every --real-every 25`, Renode 1.17.0, bootloader v2.0.0 with its test keys, BrickProof
at commit e6f8191. It took 2 h 46 min from start to the last shard.

- the update: 20,574 flash operations, 12,109 distinct flash states
- cuts: 12,109, one at every state. 520 were made in the emulator, each compared byte for
  byte with the state the golden run predicts; 11,589 were powered up from that computed state
- failed: 0. All 20 shards reported, and their cuts add up to the whole campaign

What this does and does not say. Every clean single power cut the update can meet leaves the
bootloader recovering to an approved image, in the emulator, with the chip rules modelled
here. Torn states and second cuts during recovery were not part of this run; CI covers those
on the planned sample (torn at every sampled cut, depth 2), and the tail after the reset was
done with torn states at every operation. Nothing here has been checked against the board.

The count of distinct states is higher than the 11,874 of earlier notes for two reasons: the
tail after the firmware's own reset is now part of the update, and the models no longer infer
the address of a program that wrote what was already there.
