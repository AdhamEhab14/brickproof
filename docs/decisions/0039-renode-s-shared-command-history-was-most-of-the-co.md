# Renode's shared command history was most of the cost of everything

2026-10-11

Trying to start eight emulators at once crashed them: Renode saves its monitor command
history after every command, by rewriting the whole file, and by default that file is one per
user (`%APPDATA%\renode\history`, `~/.config/renode/history`). Two Renodes writing it collide.

It was also the "fixed 40 to 60 ms per monitor line" measured the day before. The file had
grown to 25 MB (670,000 lines) and was rewritten for every command, which is why the cost
crept from 60 to 100 ms as this project ran. Measured with 20 `version` commands:
shared history 67 ms per line, own history file 1.6 ms.

Each session now writes a `renode.config` with `history-path` in its own work folder and
starts Renode with `--config`. (`--config` alone, or redirecting `APPDATA`, does not move the
history: the path is a setting inside the config file.)

Effect on one emulator, full demo, every clean cut: 580 s -> 181 s.
