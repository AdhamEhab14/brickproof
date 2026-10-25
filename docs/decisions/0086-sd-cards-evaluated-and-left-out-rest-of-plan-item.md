# SD cards, evaluated and left out (rest of plan item 10)

2026-10-16

The common bootloader case is reading: the update is a file on the card, written to flash.
Reads change nothing a cut can tear, and every flash operation of such an update is counted
as usual, so that case needs no model of ours. Renode has an SD card model of its own
(`SD.SDCard`); adding it through `platform.extra` should cover it, but that is not tried
here yet.

Cuts during SD writes are a different matter. A card's controller remaps sectors behind its
own flash translation layer, and what a power loss leaves behind there (the sector written,
its neighbours, the mapping) is not documented by any card maker and differs between cards.
Torn shapes for it would be invented, not measured, which this project does not do for its
other memories. SD writes stay out until there is a measured basis, for instance from the
power-cut rig on a few cards.
