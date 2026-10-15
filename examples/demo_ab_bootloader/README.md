# The BrickProof demo

A small A/B bootloader (about 1 KB) and an app that prints its version. The update copies a
new image from the staging slot over the running one. One source builds for three chips: an
STM32F103RB (1 KB pages, halfword programming), an STM32F411 (sectors of 16 to 128 KB, word
programming) and an nRF52840 (4 KB pages, aligned word programming, at most two writes to a
word between erases).

```bash
brickproof demo                 # the correct bootloader: every cut recovers
brickproof demo --list          # the builds with a known bug
brickproof demo self_lock       # run one of them: BrickProof should catch it
brickproof demo f411            # the same demo on the STM32F411
brickproof demo nrf52           # and on the nRF52840
```

| File | What |
|---|---|
| `bootloader/main.c` | the bootloader; each `BUG_...` option puts back one known mistake |
| `app/main.c` | the app |
| `common/chip_f103.h`, `common/chip_f411.h`, `common/chip_nrf52.h` | what differs between the chips: flash map, erase, program, option bytes, UART |
| `adapter.yaml`, `bug-*.yaml` | how BrickProof runs each build on the F103 |
| `f411.yaml`, `f411-bug-*.yaml` | the same on the F411 |
| `nrf52.yaml`, `nrf52-bug-*.yaml` | the same on the nRF52840 |
| `prebuilt/` | the built firmware, so no toolchain is needed |
| `build.py` | rebuilds `prebuilt/` (needs `arm-none-eabi-gcc`) |
