# Adapter = YAML + driver.py

2026-10-09

The YAML holds data (geometry, firmware, reset commands, cut list). The driver holds the target's
update protocol: `prepare()` stages the update once, `start_update()` triggers it, `alive()` and
`check_recovered()` judge the result. The driver may use the target's own host tools: for the
Three-Tier bootloader it imports `host/bl_host.py` and `host/sign_tool.py`, so the firmware
gets exactly the bytes the real host would send.
