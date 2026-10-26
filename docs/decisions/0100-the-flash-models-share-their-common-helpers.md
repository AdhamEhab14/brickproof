# The flash models share their common helpers

2026-10-26

The four flash models (`stm32f1_flash.py`, `stm32f4_flash.py`, `stm32l4_flash.py`,
`nrf52_flash.py`) each carried the same eight helpers, word for word once comments are set
aside: `st`, `st_w` (the state words), `log` (the trace), `wake_clock` and `spend` (flash
time, and the clock fix of 0090), `first_difference`, `get` and `put`. A change to any of
them was four changes, and #42's `wake_clock` was written four times.

They are now in `models/flash_common.py`, once. Renode runs each model as a script of its
own and cannot import another file, so the engine puts the common file into the model at
its `# @FLASH_COMMON@` line when it copies the model into the work folder, as it already
writes the flash geometry into it (`engine/workdir.py`, `with_common`). A model without the
line is refused, and a test checks that each model then has every helper exactly once.
The wake-clock test of 0090 reads the models as Renode gets them.

The other functions the models share in part (`after_reset`, `program`, `listen`, ...)
differ from chip to chip and stay where they are.
