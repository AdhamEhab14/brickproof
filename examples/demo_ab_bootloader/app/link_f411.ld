/* The app runs from Slot A, after the 0x200-byte image header area. */
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08020200, LENGTH = 0x1FE00
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}
INCLUDE sections.ld
