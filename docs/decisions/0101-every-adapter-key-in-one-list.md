# Every adapter key in one list

2026-10-26

The parser reads the keys it needs and passed over anything else in silence. An adapter
with `boot_setle: 3` or `flash: {write_units: 4}` got the default and a clean
`brickproof check`: "all good". A first-time user's typo meant a run that tested something
other than what they wrote, with nothing to say so.

`adapter_keys.py` now holds every key an adapter may have, 117 of them, as one nested
schema: a value, a mapping with known keys, a list of such mappings, or a mapping of the
user's own names (pins, images, driver options). `unknown()` walks an adapter (after
`extends:` is merged) and names every other key with the nearest real one. `load()` keeps
them on the adapter, `brickproof check` fails on each ("boot_setle: not a key BrickProof
knows, so it would be ignored. Did you mean 'boot_settle'?"), and `brickproof run`, which
makes the same checks before it starts an emulator, refuses too. That is stricter than
before on purpose: an adapter that ran with a stray key now stops and says which.

All 84 adapters here use only known keys. A test also checks that the adapter reference
mentions every key in the schema; it found four that were not documented (`oracle.run_in`,
`oracle.interval`, `scenario.check_states`, `scenario.torn_seed`), now in its "whole file"
listing.

This is not the parser rewritten from the schema: the parser's checks of values (ranges,
chip rules, required keys) are many and each says exactly what is wrong, and they stay.
