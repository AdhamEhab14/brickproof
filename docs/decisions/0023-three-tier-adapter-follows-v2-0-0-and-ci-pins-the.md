# Three-Tier adapter follows v2.0.0, and CI pins the tag

2026-10-10

The bootloader's `main` moved to v2.0.0 a day after the adapter was written, and CI checked
out `main`: the adapter's 1.6.0 test FBL was refused, no cut ever fired, and the e2e job sat
in timeouts. CI now checks out the `v2.0.0` tag, and the adapter signs its FBL as 2.1.0.
Moving to a newer bootloader release is a deliberate adapter change, not something a push
to another repo does to us.

Run against v2.0.0 with real RAM and the memory guards: baseline + 5/5 cuts, no bus fault.
The baseline's operation count is blank for this target: the bootloader resets itself after
the update, which resets the flash model's counter.
