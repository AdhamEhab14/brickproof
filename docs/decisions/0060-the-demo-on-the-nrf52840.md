# The demo on the nRF52840

2026-10-15

The demo bootloader builds for a third chip with `-DNRF52` (`common/chip_nrf52.h`). Flash
map in 4 KB pages: bootloader 16 KB at 0, the two rollback-floor pages at 0x4000 and 0x5000,
Slot A at 0x10000 and Slot B at 0x30000, 128 KB each. There are no keys: `flash_unlock()`
does nothing, and each erase or program sets CONFIG (Een or Wen) and puts it back to Ren.
The UART is UARTE0, which sends by EasyDMA from RAM only, so the text goes through a RAM
buffer, a line at a time. The watchdog is only fed: the nRF WDT cannot change its timeout
once it runs.

Builds left out on this chip, and why: `no_unlock` (no keys to forget), `self_lock` (needs
the UICR, not modelled yet), `watchdog` (a 4 KB page erase takes 85 ms), `resume_copy` (a
half-written word may be written once more, as on the F4), and the external-flash builds
(F411 only). One build is new, `nwrite`, for the rule this chip adds: install progress kept
by clearing one more bit of the same word after each step, so the third step is a third
write.

The STM32 binaries are byte for byte what they were before the change (checked with
objcopy on every bootloader and app).

**Checked** in Renode: the correct build, 98 cuts over 98 distinct flash states, all
recovered to v2. Caught: `consume_first` (cut at the Slot A erase), `trust_header` (cut in
the copy: locked up), `naive_floor` (rollback accepted), `pop_after_switch` (bus fault at
0x20040000, baseline), `no_erase` (baseline), `early_unpg` (store with CONFIG not Wen,
baseline), `nwrite` (third write refused, baseline), and `retry_limit` with `--depth 2` (every
single cut recovers, 99 of them; two cuts in a row leave v1). `hold_pg`, the correct build
with CONFIG held at Wen, recovered at all 98 cuts.
