# Flash starts erased (0xFF)

2026-10-10

Renode's flash memory starts as 0x00; real erased flash reads 0xFF. The session now fills
flash with 0xFF before loading firmware. Firmware that checks "is this slot empty" would
otherwise see a state that cannot exist on silicon.
