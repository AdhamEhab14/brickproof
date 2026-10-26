# Decisions

One record per design choice, numbered in the order they were made, so a later reader
knows why things are the way they are and what was measured. A new decision gets the next
number: `NNNN-a-few-words.md`, with its title, the date and the reasons.

| No. | Date | Decision |
|---|---|---|
| 0001 | 2026-10-09 | [Name and package](0001-name-and-package.md) |
| 0002 | 2026-10-09 | [Licence: Apache-2.0](0002-licence-apache-2-0.md) |
| 0003 | 2026-10-09 | [Port the harness, don't rewrite it](0003-port-the-harness-don-t-rewrite-it.md) |
| 0004 | 2026-10-09 | [Flash geometry by text rewrite](0004-flash-geometry-by-text-rewrite.md) |
| 0005 | 2026-10-09 | [Everything Renode loads goes into a work folder](0005-everything-renode-loads-goes-into-a-work-folder.md) |
| 0006 | 2026-10-09 | [Adapter = YAML + driver.py](0006-adapter-yaml-driver-py.md) |
| 0007 | 2026-10-09 | [Every cut starts from the same image](0007-every-cut-starts-from-the-same-image.md) |
| 0008 | 2026-10-09 | [W1 cuts are real cuts only](0008-w1-cuts-are-real-cuts-only.md) |
| 0009 | 2026-10-09 | [Liveness is still judged by the driver (temporary)](0009-liveness-is-still-judged-by-the-driver-temporary.md) |
| 0010 | 2026-10-09 | [W1 speed measurement (the kill-criterion number)](0010-w1-speed-measurement-the-kill-criterion-number.md) |
| 0011 | 2026-10-10 | [A bundled demo target comes before the W2 tracer (roadmap change)](0011-a-bundled-demo-target-comes-before-the-w2-tracer-r.md) |
| 0012 | 2026-10-10 | [Built-in `staged_slot` driver](0012-built-in-staged-slot-driver.md) |
| 0013 | 2026-10-10 | [A reset re-initialises the flash model](0013-a-reset-re-initialises-the-flash-model.md) |
| 0014 | 2026-10-10 | [Flash starts erased (0xFF)](0014-flash-starts-erased-0xff.md) |
| 0015 | 2026-10-10 | [Range cuts and exit codes](0015-range-cuts-and-exit-codes.md) |
| 0016 | 2026-10-10 | [Demo speed](0016-demo-speed.md) |
| 0017 | 2026-10-10 | [A locked-up CPU is a failed cut, not a crash](0017-a-locked-up-cpu-is-a-failed-cut-not-a-crash.md) |
| 0018 | 2026-10-10 | [Demo results (local, Windows 11, Renode 1.17.0)](0018-demo-results-local-windows-11-renode-1-17-0.md) |
| 0019 | 2026-10-10 | [Where a cut's time goes (profiled)](0019-where-a-cut-s-time-goes-profiled.md) |
| 0020 | 2026-10-10 | [The emulated chip gets the real chip's memory sizes](0020-the-emulated-chip-gets-the-real-chip-s-memory-size.md) |
| 0021 | 2026-10-10 | [Real RAM size was not enough: memory guards](0021-real-ram-size-was-not-enough-memory-guards.md) |
| 0022 | 2026-10-10 | [Baseline run before any cut](0022-baseline-run-before-any-cut.md) |
| 0023 | 2026-10-10 | [Three-Tier adapter follows v2.0.0, and CI pins the tag](0023-three-tier-adapter-follows-v2-0-0-and-ci-pins-the.md) |
| 0024 | 2026-10-10 | [Flash model state lives in memory, not in script variables](0024-flash-model-state-lives-in-memory-not-in-script-va.md) |
| 0025 | 2026-10-10 | [Golden-run tracer](0025-golden-run-tracer.md) |
| 0026 | 2026-10-10 | [A program cut used to land AFTER its halfword. Now it lands before.](0026-a-program-cut-used-to-land-after-its-halfword-now.md) |
| 0027 | 2026-10-10 | [Every cut is checked against the golden run replayed](0027-every-cut-is-checked-against-the-golden-run-replay.md) |
| 0028 | 2026-10-10 | [The flash model enforces the chip's programming rules](0028-the-flash-model-enforces-the-chip-s-programming-ru.md) |
| 0029 | 2026-10-10 | [The runner is tested without an emulator](0029-the-runner-is-tested-without-an-emulator.md) |
| 0030 | 2026-10-10 | [Renode charges per monitor line, so commands share lines](0030-renode-charges-per-monitor-line-so-commands-share.md) |
| 0031 | 2026-10-11 | [The oracle](0031-the-oracle.md) |
| 0032 | 2026-10-11 | [A session never leaves its emulator behind](0032-a-session-never-leaves-its-emulator-behind.md) |
| 0033 | 2026-10-11 | [The cut planner](0033-the-cut-planner.md) |
| 0034 | 2026-10-11 | [Torn operations](0034-torn-operations.md) |
| 0035 | 2026-10-11 | [Cuts during recovery (depth)](0035-cuts-during-recovery-depth.md) |
| 0036 | 2026-10-11 | [Depth 2 on the Three-Tier bootloader (measured)](0036-depth-2-on-the-three-tier-bootloader-measured.md) |
| 0037 | 2026-10-11 | [Reports and reproducing one result](0037-reports-and-reproducing-one-result.md) |
| 0038 | 2026-10-11 | [What the lock-up really is, and noticing it sooner](0038-what-the-lock-up-really-is-and-noticing-it-sooner.md) |
| 0039 | 2026-10-11 | [Renode's shared command history was most of the cost of everything](0039-renode-s-shared-command-history-was-most-of-the-co.md) |
| 0040 | 2026-10-11 | [Several emulators (`--jobs`)](0040-several-emulators-jobs.md) |
| 0041 | 2026-10-11 | [`real_every`: most planned cuts from the computed state](0041-real-every-most-planned-cuts-from-the-computed-sta.md) |
| 0042 | 2026-10-11 | [Each emulator gets its own temp folder; start-up is one at a time](0042-each-emulator-gets-its-own-temp-folder-start-up-is.md) |
| 0043 | 2026-10-11 | [Write protection and option bytes](0043-write-protection-and-option-bytes.md) |
| 0044 | 2026-10-11 | [Regulation map, and how BrickProof is handed to someone else](0044-regulation-map-and-how-brickproof-is-handed-to-som.md) |
| 0045 | 2026-10-11 | [A second chip family (STM32F411), and what it took](0045-a-second-chip-family-stm32f411-and-what-it-took.md) |
| 0046 | 2026-10-11 | [Flash operations take time, and an update's wear is counted](0046-flash-operations-take-time-and-an-update-s-wear-is.md) |
| 0047 | 2026-10-12 | [Resets the firmware causes now reboot it, and the hardware watchdog](0047-resets-the-firmware-causes-now-reboot-it-and-the-h.md) |
| 0048 | 2026-10-12 | [The flash models hear each program store](0048-the-flash-models-hear-each-program-store.md) |
| 0049 | 2026-10-12 | [The tail of the Three-Tier update, and exhaustive runs off the laptop](0049-the-tail-of-the-three-tier-update-and-exhaustive-r.md) |
| 0050 | 2026-10-12 | [The Three-Tier self-update, cut at every distinct flash state](0050-the-three-tier-self-update-cut-at-every-distinct-f.md) |
| 0051 | 2026-10-12 | [Flash is also at address 0](0051-flash-is-also-at-address-0.md) |
| 0052 | 2026-10-12 | [An oracle for a bootloader and a program side by side](0052-an-oracle-for-a-bootloader-and-a-program-side-by-s.md) |
| 0053 | 2026-10-12 | [Clocks follow the firmware, pins have a level, a dead device is noticed](0053-clocks-follow-the-firmware-pins-have-a-level-a-dea.md) |
| 0054 | 2026-10-12 | [An external SPI NOR flash chip](0054-an-external-spi-nor-flash-chip.md) |
| 0055 | 2026-10-13 | [Block protection in the external flash chip](0055-block-protection-in-the-external-flash-chip.md) |
| 0056 | 2026-10-13 | [A slow emulator is not a dead device](0056-a-slow-emulator-is-not-a-dead-device.md) |
| 0057 | 2026-10-13 | [MCUboot](0057-mcuboot.md) |
| 0058 | 2026-10-14 | [A third chip family, the nRF52840](0058-a-third-chip-family-the-nrf52840.md) |
| 0059 | 2026-10-14 | [Torn erases, measured](0059-torn-erases-measured.md) |
| 0060 | 2026-10-15 | [The demo on the nRF52840](0060-the-demo-on-the-nrf52840.md) |
| 0061 | 2026-10-15 | [Exporting a failing state](0061-exporting-a-failing-state.md) |
| 0062 | 2026-10-15 | [The torn-write kit in the repository](0062-the-torn-write-kit-in-the-repository.md) |
| 0063 | 2026-10-15 | [Re-running the fixes from OpenBLT and wolfBoot](0063-re-running-the-fixes-from-openblt-and-wolfboot.md) |
| 0064 | 2026-10-16 | [MCUboot and the nRF52840 in CI](0064-mcuboot-and-the-nrf52840-in-ci.md) |
| 0065 | 2026-10-16 | [Flash storage libraries (plan item 18)](0065-flash-storage-libraries-plan-item-18.md) |
| 0066 | 2026-10-16 | [Bad update content (plan item 12)](0066-bad-update-content-plan-item-12.md) |
| 0067 | 2026-10-16 | [A broken link instead of lost power (plan item 14)](0067-a-broken-link-instead-of-lost-power-plan-item-14.md) |
| 0068 | 2026-10-16 | [Bit errors at rest (plan item 16)](0068-bit-errors-at-rest-plan-item-16.md) |
| 0069 | 2026-10-16 | [Worn pages (plan item 15)](0069-worn-pages-plan-item-15.md) |
| 0070 | 2026-10-16 | [Power cuts many times in a row (plan item 17)](0070-power-cuts-many-times-in-a-row-plan-item-17.md) |
| 0071 | 2026-10-16 | [SARIF output (plan item 22)](0071-sarif-output-plan-item-22.md) |
| 0072 | 2026-10-16 | [Soak runs (plan item 21)](0072-soak-runs-plan-item-21.md) |
| 0073 | 2026-10-16 | [Adapters from a Zephyr build (plan item 20)](0073-adapters-from-a-zephyr-build-plan-item-20.md) |
| 0074 | 2026-10-16 | [Settings on FCB, written up](0074-settings-on-fcb-written-up.md) |
| 0075 | 2026-10-16 | [Testing the chip rules one by one, and the F1's option byte check (plan item 6)](0075-testing-the-chip-rules-one-by-one-and-the-f1-s-opt.md) |
| 0076 | 2026-10-16 | [STM32F4 details: PGAERR, PCROP, RDP level 2 (plan item 5)](0076-stm32f4-details-pgaerr-pcrop-rdp-level-2-plan-item.md) |
| 0077 | 2026-10-16 | [The SPI NOR chip's own protection (plan item 8)](0077-the-spi-nor-chip-s-own-protection-plan-item-8.md) |
| 0078 | 2026-10-16 | [FCB is covered through settings](0078-fcb-is-covered-through-settings.md) |
| 0079 | 2026-10-16 | [An I2C EEPROM (plan item 10)](0079-an-i2c-eeprom-plan-item-10.md) |
| 0080 | 2026-10-16 | [The nRF52's UICR, partial erase and ACL (plan item 7)](0080-the-nrf52-s-uicr-partial-erase-and-acl-plan-item-7.md) |
| 0081 | 2026-10-16 | [4-byte addresses; no quad mode (plan item 9)](0081-4-byte-addresses-no-quad-mode-plan-item-9.md) |
| 0082 | 2026-10-16 | [The STM32L4, and ECC (plan item 11)](0082-the-stm32l4-and-ecc-plan-item-11.md) |
| 0083 | 2026-10-16 | [m33mu, from wolfBoot's maintainer (PR #35)](0083-m33mu-from-wolfboot-s-maintainer-pr-35.md) |
| 0084 | 2026-10-16 | [Low-power modes (plan item 4)](0084-low-power-modes-plan-item-4.md) |
| 0085 | 2026-10-16 | [Reset during an erase is covered by the torn states (plan item 3)](0085-reset-during-an-erase-is-covered-by-the-torn-state.md) |
| 0086 | 2026-10-16 | [SD cards, evaluated and left out (rest of plan item 10)](0086-sd-cards-evaluated-and-left-out-rest-of-plan-item.md) |
| 0087 | 2026-10-18 | [The oracle waits for the device to stay up](0087-the-oracle-waits-for-the-device-to-stay-up.md) |
| 0088 | 2026-10-19 | [Checks before the emulator, and image layouts read from the image](0088-checks-before-the-emulator-and-image-layouts-read.md) |
| 0089 | 2026-10-23 | [A hung run is run again before the device is called locked up](0089-a-hung-run-is-run-again-before-the-device-is-calle.md) |
| 0090 | 2026-10-24 | [The stall was Renode's clock missing a wake-up](0090-the-stall-was-renode-s-clock-missing-a-wake-up.md) |
| 0091 | 2026-10-24 | [The ARM toolchain is cached in CI](0091-the-arm-toolchain-is-cached-in-ci.md) |
| 0092 | 2026-10-25 | [A parity check before restructuring](0092-a-parity-check-before-restructuring.md) |
| 0093 | 2026-10-25 | [CI from a manifest, with one required check](0093-ci-from-a-manifest-with-one-required-check.md) |
| 0094 | 2026-10-26 | [A core out of Thumb state is locked up](0094-a-core-out-of-thumb-state-is-locked-up.md) |
| 0095 | 2026-10-25 | [The demo, one folder per chip](0095-the-demo-one-folder-per-chip.md) |
| 0096 | 2026-10-25 | [Every target folder the same, and committed firmware checked](0096-every-target-folder-the-same-and-committed-firmwar.md) |
| 0097 | 2026-10-25 | [The docs, split by what a reader wants](0097-the-docs-split-by-what-a-reader-wants.md) |
| 0098 | 2026-10-26 | [The runner, one module per part](0098-the-runner-one-module-per-part.md) |
| 0099 | 2026-10-26 | [RenodeSession, one file per part](0099-renodesession-one-file-per-part.md) |
| 0100 | 2026-10-26 | [The flash models share their common helpers](0100-the-flash-models-share-their-common-helpers.md) |
