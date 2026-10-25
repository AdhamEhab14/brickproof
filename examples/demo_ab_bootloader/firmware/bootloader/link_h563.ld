/* STM32H563, secure: the bootloader in sector 0 of the secure flash alias. */
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x0C000000, LENGTH = 8K
    RAM   (rwx) : ORIGIN = 0x30000000, LENGTH = 640K
}
INCLUDE sections.ld
