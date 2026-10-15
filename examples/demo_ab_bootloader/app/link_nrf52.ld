/* The app runs from Slot A, after the 0x200-byte image header area. */
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00010200, LENGTH = 0x1FE00
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 256K
}
INCLUDE sections.ld
