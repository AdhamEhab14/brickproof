# m33mu, from wolfBoot's maintainer (PR #35)

2026-10-16

Daniele Lacamera (wolfBoot) contributed a second emulator backend: m33mu, his Cortex-M33
emulator, driven over its GDB server's monitor commands (`engine/m33mu.py`), with the STM32H563
as its first chip, the demo ported to it, and a wolfBoot adapter for the H563 with TrustZone.
It is the one way here to reach Armv8-M chips, which Renode does not have. His seven commits
were brought onto this branch as he wrote them (his authorship kept), with conflicts resolved
against everything that landed after his base, and then fitted in:

- **Taken whole:** the backend, the H563 demo and its bug builds, the wolfBoot H563 adapter,
  his tests, the `demo-m33mu` CI lane, and the Action building m33mu from a pinned commit
  when an adapter needs it.
- **Left out: m33mu in the Docker image.** m33mu is AGPL-3.0 and BrickProof is Apache-2.0.
  Calling it as a separate program is fine either way; shipping its binary inside our image
  would make the image carry AGPL terms, and every image build would compile it. The image
  stays Renode only, and the README says how to get m33mu for the H563.
- **Fitted to what came after his base:** the H563 path now parses content faults, link cuts
  and bit errors like every other adapter (his `h563.yaml` gets the same checks as the other
  demos), `M33muSession.uart_write` honours the link budget as `RenodeSession` does, and the
  Renode-only keys added since (`external_eeprom`, `flash.worn`, `flash.uicr`) are refused on
  an m33mu chip instead of being ignored. The demo's UART goes by `UART_*` names, his scheme,
  which the L476 uses too.

**Known gap:** on m33mu the option bytes are kept by name, outside the flash image, so a cut
while firmware changes them is not modelled and torn states do not cover them. The Renode
chips do cover theirs. Closing it needs m33mu to save and load its option bytes with the
flash, which is m33mu's side.

m33mu does not build on this machine (no Linux toolchain), so the H563 lane is checked on
GitHub's runners only.
