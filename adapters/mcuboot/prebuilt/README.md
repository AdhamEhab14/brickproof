# MCUboot, prebuilt

What `build.py` made for each board, so the adapters and CI run without a Zephyr
workspace. Built on GitHub's ubuntu-latest runner on 2026-10-15:

| | |
|---|---|
| MCUboot | `4eba8087fa606db801455f14d185255bc8c49467` |
| Zephyr | `413b789deb391d3a37d06b463288a5fe765ee57e` (v4.2.0) |
| Compiler | Ubuntu's arm-none-eabi-gcc 13.2.1 (`ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb`) |
| Signing key | MCUboot's own test key `root-ec-p256.pem` (public, for testing only) |

Each folder has:

| File | What |
|---|---|
| `mcuboot.elf` | MCUboot, debug sections removed (`strip --strip-debug`; symbols kept, loaded bytes unchanged) |
| `app_v1.img` | the app, version 1.0.0, signed: installed in slot 0 at the start |
| `app_v2_staged.img` | version 2.0.0, signed with `--pad --confirm`: staged in slot 1 |
| `app_v2.img` | the same v2 image without the padding and trailer: what slot 0 must hold afterwards |

ECDSA signatures are different on every build, so a rebuild gives different bytes. Build
again with:

```bash
python adapters/mcuboot/build.py <zephyr workspace> adapters/mcuboot/prebuilt/f411 f411
python adapters/mcuboot/build.py <zephyr workspace> adapters/mcuboot/prebuilt/nrf52840 nrf52840
```

then delete the `build/` folder it leaves and strip `mcuboot.elf` the same way.

`f411-overwrite/` is the same board with MCUboot's overwrite-only upgrade
(`CONFIG_BOOT_UPGRADE_ONLY=y`), built on 2026-10-19 with the same MCUboot, Zephyr and
compiler as above (GitHub Actions run 39271573096):

```bash
python adapters/mcuboot/build.py <zephyr workspace> adapters/mcuboot/prebuilt/f411-overwrite f411 overwrite
```

Its images are 40 bytes shorter than `f411/`'s (v2 is 0x43AF bytes). The damaged-image
tests read each image's layout from its header, so no adapter states a size.
