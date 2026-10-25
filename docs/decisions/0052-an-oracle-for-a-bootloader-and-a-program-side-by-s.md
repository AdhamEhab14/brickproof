# An oracle for a bootloader and a program side by side

2026-10-12

The oracle was written for one slot that holds the old image or the new one. A bootloader
that reprograms the application in place (no second slot) does not fit that: after a cut
there is no approved application at all, by design, and the right state is "the bootloader
is intact and running, waiting to be given the program again".

Images can now be approved at different addresses. At each address the installed one is
found as before (longest match). If more than one address has an approved image, the core
must be running inside one of those that the scenario accepts, and it may move from one to
the other between two looks, because a bootloader hands over. With a single address nothing
changes, messages included.

Two things the same outside project showed (both dealt with in the next entry):
- Emulated peripheral clocks do not follow the firmware's clock setup. Renode gives a timer
  a fixed input clock (10 MHz by default), so firmware that sets a prescaler for the 72 MHz
  it configured sees time run 7.2 times too slowly. An adapter can state the clock in its
  extra platform lines, which is what the Three-Tier adapter already does for its UARTs.
  The proper fix is for the RCC model to tell the peripherals.
- An input pin nobody drives reads low. Firmware that reads a button at start-up needs the
  adapter to set the pin (`reset:` lines).
