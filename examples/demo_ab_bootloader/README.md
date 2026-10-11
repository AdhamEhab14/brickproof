# The BrickProof demo

A small A/B bootloader for an STM32F103RB (under 1 KB) and an app that prints its version.
The update copies a new image from the staging slot over the running one.

```bash
brickproof demo                 # the correct bootloader: every cut recovers
brickproof demo --list          # the builds with a known bug
brickproof demo self_lock       # run one of them: BrickProof should catch it
```

| File | What |
|---|---|
| `bootloader/main.c` | the bootloader; each `BUG_...` option puts back one known mistake |
| `app/main.c` | the app |
| `adapter.yaml`, `bug-*.yaml` | how BrickProof runs each build |
| `prebuilt/` | the built firmware, so no toolchain is needed |
| `build.py` | rebuilds `prebuilt/` (needs `arm-none-eabi-gcc`) |
