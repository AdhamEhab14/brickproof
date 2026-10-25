# Port the harness, don't rewrite it

2026-10-09

`engine/session.py` is the bootloader's `tests/renode/renode_session.py` with the target-specific
parts moved into the adapter: ELF names, the held B1 button (now `reset:` monitor commands),
the flash geometry, and the repo root. The flash model is the bootloader's `models/flash.py`
unchanged apart from its header comment.
