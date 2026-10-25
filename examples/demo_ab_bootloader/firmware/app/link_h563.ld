/* The app runs from Slot A, after the 0x200-byte image header area. */
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x0C010200, LENGTH = 0xFE00
    RAM   (rwx) : ORIGIN = 0x30000000, LENGTH = 640K
}
INCLUDE sections.ld
