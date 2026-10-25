# Flash storage libraries (plan item 18)

2026-10-16

**What is judged.** A store promises less than a bootloader: not "one of two images", but
"what I said I stored is there". The `storage` driver checks exactly that. The firmware runs
a fixed workload (80 writes and deletes over 8 keys) and says "C <step>" when each call
returned. Values carry their key, generation and length and a pattern made from them, so a
read tells a whole value from a half-written or mixed-up one.

**Which steps had finished, at any cut.** The verdict needs the commits made before the cut,
also for cuts that are computed or torn (never run in that emulator), so reading the UART at
cut time is not enough. Before the campaign the driver runs the workload one step at a time
("S" commands) and notes the flash operation count before and after each step. The workload
is deterministic, which the golden run's self-check already relies on, so a cut before
operation N has finished every step that ended at or before N; the step that started and had
not ended may or may not have taken effect, and both values are accepted. The runner now
tells a driver which update operation each result was cut at (`judging()`): the cut's
operation, the torn state's, or for cuts in a row the first cut's.

**After a cut**, three checks: the store mounts and was not formatted again; every key holds
its last finished value or the one under way, and nothing reads back half-written or fails
to read; and the store takes a new write (the probe key) that is still there after another
power cycle with the other keys unchanged. The last check is what catches a store that
mounts fine but has a damaged write position.

**The workload firmware** is one Zephyr app built four ways (NVS, ZMS, settings on FCB,
littlefs), on the nRF52840 DK, built once on a GitHub runner and committed as prebuilt like
MCUboot. Two things had to change for Renode: the DK's external QSPI flash is disabled (Renode
does not model the QSPI controller and Zephyr's driver waits for it at start-up for ever),
and the oracle's `.bin` files are objcopy's output from the ELF, not Zephyr's `zephyr.bin`,
which fills a gap between sections with 0xFF where loading the ELF leaves zeros. littlefs
needed its cache raised to 256 bytes so the values stay inline (with 64, every file takes a
4 KB block and 8 files do not fit 8 blocks), and a littlefs file left empty by a cut between
its creation (committed at open) and its data (committed at close) is read as absent.

**Results** (every distinct flash state cut, this PC, 6 emulators): NVS 2,158 of 2,158 (17
min), plus 754 cuts and 2,253 torn states with the phases plan; littlefs 3,228 of 3,228 (28
min); ZMS 130 of 2,327: every cut inside a value's data or ATE leaves the next write landing
on the half-written words, which on the nRF52 (two writes per word, old AND new) reads back
wrong. That is the open report zephyrproject-rtos/zephyr#121747; booting the exported op-5
state shows the overlap word by word.

**CI** runs NVS and littlefs with the adapters' phases plan, expecting no failure, and ZMS
with `--fail-fast`, expecting exit code 1 until #121747 is fixed upstream.
