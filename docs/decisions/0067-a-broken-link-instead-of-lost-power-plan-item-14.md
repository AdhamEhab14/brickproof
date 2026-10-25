# A broken link instead of lost power (plan item 14)

2026-10-16

An update sent over a protocol can also be lost to the link: the cable comes out, the host
crashes, a CAN bus goes quiet, while the device keeps its power. The bootloader then has a
half-received session to deal with, not a half-written flash.

The break is made in the session, not in the drivers: `uart_write` gets a byte budget, and
once it is used up the rest of what the host sends is dropped. Both protocol drivers send
everything through `uart_write`, so neither needed a change. The baseline counts the bytes
the host sends; link cuts are placed at the first byte, the last, and `points` evenly between.
After a cut the link stays down for `wait` virtual seconds, then the host runs the whole
update again (`start_update()`), and the result is judged like a power cut's.

**Checked** in Renode: OpenBLT 62786e72 (a 6,422-byte XCP session) recovered at all 10
points: after each, a new session installed the program and it ran. The Three-Tier
bootloader v2.0.0 (its 170-byte UPDATE_FBL frame) recovered at all 10: a partial frame
never started the self-update, and the frame sent again installed the new FBL. A unit test
checks that with a budget only that many bytes reach the device. Only the UART is covered:
the Three-Tier adapter drives its update over the UART too, and a CAN link would need the
same budget on the CAN frames.
