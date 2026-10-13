# OpenBLT on a Nucleo-F103RB

[OpenBLT](https://github.com/feaser/openblt) with its own Nucleo-F103RB demo, reprogrammed over
the UART with OpenBLT's XCP protocol, the way its host tools do it.

OpenBLT has no second slot: it erases the program and writes the new one in its place. What
it promises is that the bootloader always survives and takes a new programming session. So
after every cut the bootloader must answer, it must not start a program that is not
completely written, and a full session after the cut must end with the program running.

## Running it

```bash
git clone https://github.com/feaser/openblt
cd openblt/Target/Demo/ARMCM3_STM32F1_Nucleo_F103RB_GCC
make -C Boot all && make -C Prog all
cd -
brickproof run adapters/openblt_f103/adapter.yaml \
    --target openblt/Target/Demo/ARMCM3_STM32F1_Nucleo_F103RB_GCC -j auto --html openblt.html
```

| File | What |
|---|---|
| `adapter.yaml` | the chip, the bootloader, the approved images and the cut plan |
| `driver.py` | an XCP programming session over the UART, and the checks after a cut |

## What it found

Tested on commit `7dfd266` (2026-10-06), default `blt_conf.h`.

The bootloader itself survived every cut and always took a new session. But a cut near the
end of a session can leave a program that the bootloader starts although it is not
completely written.

`FlashDone()` in `Target/Source/ARMCM3_STM32F1/flash.c` writes the block that holds the
program's checksum (at `0x10C`) before the last data block, and the block is written from
its start, so the checksum is in flash before the rest. From then until the session ends,
the program passes `NvmVerifyChecksum()`, which only covers the vector table, while part of
it is still erased.

Confirmed on a real Nucleo-F103RB on 2026-10-13. The flash contents a cut leaves at each
point were written with an ST-LINK (verify OK each time) and the board was reset:

| Flash state | LED after reset |
|---|---|
| complete session | slow blink: the program runs |
| cut just before the checksum | fast blink: the bootloader refuses it, as it should |
| checksum written, rest of its block and the last block erased | off: a broken program was started |
| that block complete, last block erased | off: a broken program was started |
| only the last two bytes missing | slow blink: an incomplete program runs |

In the two "off" cases the board stays that way across resets. It can be recovered by
connecting during the bootloader's 500 ms backdoor, so the bootloader itself is never lost.
The window is short, roughly the last 20 ms of flash writing in a session, and OpenBLT
documents hooks (`BOOT_NVM_CHECKSUM_HOOKS_ENABLE`) for a checksum over the whole program.

The fix suggested to the maintainers is to make the checksum the last thing written: write
the last data block first, then the checksum block with the checksum word left erased, then
the checksum word on its own.

Reported to Feaser on 2026-10-13 (the GitHub repository is a read-only mirror and takes no
issues).
