# Testing the chip rules one by one, and the F1's option byte check (plan item 6)

2026-10-16

The flash models' rules were only ever checked through whole firmware runs (a bug build is
caught or it is not). The plan's chip-detail items ask for a test per rule, so `tests/renode`
now boots the demo's chip in Renode and checks a rule directly: load a flash image, reset,
then read the controller's registers off the bus, no test firmware needed for register rules.
They are skipped where Renode is not installed and run in CI as `model-rules`. Each new rule
gets a test that fails without the change (checked by running the tests on the old model).

**F1 option bytes.** RM0008 (FLASH_OBR): at reset each option byte is checked against its
complement, and where they do not match OPTERR is set and the byte and its complement read as
0xFF. The model loaded the bytes as they were. Now it checks each pair. What that changes:
OBR's OPTERR bit, and a byte with a bad complement loads as 0xFF. For RDP that is "protected"
(any value but 0xA5 is), for a WRP byte "not protected"; erased option bytes (0xFF/0xFF) give
OPTERR and read protection, as before minus the flag. Data0 and Data1 were already in OBR;
the tests now cover them. Tests: good bytes (no OPTERR, Data0/Data1 in place), a bad WRP0 and
a bad Data0 complement, a bad RDP complement, all erased. Three of the four fail on the old
model. The USER bits nRST_STOP and nRST_STDBY come with the low-power modes (item 4).
