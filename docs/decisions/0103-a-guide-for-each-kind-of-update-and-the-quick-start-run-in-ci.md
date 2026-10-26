# A guide for each kind of update, and the quick start run in CI

2026-10-26

Testing real firmware meant reading the README, the adapter reference and a target's
README, and working out which of `init`, `adapter-from-zephyr`, `check`, `trace` and `run`
to use in what order. And no CI job ran the README's own commands the way a new user does:
`brickproof setup`, `trace` and `export` had unit tests only.

`docs/guide/` now has five steps for each kind of update: [MCUboot](../guide/mcuboot.md),
[a bootloader that installs a staged image](../guide/staged-update.md),
[an update sent over the UART](../guide/uart-protocol.md) and
[a flash storage library](../guide/storage-library.md): get the firmware, write the adapter,
check it, a quick first look, everything. Each points to a complete target in `adapters/`.

A `quickstart` CI job installs the wheel in a clean virtualenv and, in a folder outside the
repository, runs `brickproof setup` (which downloads and checks Renode), the demo with
`--quick`, a bug build that must exit 1, `trace` and `export` on the installed demo, and
`check` on an adapter with a typo, which must fail. The features list moves those from
"unit only" to proven.
