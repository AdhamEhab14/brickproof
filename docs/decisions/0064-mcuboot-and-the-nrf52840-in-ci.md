# MCUboot and the nRF52840 in CI

2026-10-16

MCUboot needs a Zephyr workspace to build, which is too much for every CI run and for a new
user. `build.py`'s output for both boards is committed in `adapters/mcuboot/prebuilt`
(built once on an ubuntu-latest runner: MCUboot `4eba8087`, Zephyr v4.2.0 `413b789`, Ubuntu's
arm-none-eabi-gcc 13.2.1), and the adapters point there unless `--target` says otherwise.
`mcuboot.elf` has its debug sections stripped: 1.1 MB down to 90 KB, symbols kept, the
loaded bytes checked identical.

Timing decided the CI settings. One uninterrupted update: 4 min on the F411 (391,974 byte
programs), 2 min on the nRF52840. Every cut then runs MCUboot's recovery, which on the F411
redoes the rest of a 128 KB byte-by-byte swap, about 5 minutes. The adapters' own plans (57
and 156 cuts) would take hours on a 4-core runner. CI therefore runs `--per-phase 1
--real-every 4`: every edge between phases is cut, one sample inside each long phase, and
three in four cuts start from the computed state (the real ones check it byte for byte). On
this PC with 6 emulators: nRF52840 111 cuts, all recovered, 3.5 min; F411 42 cuts, all
recovered, 56 min. So on a runner the F411 is split over four shards (`--shard K/4`), which
together make exactly those 42 cuts. First CI run: the shards took 8 to 19 minutes (a runner
goes through the F411 update in about a minute, four times faster than this PC), the
nRF52840 5 minutes.

The nRF52840 demo joins the `demo` matrix: the correct build with torn states and depth 2,
`hold_pg` with torn states, and the eight bug builds, each expected to fail.
`nrf52-bug-retry_limit.yaml` now sets `scenario.depth: 2` like its STM32 versions, so it is
caught without a command-line flag.
