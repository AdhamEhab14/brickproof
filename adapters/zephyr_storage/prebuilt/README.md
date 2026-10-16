# The storage workload, prebuilt

What `build.py` made, so the adapters and CI run without a Zephyr workspace. Built on
GitHub's ubuntu-latest runner on 2026-10-16:

| | |
|---|---|
| Zephyr | `413b789deb391d3a37d06b463288a5fe765ee57e` (v4.2.0) |
| littlefs module | `8f5ca347843363882619d8f96c00d8dbd88a8e79` |
| Compiler | Ubuntu's arm-none-eabi-gcc 13.2.1 (`ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb`) |
| Board | `nrf52840dk/nrf52840`, its external QSPI flash disabled (`app/boards/`) |

| File | What |
|---|---|
| `nrf52840/nvs.elf`, `nvs.bin` | the workload on Zephyr NVS, 3 sectors of 4 KB at 0xF8000 |
| `nrf52840/littlefs.elf`, `littlefs.bin` | the workload on littlefs, the 32 KB storage partition at 0xF8000 |

Each `.bin` is `arm-none-eabi-objcopy -O binary` of its ELF: the bytes loading the ELF puts
in flash, which the oracle compares with. (Zephyr's own `zephyr.bin` fills gaps between
sections with 0xFF where the ELF has zeros, so it is not used.) The ELF files have their debug sections stripped (`strip --strip-debug`; symbols kept, the
loaded bytes unchanged). Build again with
`python adapters/zephyr_storage/build.py <zephyr workspace> adapters/zephyr_storage/prebuilt/nrf52840`
(the workspace needs the `littlefs` and `hal_nordic` modules), then delete the `build/`
folder it leaves and strip the ELF files the same way.
