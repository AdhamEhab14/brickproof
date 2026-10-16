# Future work

What would make BrickProof better, roughly in order of value. Written 2026-10-16, after
v0.3.0, from what the work so far turned up and a look at how others test power loss (the
MCUboot simulator, Arm Trusted Services' update tests, littlefs's emulated block device).
None of those cut power at every distinct flash state of a real firmware binary on an
emulated chip, which is what BrickProof does; the gaps below are about going further.

## Closer to real power loss

1. **Validate the torn shapes against a real supply loss** (plan item 27). The measured
   shapes come from a reset stopping an erase. A MOSFET on the Nucleo's 3.3 V, driven at a
   counted delay, would show whether a sagging supply leaves the same shapes, and how
   programs tear, which no measurement covers yet.
2. **Brown-out and slow supply ramps.** A real power loss is seconds of sagging voltage:
   the core can keep running below the level flash writes need, and a cell programmed at
   low voltage can read right now and wrong later (weak cells, poor retention). Model the
   BOR/PVD thresholds and a "weakly programmed" cell that fails a later read.
3. **Correctable ECC errors (ECCC)** on the STM32L4, and ECC on instruction fetches, not
   only data reads.
4. **Write reordering** for memories with a write cache or a translation layer (the
   littlefs block device has an "out of order" power-loss mode for this): blocks reach the
   medium in a different order than written. It matters for SD cards and managed flash,
   and would be the measured basis that SD write support is still missing.

## More chips and update mechanisms

5. **Dual-bank swap** (STM32 BFB2 on the L4, F7 and H7): an update that flips banks
   instead of copying is a common design and is not modelled.
6. **Chips Renode already runs**, each needing a flash model of ours: STM32G0 (shares the
   L4 model: cheap), STM32H7 (256-bit flash words with ECC, dual bank), STM32F7, STM32L0
   (data EEPROM, half-page programming), Microchip SAMD21/SAMD51 (NVMCTRL, RWW EEPROM),
   NXP i.MX RT1064 (execute-in-place from external NOR through FlexSPI, a big OTA platform).
   ESP32 and RP2040 are not in Renode; m33mu covers Armv8-M parts Renode lacks.
7. **m33mu parity:** option bytes in the flash image; nRF52 RESETREAS; timers frozen in
   Stop mode.

## Smarter campaigns

8. **Recovery code coverage.** Trace which bootloader branches the cuts reached and
   report the recovery paths no cut exercised; then choose extra cuts to reach them.
9. **Combined faults:** a cut while a damaged image is being checked, a cut during the
   recovery from a bit error, a cut while the link is down.
10. **Snapshots instead of replays.** Renode's save/load crashes with Python peripherals;
    with the flash models in C# a cut could restore a snapshot, making campaigns much
    faster. Sparse images would make big external chips cheap.
11. **Wear over many updates:** run update after update with endurance that degrades, and
    report when the first failure appears.

## Use and evidence

12. **Hardware-in-the-loop:** run the same plan on a real board through the power-cut rig,
    using `brickproof export` for the states.
13. **Evidence pack** for secure-update requirements (EU Cyber Resilience Act, EN 18031):
    a signed report with firmware hashes and every state tested. The wording of what a
    notified body expects should be checked against the standards themselves first.
14. **Pull-request summaries:** a short comment with what changed between two runs (new
    failures, new states), on top of the SARIF upload.
15. **More adapter generators** next to `adapter-from-zephyr`: NuttX, Mbed, the vendor SDKs'
    OTA examples.

Declined: glitch / fault-injection simulation (plan item 13), out of scope for now.
