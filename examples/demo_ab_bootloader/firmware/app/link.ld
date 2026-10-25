/* The app runs from Slot A, after the 0x200-byte image header area. */
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08002200, LENGTH = 0xDE00
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 20K
}
INCLUDE sections.ld
