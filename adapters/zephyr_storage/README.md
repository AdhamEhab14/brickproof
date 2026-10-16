# Zephyr storage libraries

Zephyr's flash stores on an nRF52840 DK, each running the same workload, and judged by
BrickProof's built-in `storage` driver.

| Adapter | Store | Where |
|---|---|---|
| `nvs.yaml` | NVS | 3 sectors of 4 KB at 0xF8000 |
| `zms.yaml` | ZMS | 3 sectors of 4 KB at 0xF8000 |
| `settings_fcb.yaml` | the settings subsystem on its FCB backend | 3 sectors of 4 KB at 0xF8000 |
| `littlefs.yaml` | littlefs | the 32 KB storage partition at 0xF8000 (8 blocks) |

The workload (`app/`) writes and deletes 8 keys in 80 steps: values of 20 to 200 bytes,
each holding its key, its generation and a pattern made from both, so a read can tell a
whole value from a half-written one. The stores are small on purpose: the workload fills
them more than once, so each one reclaims space (garbage collection, rotation, compaction)
while the power can go.

Before the cuts the driver runs the workload a step at a time and notes the flash
operations each step spans. After a cut it knows which steps had finished and checks:

- the store mounts, and was not formatted again;
- every key holds its last finished value, or the one under way; nothing half-written comes
  back and nothing fails to read;
- the store takes a new write, which is still there after one more power cycle, with the
  other keys unchanged.

## Running it

The firmware is committed in `prebuilt/` (see its README), so this needs nothing but
BrickProof and Renode:

```bash
brickproof run adapters/zephyr_storage/nvs.yaml --plan every -j 6
```

To build it yourself: `python adapters/zephyr_storage/build.py <zephyr workspace> <out>`,
with the `hal_nordic` and `littlefs` modules in the workspace. The board overlay in
`app/boards/` turns off the DK's external QSPI flash, which is not used and which Renode
does not model.

| File | What |
|---|---|
| `nvs.yaml`, `zms.yaml`, `settings_fcb.yaml`, `littlefs.yaml` | one adapter per store |
| `app/` | the workload: one source, `nvs.conf` / `zms.conf` / `settings_fcb.conf` / `littlefs.conf` pick the store |
| `build.py` | builds all four for the board |
| `prebuilt/nrf52840/` | the four builds |

## What it found

Zephyr v4.2.0, littlefs module `8f5ca347`, on the nRF52840 model (whole 32-bit word
programs, at most two writes to a word between erases), 2026-10-16.

**NVS: no failure.** 2,159 flash operations, one garbage collection. All 2,158 distinct
flash states cut, every one recovered; with the phases plan, 754 cuts and 2,253 torn states
(words and pages left half written), all recovered.

**littlefs: no failure.** 3,403 flash operations, three block erases while it compacts its
metadata. All 3,228 distinct flash states cut, every one recovered. (One thing the workload
had to learn: littlefs commits a file's creation when it is opened and its data when it is
closed, so a cut in between leaves an empty file. That is no value yet, not a mangled one,
and the workload reads it as absent. A key that had a value and comes back empty would
still fail.)

**ZMS: a write after a cut is lost.** 2,372 flash operations; of the 2,327 distinct flash
states, 130 recover. Every failing state is a cut inside a value's data or its ATE, and in
every one the store takes the next write, reports success, and reads it back wrong (or not
at all). Booting the state BrickProof exports for op 5 shows how: the first five words of a
value are written, and after the reset ZMS puts the next value's data at the same address,
over them. The nRF52 lets a word be written twice and keeps old AND new, so the probe's key
word reads 9 AND 1 = 1. This is the open report
[zephyrproject-rtos/zephyr#121747](https://github.com/zephyrproject-rtos/zephyr/issues/121747)
(foggynoggun, 2026-10-09), here on word-written flash with no setup beyond the workload.

**Settings on FCB:** results being written up.

The configs here leave each library at its defaults, apart from the sizes above and
littlefs's cache (256 bytes, so the values stay inline in its metadata and 8 keys fit 8
blocks).
