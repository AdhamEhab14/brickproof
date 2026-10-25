# Adapters from a Zephyr build (plan item 20)

2026-10-16

Writing an MCUboot adapter by hand means copying numbers out of the board's devicetree. The
build already has them all: `zephyr/zephyr.dts` (the devicetree after every overlay) gives the
flash (base, size, write and erase block size), the RAM, the partitions and the console UART
(`/chosen`), and an STM32 board's crystal (`clk_hse`); MCUboot's `zephyr/.config` gives the
chip (`CONFIG_SOC`) and the upgrade mode (`CONFIG_BOOT_SWAP_USING_SCRATCH`, `_MOVE`, ...).
`brickproof adapter-from-zephyr` reads those two files with a small parser of the flattened
devicetree (nodes, labels, properties; no dtc needed) and writes the adapter, with the images
folder relative to it.

Only the MCUboot build is read: the app's devicetree carries the same partitions. What the
devicetree does not say is the STM32F4's sector layout, so the chip table holds it for the
parts BrickProof models. `--alive` and `--expect` name what the app prints (by default the
test app's "APP v[0-9]" and "APP v2").

**Checked**: from the Black Pill and nRF52840 DK builds (their devicetree and Kconfig are in
tests/fixtures/zephyr), the generated adapters equal adapters/mcuboot/f411.yaml and
nrf52840.yaml in every field a run uses (chip, flash layout, RAM, UART, crystal, firmware,
driver options, oracle). The generated nRF52840 adapter, run with the CI settings: 111 of 111.
