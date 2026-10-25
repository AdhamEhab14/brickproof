# The demo, one folder per chip

2026-10-25

`examples/demo_ab_bootloader/` held 72 adapters side by side with the firmware's source,
its build script and 78 prebuilt files. Now the adapters are in one folder per chip
(`f103/`, `f411/`, `l476/`, `nrf52/`, `h563/`) and the firmware in `firmware/`. The five base
adapters say `target: ../firmware`, so every `prebuilt/...` path inside them and their
variants is unchanged.

File names are kept, so every demo name (`brickproof demo f411-bug-no_erase`) and every
scenario id works as before; `brickproof demo` now looks in each chip's folder. The parity
baseline is the same 84 campaigns with the same results, under the new paths (only its
keys moved). The wheel ships the same 72 adapters and 78 prebuilt files, and the demo runs
from it.
