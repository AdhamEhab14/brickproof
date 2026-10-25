# Limits

- The device is emulated. Two of the torn erase shapes are measured on a real STM32F103,
  with the erase stopped by a reset; the others, and every torn program, are models. A real
  power loss, which lets the supply sag, is not measured yet.
- Flash is modelled for STM32F1 (pages, halfword programming), STM32F411 (sectors, byte
  to double-word programming), STM32L476 (2 KB pages, 64-bit programs with ECC) and nRF52840
  (4 KB pages, word programming, at most two writes to a word between erases) in
  `src/brickproof/models/` for Renode; m33mu models the STM32H5 (128-bit programs, write
  protection, bank swap) itself. Another family needs a model of its flash controller in one
  emulator or the other; the engine itself assumes neither.
- On m33mu, option bytes are kept apart from the flash image: a run starts every cut from the
  option bytes as shipped, and a cut while the firmware changes them is not modelled.
- Flash timing uses datasheet figures (typical or slowest), not measurements, and does not
  vary with temperature, voltage or age. Wear is counted per update, not simulated.
- An external flash chip is modelled as SPI NOR with the 25-series commands in single-line
  mode (four-byte addressing included), or as an I2C EEPROM. Quad and dual modes, NAND and
  SD cards are not.
