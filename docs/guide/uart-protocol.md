# An update sent over the UART

Here a host program sends the update over the UART with the bootloader's own protocol (a
programming session, frames, acknowledgements). BrickProof cuts power during the session,
and can also break the link part-way while the device keeps its power. You describe the
protocol in a short `driver.py`. Two complete ones: [OpenBLT](../../adapters/openblt_f103)
(XCP) and the [Three-Tier bootloader](../../adapters/three_tier_f103), which calls the
bootloader's own host tools so the device sees exactly the bytes the real host sends.

1. **Build** the bootloader and the image the host will send.

2. **Write the adapter and a driver to fill in.** `init` writes both; the driver has a
   `TODO` in each method BrickProof calls:

   ```bash
   brickproof init --kind protocol
   ```

   `start_update()` sends the update (`session.uart_write`, `session.uart_text`, or
   `RenodeSerial` for a host tool that wants a serial port), `alive()` asks the bootloader
   something it answers, and `check_recovered()` says whether a cut left the device usable.

3. **Check it**:

   ```bash
   brickproof check brickproof.yaml
   ```

4. **Trace one whole update** with no cut, to see that the driver works and what the
   update does to flash:

   ```bash
   brickproof trace brickproof.yaml
   ```

5. **Cut it**, first quickly, then everything; add `scenario.link_cuts: true` to break the
   link at points through the session too:

   ```bash
   brickproof run brickproof.yaml --quick
   brickproof run brickproof.yaml --full
   ```
