# Settings on FCB, written up

2026-10-16

The settings-on-FCB results were kept out of the repository until they were reported. Every
distinct flash state cut (2,314): 2,305 recover. 7 are a cut inside an entry's data whose
CRC-8 over what reached flash is 0xFF, the erased value of the marker slot, so FCB accepts
the unfinished entry (each checked byte by byte on the state BrickProof replays to that
cut); reported as zephyrproject-rtos/zephyr#122446. 2 are a cut inside a new sector's header
after its magic word: the sector is accepted with the erased id 0xFFFF, which makes it the
oldest, and `settings_fcb_src()` then erases the active sector; added to #121749. CI now
runs settings on FCB expecting it to be caught, like ZMS.
