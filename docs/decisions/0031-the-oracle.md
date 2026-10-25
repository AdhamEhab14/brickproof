# The oracle

2026-10-11

Until now "did it recover?" was answered by the driver: a UART banner, a version reply. That
is the firmware vouching for the firmware. `oracle.py` judges from outside, using nothing
the firmware says, and shares no code with any target:

- **what is installed:** the bytes in flash are exactly one of the approved images (compared
  inside the flash model, so it costs one monitor line whatever the image size);
- **what is running:** the PC, sampled several times, stays inside that image, and the core's
  exception number is not a fault (2 to 6: NMI, HardFault, MemManage, BusFault, UsageFault).

An adapter lists the approved images and which of them a scenario accepts after a cut
(`accept: [v2]` = the update must not be lost; `[old, new]` = either is fine). A driver can
add images it creates at run time with `oracle_images()`.

A verdict now needs three voices to agree: the chip rules (bus fault, refused program, stray
write), the oracle, and the driver. The oracle is asked twice: after recovery, and again
after the driver's checks, because a rollback probe stages an older image and reboots.

What it caught on its first day:
- `bug-trust_header`, cuts at ops 163 to 165 (the last three halfwords of the body): the app
  boots and prints "APP v2", so the driver said PASS. The oracle: "no approved image is
  installed at 0x08002000: the closest is v2, and flash differs from it at 0x08002326".
  These three cuts were false passes before.
- A mistake of its own: the Three-Tier test update is the old FBL plus 16 bytes, so the old
  image matched the new one on its own length and every result said `old_fbl`. When several
  images match, the longest is the one really there. Covered by a test.

It also let the Three-Tier adapter drop its "Slot B must be wiped" check, which was only true
after the SBL had started, and add cuts at ops 0 to 6 (the Boot Manager's state page). There
the device keeps the old FBL and runs it; from op 7 on the Boot Manager completes the update
and the new FBL runs. 12 cuts, all pass, and each line says which image it ended on.

Limits:
- The oracle is consulted after the driver says the device is up. The driver is still what
  decides "booting has finished". A target with a slow recovery needs that wait.
- "Running inside the image, not in a fault handler" is evidence of life, not proof of
  correct behaviour. A firmware stuck in its own `while(1)` in thread mode passes it; that is
  what the driver's own signs of life are for.
- Without an `oracle:` section a run still works, and the CLI says the verdicts then rest on
  the driver alone.
