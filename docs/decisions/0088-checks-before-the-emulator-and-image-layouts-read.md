# Checks before the emulator, and image layouts read from the image

2026-10-19

The first outside target Adham ran himself (MCUboot overwrite-only, PR #38) failed three
times before any firmware was judged, every time for a reason a program could have named: an
adapter saved in .github/workflows instead of next to the adapter it extends, a build
workflow that fetched from a remote west never sets up, and a damaged-image size inherited
through `extends:` from another build whose image was 40 bytes longer (a false FAIL). A
first-time user meeting the same errors would give up on the tool.

`brickproof check` makes every check that needs no emulator, in plain words with a fix for
each, and run/trace/export run it first. It searches for a file of the same name when a
path is wrong, reads ELF load addresses and the vector table's initial SP (a stack outside
the RAM given means ram.size is not the chip's), and asks Renode's platform files which
UARTs exist. An approved image a driver makes at run time (OpenBLT's) is a warning, not a
failure.

The damaged-image tests read an MCUboot image's layout from its header and TLV magics when
the adapter gives none, as build.py's image_end() did. What the adapter gives still wins, so
no existing adapter changes; check fails when a given size disagrees with the header.
