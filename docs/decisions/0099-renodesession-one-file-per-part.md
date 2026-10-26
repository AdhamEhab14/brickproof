# RenodeSession, one file per part

2026-10-26

`engine/session.py` was 1,000 lines: the flash models' register map, `FlashGeometry`, the
helpers both emulator backends use, and `RenodeSession`, one class of 70 methods covering
starting Renode, its monitor, emulated time and the UART, every memory, the flash model's
cut controls, the trace, resets and power.

Now:

| File | What |
|---|---|
| `engine/common.py` | `MachineHung`, the hang limit, TCP ports, closing emulators left running (shared with m33mu) |
| `engine/geometry.py` | `FlashGeometry` |
| `engine/flash_regs.py` | the flash models' test registers and trace codes |
| `engine/renode/process.py` | starting Renode, its monitor, stopping it |
| `engine/renode/clock.py` | emulated time in slices, the UART, the core's state on every slice |
| `engine/renode/memory.py` | words, flash images, the external chip and the EEPROM |
| `engine/renode/flash_model.py` | arming cuts, the chip rules seen broken, the trace |
| `engine/renode/power.py` | reboots and power cycles |
| `engine/session.py` | `RenodeSession(Process, Clock, Memory, FlashModel, Power)`, `RenodeSerial`, `find_renode` |

Each part is a class holding its section's methods, and `RenodeSession` is the five put
together, so a session is the same object with the same methods as before. The move was
mechanical, by the parser, method by method; a check found every line of code and every
comment of the old file in the new ones, but for the eight `# ---- section ----` lines the
files now stand for. `session.py` re-exports every name it had (and `subprocess`, whose
`Popen` a test patches), so nothing that imports from it changes. `brickproof.engine.renode`
is in the package list.
