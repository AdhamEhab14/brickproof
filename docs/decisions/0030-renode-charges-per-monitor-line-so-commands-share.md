# Renode charges per monitor line, so commands share lines

2026-10-10

Profiled again after the flash checks pushed a demo cut from 1.9 s to 3.9 s. Measured:
every monitor line costs 40 to 60 ms in Renode whatever it holds (a RAM write, `version`,
a register read), sending many lines in one socket write changes nothing, but several
commands on ONE line separated by `;` cost about the same as one (8 writes: 77 ms, not 500).
Reading memory back as text is slow on top of that: 128 ms per KB.

So:
- `cmd_batch` joins commands with `;` (40 per line). A power cycle is one line instead of ten.
  UART injection, which is two commands per byte, gains the most.
- status is read in groups: `cut_status()`, `violations()`, `run_until_cut()` (run and check
  in one line).
- the per-cut self-check no longer reads pages back. The expected image is loaded into a
  hidden memory (`bpExpect`, a file load is fast) and the flash model compares natively. It
  now covers the whole flash, not only the pages the update touches, and is quicker.

Demo cut: 3.9 s -> 1.7 s with every check on (whole-flash compare, rule enforcement, audit).
What is left is mostly emulation itself (`RunFor`, about 0.28 s per boot with the model's
per-access overhead) plus the one-off flash dump at setup (about 7 s).
