# Flash geometry by text rewrite

2026-10-09

Renode's Python peripherals take no parameters. The engine copies each flash model into the run's
work folder and rewrites its `PAGE`, `FLASH_BASE` and `FLASH_SIZE` lines. A unit test fails if a
model loses one of those lines.
