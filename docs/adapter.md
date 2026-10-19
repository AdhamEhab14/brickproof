# Writing an adapter

An adapter is one YAML file that tells BrickProof about your device: which chip, what to load
into its flash, how an update is started, and what counts as recovered. Everything below is
what `brickproof run` reads. Two complete examples are in the repository:

- [examples/demo_ab_bootloader/adapter.yaml](../examples/demo_ab_bootloader/adapter.yaml): a
  bootloader that applies a staged image on the next boot. No code needed, only YAML.
- [adapters/three_tier_f103](../adapters/three_tier_f103): an update driven over a UART
  protocol, with a small `driver.py`.

Start from the one that is closer to your update, then run `brickproof trace my_adapter.yaml`.
It does one update with no cuts and prints every flash operation in phases. If that passes,
the adapter is right and `brickproof run` can start cutting.

## The whole file

```yaml
name: my_device                # used in reports
target: ../my-firmware         # folder the file paths below are relative to
                               # (--target on the command line overrides it)
extends: base.yaml             # optional: start from another adapter and change a few keys

platform:
  base: stm32f103              # stm32f103, stm32f411, stm32l476, nrf52840 (Renode); stm32h563 (m33mu, see below)
  extra: extra.repl            # optional: more Renode platform lines (peripherals your
                               # firmware needs); @ADAPTER@ is this file's folder

flash:
  base: 0x08000000
  size: 0x20000                # the real size of the chip's flash
  page: 0x400                  # STM32F1: the page size (0x400 or 0x800); STM32L476: 0x800; nRF52840: 0x1000
  # sectors: [0x4000, 0x4000, 0x4000, 0x4000, 0x10000, 0x20000, 0x20000, 0x20000]
  #                            # STM32F4: every sector's size, in order. One of page or sectors.
  write_unit: 2                # bytes a program usually writes (2 on F1, 4 on F4 and nRF52, 8 on L4)
  write_protected:             # STM32: what the option bytes protect on the device as shipped
    - {from: 0x08000000, size: 0x4000}
  read_protected: false        # true: RDP level 1 (nRF52: APPROTECT); 2: level 2 (STM32F4), for good
  # uicr: {0x304: 5}           # nRF52: UICR words as shipped, by offset (here REGOUT0 = 3.3 V)
  # reset_on: [standby]        # STM32F1/F4: nRST_STDBY / nRST_STOP cleared: entering the mode resets
  # pcrop:                     # STM32F4: sectors of proprietary code (SPRMOD), instead of
  #   - {from: 0x08060000, size: 0x20000}   # write_protected: run only, no data reads
  hardware_watchdog: false     # WDG_SW cleared: the watchdog runs from reset, unstoppable
  timing: typical              # typical, max or none: how long erases and programs take

external_flash:                # optional: an SPI NOR flash chip (25-series commands)
  bus: spi1                    # the SPI controller it is wired to
  cs: PA4                      # its chip select pin
  size: 0x100000               # up to 64 MB; over 16 MB it has 4-byte addresses
  # address: 0xA0000000        # how its bytes are named in traces, images and `slot:`
  # status: 0x00               # its status registers as shipped: 1, or 0xTTSSRR for 1-3
  # wp: PA3                    # the pin wired to its /WP (otherwise /WP reads high)

external_eeprom:               # optional: an I2C EEPROM (24-series)
  bus: i2c1                    # the I2C controller it is wired to
  size: 0x8000                 # a power of two, up to 64 KB
  # page: 32                   # bytes one write can cover; it wraps inside the page
  # i2c_address: 0x50          # its 7-bit bus address
  # address_bytes: 2           # 1 for chips up to 256 bytes (the default there), else 2
  # address: 0xB0000000        # how its bytes are named in traces, images and `slot:`
  # endurance: 1000000         # write cycles per page the datasheet promises

ram:
  size: 0x5000                 # the real RAM size. Required: extra RAM hides stack faults

firmware:                      # the device as shipped, before the update
  - file: build/bootloader.elf
  - file: build/app_v1.bin     # a raw binary needs an address
    addr: 0x08004000

clock:
  hse: 8000000                 # the board's crystal or external clock in Hz (default 8 MHz)

pins:                          # inputs held at a level, for buttons and straps
  PC13: high                   # an input nothing drives reads low in the emulator

uart: usart2                   # where the firmware prints
boot_settle: 1.5               # virtual seconds from reset until the device is ready
reset:                         # optional Renode commands after every reset
  - gpioPortC OnGPIO 13 false  # for example a button held down

cpu:
  vector_table: 0x08000000     # default: flash.base
  mips: 72                     # emulated CPU speed

driver:
  builtin: staged_slot         # or  file: driver.py
  options: {}                  # passed to the driver, see below

oracle:                        # which images may be installed after a cut
  images:
    old: {file: build/app_v1.img, at: 0x08004000}
    new: {file: build/app_v2.img, at: 0x08004000}
  accept: [old, new]           # or [new] if a cut must never lose the update
  stable_for: 1.0              # seconds it must then run with no reset (0 = do not wait)

scenario:
  name: update-v1-to-v2
  update_time: 6               # virtual seconds an uninterrupted update needs
  cut_limit: 30                # virtual seconds to wait for a cut to fire
  plan: phases                 # or every, or {mode, per_phase, small, real_every}
  torn: true                   # or a list of shapes; same as --torn
  depth: 2                     # or {levels, mode, per_phase, small, max_states, torn}
  cuts:                        # optional hand-picked cuts, instead of or beside a plan
    - {at_op: 12}
    - {on_erase: 0x08004000}
    - {at_ops: {from: 0, to: 40, step: 4}}
```

## Getting the chip right

The run is only worth something if the emulated chip is the chip you ship.

- `flash.size`, `ram.size`: the real ones. Renode's stock platforms are far bigger than any
  chip, and a stack overflow or a write past the end of flash would simply work.
- `flash.write_protected`, `flash.read_protected`: as the device leaves the factory. A slot
  that is write-protected by mistake makes every update fail on the chip and none in a plain
  emulator.
- `flash.pcrop` (STM32F4): sectors of proprietary code. The option bytes get SPRMOD, and
  those sectors can be run but not read as data, erased or programmed. A data read there is
  RDERR on the chip; the run fails with "proprietary code read as data". It shares the nWRP
  bits with `write_protected`, so it is one or the other. `read_protected: 2` is level 2,
  after which the option bytes cannot change at all.
- STM32L476: programs are 64-bit double words, each with its own ECC. A double word is
  written once between erases (all zeros is the exception), as two word stores in order,
  and anything else is refused with the chip's flag (SIZERR, PGAERR, PROGERR, and PGSERR
  for any program while an earlier error is still flagged). An erase or program cut short
  leaves the ECC of what it touched wrong (torn states only); a read of such a double word
  sets ECCD and raises an NMI, which the bootloader must handle. `write_protected` takes up
  to two areas in bank 1; bank 2's areas and PCROP are not modelled.
- nRF52: the UICR is the chip's option bytes and part of the flash image, after the code
  area. It starts erased; `read_protected: true` sets APPROTECT, and `flash.uicr` sets any
  other word, such as REGOUT0 on a board powered from the high-voltage regulator. Stores into
  it are programs under the same rules as the code area (whole words, two writes between
  erases), ERASEUICR erases it, and ERASEALL erases it together with the code area. Write
  protection is the ACL, which firmware sets after every reset: a write or an erase in a
  region it blocks fails the run as write protection, a read it blocks as a protected read.
  Partial erase (ERASEPAGEPARTIAL) erases a page once the steps add up to tERASEPAGE (85 ms);
  until then the page holds the old data with some bits already flipped to 1.
- Low-power modes. On an STM32F1 or F4, WFI with SLEEPDEEP set enters Stop (RAM kept, the
  SysTick stopped until an interrupt wakes the core) or, with PWR's PDDS, Standby: RAM is
  lost and the chip comes back through a reset with SBF set. `flash.reset_on` clears
  nRST_STOP / nRST_STDBY, so that entering the mode resets the chip instead. On an nRF52,
  SYSTEMOFF powers the chip off the same way (RAM lost, back through a reset; RESETREAS is
  not modelled). `low_power.wake_after` (seconds, 0.5 unless you say otherwise) is when the
  board's wake source (an RTC alarm, a button) ends Standby or System OFF. Without this a
  plain emulator would keep RAM through Standby, or never wake from it.
- `flash.hardware_watchdog`: true if the option bytes make the independent watchdog a
  hardware one. It then runs from reset with its default timeout (about 0.4 s on an F1,
  0.5 s on an F4), and a chip that stands still through a long erase gets reset.
- `clock.hse`: the frequency of the board's crystal. The emulated clock tree follows what
  the firmware writes to the RCC (PLL, prescalers), and the timers and the SysTick count
  with the result, so this one number is all the board has to add.
- `pins`: firmware that reads a button or a strap at start-up sees a low level unless told
  otherwise, and may then stay in its bootloader. State the level the board gives the pin.
- `flash.timing`: `typical` by default. Use `max` when the question is whether a watchdog or
  a timeout survives the slowest erase the datasheet allows. `none` makes operations take no
  time, which is faster and less true.

## A chip m33mu emulates

`platform.base: stm32h563` runs on [m33mu](https://github.com/danielinux/m33mu) instead of
Renode (commit 23960ed or later, on PATH or in `M33MU_PATH`). m33mu models the whole chip, so
the adapter describes it as it is and BrickProof checks that it does:

```yaml
platform:
  base: stm32h563
flash:
  base: 0x0C000000             # the secure alias, or 0x08000000; the size is the chip's,
  size: 0x200000               # and sectors are 8 KB (page: 0x2000, or leave it out)
  write_protected:             # as on the chip: whole groups of four sectors (32 KB)
    - {from: 0x0C000000, size: 0x8000}
ram:
  base: 0x30000000             # or 0x20000000
  size: 0xA0000
uart: usart3                   # usart1..usart3, uart4, uart5, usart6, uart7..uart9,
                               # usart10, usart11, uart12, lpuart1, or a base address
option_bytes:                  # the option bytes as the device ships, by m33mu's names
  SWAP_BANK: 0                 # also WRPSG1, WRPSG2, SECWM1, SECWM2
```

`flash.write_protected` becomes the `WRPSG1` / `WRPSG2` option bytes; give one or the other.
The keys that only mean something to Renode (`platform.extra`, `reset`, `pins`, `clock`,
`cpu.mips`, `external_flash`) are refused rather than ignored.

What the chip does on a power cut comes from m33mu's model of it: a program writes a 128-bit
word with its ECC, as one operation, and a word cannot be programmed twice; write protection,
the TrustZone watermarks and the bank swap act as RM0481 says, and `flash.timing` uses the
datasheet's figures (31 us per word, 2 ms per sector, typical). A cut lands exactly before its
operation, so no program is ever rewound. A core that locks up stays locked up until the next
power cycle, as on silicon.

Option bytes are not part of the flash image here: every cut starts from the option bytes as
shipped.

## An external flash chip

`external_flash` adds an SPI NOR flash chip of the common 25-series kind (Winbond W25Q,
Macronix MX25, GigaDevice GD25): read, page program, 4 / 32 / 64 KB and chip erase, write
enable, status registers 1 to 3, JEDEC ID. Its page programs and erases are operations
like those of the internal flash, counted in the order they really happen, so a cut can fall
on either memory and torn states and cuts during recovery cover both.

The chip has no address on the system bus. `address` (0xA0000000 unless you say otherwise)
is only the name its bytes go by: a staging `slot`, a `firmware` file's `addr` or an oracle
image's `at` at that address goes into the chip.

Block protection works as on a Winbond W25Q: the status register's BP, TB and SEC bits (and
CMP in register 2) protect part of the chip, and an erase or program that touches it is
ignored by the chip and fails the run with a message. The status registers are kept across
power cuts. `status` sets them as the device ships: register 1, or `0xTTSSRR` for all three.
`wp` names the pin wired to /WP: with SRP set and /WP low, status writes are refused. SRL,
volatile status writes (50h) and individual block locks (WPS) work as on a W25Q16JV.

A chip over 16 MB is the W25Q256JV kind: 4-byte addresses, with B7h and E9h to enter and
leave 4-byte mode (status register 3's ADP sets the mode at power-up), the 4-byte commands
13h, 0Ch, 12h, 21h, 5Ch and DCh, the extended address register (C5h, C8h) for 3-byte
commands above 16 MB, and that chip's block protection (BP3-BP0 and TB). A smaller chip
ignores those commands, as a W25Q128 does. A big chip costs memory and time: every saved
flash state holds all of it.

Not modelled: the quad and dual modes (the SPI controllers emulated here move one bit at a
time, so firmware cannot use them through one), and suspend.

## An I2C EEPROM

`external_eeprom` adds a 24-series I2C EEPROM (Microchip 24LC, ST M24, Atmel AT24) on one of
the chip's I2C controllers: random and sequential reads, byte and page writes, one or two
word address bytes. Each write is an operation like a flash program, counted with the
flash's operations in the order they happen, so a cut can fall on it. A write covers one
page at most; bytes past the end of the page wrap to its start, as on the chip.

Unlike flash, a write sets each byte to its new value, whatever was there: the chip erases
the bytes and writes them in one cycle. A write cut short is therefore not an AND of old and
new. Its torn states are `page-erasing` (some old 0 bits back to 1), `page-erased` (0xFF,
nothing written yet) and `page-writing` (part of the new value's 0 bits cleared). Wear is
counted per page against `endurance`.

Like the external flash, the EEPROM has no address on the system bus, and `address`
(0xB0000000 unless you say otherwise) is only the name its bytes go by. It comes last in a
flash image. The write cycle time (5 ms) is spent, but the chip never answers busy:
firmware that polls for the acknowledge gets it at once.

## Drivers

The driver is the part that knows how your update starts and how to tell the device is alive.

**`builtin: staged_slot`** covers bootloaders that find a new image in a staging slot and
apply it on the next boot (MCUboot's overwrite mode, most OTA designs). Options:

| Option | Meaning |
|---|---|
| `slot` | address of the staging slot |
| `image` | the new image, written there before the reset |
| `alive` | regular expression: some valid image is running |
| `expect` | optional regular expression the device must print after recovering, for example `APP v2`: the update was not lost |
| `boot_timeout` | virtual seconds to wait for those (default 2). A recovery that erases a large sector needs more |
| `rollback` | optional `{image, forbidden}`: after recovering, stage this older image and reboot. The device must not print `forbidden` |

**`builtin: storage`** is for flash storage libraries (a key-value store, a file system).
The firmware runs a fixed workload of writes and deletes and speaks a small line protocol
over the UART (see the top of
[drivers/storage.py](../src/brickproof/drivers/storage.py); the reference firmware is
[adapters/zephyr_storage/app](../adapters/zephyr_storage/app)). Before the cuts, the driver
runs the workload a step at a time and notes the flash operations each step spans. After a
cut before operation N it knows which steps had finished, and checks that the store mounts
without being formatted again, holds every finished step's value (or the one under way),
returns nothing half-written, and takes a new write that is still there after one more
power cycle. Options:

| Option | Meaning |
|---|---|
| `keys` | how many keys the workload uses (default 8); the probe key is the next one |
| `probe_gen` | the generation the probe writes (default 9999) |
| `boot_timeout` | virtual seconds to wait for the firmware's `READY` (default 5) |

**`file: driver.py`** is for updates started over a protocol. The file defines
`make_driver(session, adapter)` returning an object with:

| Method | What it does |
|---|---|
| `prepare()` | once: build or load what the update needs |
| `start_update()` | make the device begin the update (send the commands) |
| `alive()` | True if the device is running something valid |
| `check_recovered()` | `(ok, message)` after a cut and a power cycle |
| `oracle_images()` | optional: approved images known only at run time, as `{name: (bytes, address)}` |
| `export_state()`, `import_state(state)` | optional: lets several emulators (`--jobs`) start from exactly the same bytes |
| `judging(update_op)` | optional: told, before each verdict, which operation of the update the (first) cut fell before (`None` for the update left to finish) |

Set `update_on_boot = True` on the driver if the reset itself starts the update, as
`staged_slot` does. The `session` gives you the UART (`uart_write`, `uart_text`), time
(`run_for`), flash (`load_binary`, `read_bytes`) and resets (`reboot`, `power_cycle`).
[adapters/three_tier_f103/driver.py](../adapters/three_tier_f103/driver.py) is about 90 lines.

## Bad update content

`scenario.content_faults` runs, after the cuts, the update with damaged images in place of
the staged one. Nothing is cut: the bootloader has to refuse the image. The driver must say
what it stages (`staged()`, which `staged_slot` has), and the adapter needs an oracle.

| Key | Meaning |
|---|---|
| `keep` | the oracle image that must still be installed and running afterwards (required) |
| `image_size` | bytes of the staged file that are the image. The rest, such as MCUboot's padded trailer that asks for the upgrade, is kept, so the bootloader does try the damaged image. Default: read from the image's header when it is an MCUboot image, else the whole file. Leave it out for MCUboot: a rebuild changes the size |
| `mutations` | which built-in ones to run: `truncate` (at a quarter, a half, three quarters and four bytes short), `flip` (one bit in the middle of each region), `erased`. Default all |
| `regions` | `{name: [start, end]}` offsets in the image to flip a bit in, for example header, body and the signature area. Default: an MCUboot image's header, body and TLV area (hash and signature), read from it; else the whole image as one region |
| `images` | `{name: file}`: bad images made elsewhere (signed with another key, older, built for another slot), staged as they are |

## Worn pages

`flash.worn: {from: 0x08002000, size: 0x400}` marks part of the flash as worn out. A program
there is accepted (no error flag, nothing refused) but bit 0 of each cell keeps the value it
had, as when a cell no longer takes charge: the data read back differs from what was written.
Erases still work. Use it on the pages an update writes, to see whether the bootloader reads
back what it wrote and what it does when that fails.

## Bit errors at rest

`scenario.bit_errors` takes the flash the uninterrupted update left, flips `flips` bits (default
1) at random in a region, `runs` times per region (default 4), with `seed` (default 0) so a run
repeats, and powers up. Pass: the CPU is not executing inside that region and is not in a
fault handler. `regions` names `{name: [start, end]}` addresses; the default is every image the
oracle accepts, where it is installed. Name the bytes the image really uses where it has
unused padding (the demo's header area is 0x200 bytes, of which 16 are used): a flip in bytes
nothing reads changes nothing, and the device is right to run the image.

## A broken link

`scenario.link_cuts: {points: 8, wait: 2}` (or `true` for those values) is for drivers that
send the update over the UART. The uninterrupted update counts the bytes the host sends.
Then, for each of `points` byte counts spread over that session plus the first and the last
byte, a run lets only that many bytes reach the device and drops the rest, as when the cable
comes out; the driver's session fails as it would. After `wait` virtual seconds the link is
back, the driver's `start_update()` runs again (the host tries from the start), and the
usual verdict follows: alive, the oracle, and the driver's `check_recovered()`.

## The oracle

Without an `oracle` section the verdict rests on what the firmware says about itself, and
the run says so. With one, a result only passes if the bytes at `at` are exactly one of the
accepted images and the CPU is executing inside it, not in a fault handler. List every image
that may legitimately be there, and put in `accept` the ones a cut is allowed to leave.

Seen running is not enough: a device can boot its image and be reset by its watchdog half a
second later, over and over, and every quick look finds it running. So the oracle then lets
the device run for `stable_for` seconds more (1 by default) and fails the cut if it reset in
that time, or if it is no longer running an accepted image at the end. Set it above the
longest watchdog timeout the firmware uses. Resets are counted by the Renode flash models;
on m33mu, which does not count them, only the second look is made.

## Choosing cuts

- `plan: every` cuts at every distinct flash state the update goes through. Use it when the
  update is a few hundred operations.
- `plan: phases` cuts every state in short phases and samples long ones (`per_phase` cuts
  each; phases of up to `small` operations are cut everywhere). The report names what was
  sampled. `--plan every` on the command line overrides it for one run.
- `real_every: N` makes every Nth cut in the emulator and powers the device up from the
  computed flash state for the others, which is several times faster and checked against
  the real cuts.
- `--shard K/N` on the command line runs every Nth cut, starting with the Kth. Give N
  machines the same command with K from 1 to N and together they make the whole campaign.
  `.github/workflows/exhaustive.yml` does that for the Three-Tier bootloader.
- `torn` adds states where the power failed inside an erase or a program.
- `depth: 2` cuts again while the device is recovering from the first cut.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | every cut recovered |
| 1 | at least one cut did not, or the update fails with no cut at all |
| 2 | the adapter could not be read |
| 3 | the tool itself failed (Renode would not start, or the self-check found the emulated flash differing from the golden run) |
