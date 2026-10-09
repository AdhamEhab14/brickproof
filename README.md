# BrickProof

Pull the plug on your firmware update, in an emulator, at every flash operation, and check
that the device still comes back.

BrickProof runs a firmware binary in [Renode](https://renode.io), cuts power just before
each flash erase and program during an update, reboots, and checks recovery invariants
with an oracle that shares no code with the firmware under test.

**Status:** early development. The engine is being extracted from the power-cut harness of
[Three-Tier-STM32-Secure-Bootloader](https://github.com/AdhamEhab14/Three-Tier-STM32-Secure-Bootloader),
where it found three real bugs.

## Licence

Apache-2.0, see [LICENSE](LICENSE).
