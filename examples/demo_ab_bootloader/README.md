# The BrickProof demo

A small A/B bootloader (about 1 KB) and an app that prints its version. The update copies a
new image from the staging slot over the running one. One source builds for five chips: an
STM32F103RB (1 KB pages, halfword programming), an STM32F411 (sectors of 16 to 128 KB, word
programming), an STM32L476 (2 KB pages, 64-bit double words with ECC), an nRF52840 (4 KB
pages, aligned word programming, at most two writes to a word between erases), all emulated
by Renode, and an STM32H563 (8 KB sectors, 128-bit words that are never programmed twice),
emulated by [m33mu](https://github.com/danielinux/m33mu).

```bash
brickproof demo                 # the correct bootloader: every cut recovers
brickproof demo --list          # the builds with a known bug
brickproof demo self_lock       # run one of them: BrickProof should catch it
brickproof demo f411            # the same demo on the STM32F411
brickproof demo l476            # and on the STM32L476, where an erase cut short trips ECC
brickproof demo nrf52           # and on the nRF52840
brickproof demo h563            # and on the STM32H563 (needs m33mu, see below)
```

The H563 build runs secure from the secure flash alias and prints on USART3, the
Nucleo-H563ZI's virtual COM port. Where the F-series builds mark the staged image consumed
by programming zeros over its magic, the H563 one programs a marker word of its own: the
chip does not let a 128-bit word be programmed twice. The option-byte and watchdog bugs
(`self_lock`, `watchdog`) and the external flash chip are F-series only. m33mu goes on
PATH, or in `M33MU_PATH`.

| File | What |
|---|---|
| `bootloader/main.c` | the bootloader; each `BUG_...` option puts back one known mistake |
| `app/main.c` | the app |
| `common/chip_f103.h`, `common/chip_f411.h`, `common/chip_l476.h`, `common/chip_nrf52.h`, `common/chip_h563.h` | what differs between the chips: flash map, erase, program, option bytes, UART |
| `adapter.yaml`, `bug-*.yaml` | how BrickProof runs each build on the F103 |
| `f411.yaml`, `f411-bug-*.yaml` | the same on the F411 |
| `l476.yaml`, `l476-bug-*.yaml` | on the L476 |
| `nrf52.yaml`, `nrf52-bug-*.yaml` | on the nRF52840 |
| `h563.yaml`, `h563-bug-*.yaml` | and on the H563 |
| `prebuilt/` | the built firmware, so no toolchain is needed |
| `build.py` | rebuilds `prebuilt/` (needs `arm-none-eabi-gcc`) |
