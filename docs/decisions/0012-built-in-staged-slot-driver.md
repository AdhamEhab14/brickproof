# Built-in `staged_slot` driver

2026-10-10

Most bootloaders apply an image that waits in a staging slot on the next boot (MCUboot
overwrite mode, most OTA designs). For those, the driver needs no target code: put the image
in the slot, reset, read what booted from the UART. Options are regexes (`alive`, `expect`)
and an optional rollback probe (stage an older image after recovering; it must not run).
Targets with a protocol-started update still write a `driver.py`.
