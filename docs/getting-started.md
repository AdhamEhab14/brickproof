# Getting started

You need Python 3.10+. No toolchain, no board, no firmware of your own: a demo comes with the
package, and `brickproof setup` downloads the emulator ([Renode](https://renode.io) 1.17, checked
against its published SHA-256) for Windows or Linux.

```bash
pip install brickproof-fw
brickproof setup
brickproof demo
```

(A Renode you installed yourself works too: put `renode` on PATH or set `RENODE_PATH`. On a
Mac, install Renode's .dmg. For an STM32H5 you need [m33mu](https://github.com/danielinux/m33mu)
instead, commit 23960ed or later, on PATH or in `M33MU_PATH`.)

The demo is a small A/B bootloader updating its app from v1 to v2. BrickProof first checks
that the update works when nothing interrupts it, then cuts power at every flash state the
update goes through, one per line:

```
PASS baseline (no cut)   168 ops                       2.2s  runs v2
PASS op-0                op 0     erase 0x0801E400     1.8s  runs v2
PASS op-1                op 1     program 0x0801E400   1.7s  runs v2
...
167/167 cuts recovered
coverage: 167 cut(s) over 167 distinct flash states (168 operations): every state is cut
```

Now run a build with a known bug. BrickProof should catch it:

```bash
brickproof demo self_lock --fail-fast
```

`brickproof demo --list` shows all of them:

| Build | The mistake | What happens |
|---|---|---|
| `consume_first` | marks the staged image used before copying it | a cut leaves no valid image: bricked |
| `trust_header` | copies the header first and trusts it without a CRC | boots a half-copied image |
| `naive_floor` | rewrites the anti-rollback floor in place, after the install | an older image can be installed again |
| `pop_after_switch` | pops saved registers after switching to the app's stack | reads past the end of RAM: bus fault on every boot |
| `no_erase` | copies the new image over the old one without erasing | the chip refuses to program cells that are not erased |
| `no_unlock` | never unlocks the flash controller | the chip ignores every write: the update silently does nothing |
| `early_unpg` | stores every second cell after programming mode is off again | the chip ignores those stores: half the image is never written |
| `protected_slot` | (a device setting) the app slot is write-protected | the chip refuses every erase and program there |
| `resume_copy` | after an interrupted install, skips the erase and writes only what is missing | survives every clean cut; a torn write leaves a cell the chip will not program again |
| `retry_limit` | gives up on an update after two interrupted attempts | survives any single cut; two cuts in a row lose the update |
| `self_lock` | write-protects its own flash from the bootloader, in the field | a cut while the option bytes are erased, and the retry mass-erases the flash |

The first three are the bugs BrickProof found in the Three-Tier bootloader. `pop_after_switch`
was found by a real board after an emulator had passed it. The rest are mistakes a plain
emulator lets through and a chip does not.

The demo also builds for an **STM32F411**, a chip that differs from the F103 in everything a
power cut touches: an erase wipes a whole sector of 16 to 128 KB, a program writes a word and
is never refused (the cell ends up as old AND new), and the chip rewrites its own option
bytes. `brickproof demo f411` runs the correct build, and `brickproof demo f411-bug-no_erase`
and the other `f411-bug-*` builds have the same mistakes. `resume_copy` is missing there on
purpose: an F4 does let a half-written cell be programmed again, so it is not a bug on that chip.
It has one of its own instead, `f411-bug-watchdog`: on a device with a hardware watchdog, a
sector erase that takes a second gets the chip reset half way through, on every attempt.
`watchdog` and `f411-watchdog` are the correct build on such a device, and `hold_pg` and
`f411-hold_pg` are the correct build writing flash the other common way, with programming
mode left on over a whole run of cells.

And for an **nRF52840**, which has no flash keys at all: one register (CONFIG) says whether a
store is a program, whether an erase is allowed, or neither. `brickproof demo nrf52` and the
`nrf52-bug-*` builds have the mistakes that apply there (`early_unpg` becomes a store made
with CONFIG back to read-only). It has two of its own. `nrf52-bug-nwrite`: progress kept by
clearing one more bit of the same word after each step. An STM32F4 takes that; the nRF52
promises only two writes to a word between erases. And `nrf52-bug-boot_loop`: a cut just
before the install's last step sends the bootloader into a trial boot under the watchdog
that this app cannot pass. The new image is installed and prints its banner, and half a
second later the watchdog resets it, on every boot.

And for an **STM32L476**: `brickproof demo l476`. Every 64 bits of its flash carry ECC, and an
erase or program cut short leaves the ECC wrong, so the next read of that double word raises
an NMI. The bootloader has to catch it; `l476-bug-no_ecc_nmi` does not, and only torn states
find that.

And for an **STM32H563**, on m33mu: `brickproof demo h563`. The H5 programs a 128-bit word with
its ECC in one operation, and a word programmed once cannot be programmed again before its
sector is erased, so the update is 26 operations and the `h563-bug-*` builds meet a chip that
refuses what the F-series accepts. Its torn states found a bug in the port itself: a torn
program of the "staging slot consumed" marker was retried, over the half-written word.
The bootloader now takes any cleared bit in the marker as consumed.
