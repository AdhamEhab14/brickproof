# Three-Tier secure bootloader on an STM32F103RB

[Three-Tier-STM32-Secure-Bootloader](https://github.com/AdhamEhab14/Three-Tier-STM32-Secure-Bootloader)
v2.0.0, cut during its FBL self-update: the first real target BrickProof was written for.

The bootloader has three parts: a Boot Manager that never changes, an FBL that takes updates
over the UART, and an SBL that runs from RAM. To update itself, the FBL stages a signed new
FBL in Slot B, and `UPDATE_FBL` hands over to the SBL, which erases the FBL's 40 KB and
copies Slot B over it. After a cut, the Boot Manager has to finish that copy on the next
boot. So after every cut the device must come back running either the old FBL or the new
one, byte for byte, and never anything in between.

## Running it

```bash
git clone --branch v2.0.0 https://github.com/AdhamEhab14/Three-Tier-STM32-Secure-Bootloader target
cmake -S target -B target/build-test -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake -DBL_TEST_KEYS=ON
cmake --build target/build-test
pip install -r adapters/three_tier_f103/requirements.txt
brickproof run adapters/three_tier_f103/adapter.yaml --target target --torn --depth 2 -j 3
```

The build uses the bootloader's published TEST keys. The driver signs the new FBL with them
using the bootloader's own host tools (`host/bl_host.py`, `host/sign_tool.py`), so the
device sees exactly the bytes the real host would send. CI runs this as the `e2e` job.

| File | What |
|---|---|
| `adapter.yaml` | the chip as deployed (Boot Manager write-protected), the approved images, the cut plan and the broken-link points |
| `driver.py` | the FBL self-update over the UART, through the bootloader's host tools |
| `platform_extra.repl`, `can_stub.py` | a small stand-in for the bxCAN controller, which Renode's model will not take out of sleep |
| `requirements.txt` | what those host tools import |

## What it found

Run on the bootloader as it was before v2.0.0, BrickProof found three bugs, each a way a cut
bricked the device or let an old image back in. They are the demo's first three bug builds:

| Demo build | The mistake |
|---|---|
| `bug-consume_first` | the staged image is marked used before it is copied, so a cut leaves no valid image |
| `bug-trust_header` | the header is copied first and trusted without a CRC, so a half-copied image boots |
| `bug-naive_floor` | the anti-rollback floor is rewritten in place after the install, so an older image can be installed again |

v2.0.0 fixes all three. Its self-update has since been cut at every one of its 12,109
distinct flash states (`.github/workflows/exhaustive.yml`, 20 machines, 2026-10-12), with no
failure. Built with Arm's toolchain, as CI now does, the same update has 11,897 distinct
states (`docs/decisions.md`, 2026-10-25).
