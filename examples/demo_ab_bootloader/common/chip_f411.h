/* The demo on an STM32F411: 512 KB of flash in eight sectors of 16, 64 and
 * 128 KB, programmed a word at a time. An erase wipes a whole sector, so each
 * part of the map gets sectors of its own. */
#ifndef CHIP_H
#define CHIP_H

/* ---- flash map ----------------------------------------------------------- */
#define BL_BASE        0x08000000u   /* sector 0, 16 KB: bootloader              */
#define META_0         0x08004000u   /* sector 1, 16 KB: rollback floor, in two  */
#define META_1         0x08008000u   /* sector 2, 16 KB: sectors, so one is always intact */
#define SLOT_A         0x08020000u   /* sector 5, 128 KB: the image that runs    */
#define SLOT_B         0x08040000u   /* sector 6, 128 KB: staging                */
#define SLOT_SIZE      0x20000u

/* ---- uart: USART2 on PA2, the bus at the reset 16 MHz HSI ----------------- */
#define RCC_AHB1ENR    REG(0x40023830u)
#define RCC_APB1ENR    REG(0x40023840u)
#define GPIOA_MODER    REG(0x40020000u)
#define GPIOA_AFRL     REG(0x40020020u)
#define UART_BRR_115200 0x8Bu

static inline void uart_pins(void)
{
    RCC_AHB1ENR |= (1u << 0);                         /* GPIOA */
    RCC_APB1ENR |= (1u << 17);                        /* USART2 */
    GPIOA_MODER = (GPIOA_MODER & ~(3u << 4)) | (2u << 4);   /* PA2: alternate function */
    GPIOA_AFRL = (GPIOA_AFRL & ~(0xFu << 8)) | (7u << 8);   /* AF7 is USART2 */
}

/* ---- flash --------------------------------------------------------------- */
#define FLASH_KEYR     REG(0x40023C04u)
#define FLASH_OPTKEYR  REG(0x40023C08u)
#define FLASH_SR       REG(0x40023C0Cu)
#define FLASH_CR       REG(0x40023C10u)
#define FLASH_OPTCR    REG(0x40023C14u)
#define CR_PG          (1u << 0)
#define CR_SER         (1u << 1)
#define CR_SNB(n)      ((uint32_t)(n) << 3)
#define CR_PSIZE_32    (2u << 8)
#define CR_STRT        (1u << 16)
#define CR_LOCK        (1u << 31)
#define SR_BSY         (1u << 16)
#define OPTCR_OPTSTRT  (1u << 1)

typedef uint32_t cell_t;              /* what one program writes */

static inline void flash_wait(void)
{
    while (FLASH_SR & SR_BSY)
        ;
}

static inline void flash_unlock(void)
{
    FLASH_KEYR = 0x45670123u;
    FLASH_KEYR = 0xCDEF89ABu;
}

static inline void flash_lock(void)
{
    FLASH_CR |= CR_LOCK;
}

/* Where sector n ends: four of 16 KB, one of 64 KB, three of 128 KB. */
static inline uint32_t sector_end(uint32_t n)
{
    if (n < 4)
        return 0x08004000u + n * 0x4000u;
    return n == 4 ? 0x08020000u : 0x08040000u + (n - 5) * 0x20000u;
}

/* Erase every sector that has a byte in `addr` .. `addr + size`. */
static inline void flash_erase(uint32_t addr, uint32_t size)
{
    for (uint32_t n = 0; n < 8; n++) {
        uint32_t start = n ? sector_end(n - 1) : 0x08000000u;
        if (sector_end(n) <= addr || start >= addr + size)
            continue;
        /* PSIZE counts for an erase too: at 32 bits it is the fastest the chip does */
        FLASH_CR = (FLASH_CR & ~(CR_SNB(0xF) | (3u << 8))) | CR_PSIZE_32 | CR_SER | CR_SNB(n);
        FLASH_CR |= CR_STRT;
        flash_wait();
        FLASH_CR &= ~(CR_SER | CR_SNB(0xF));
    }
}

/* A program on the F4 can only clear bits: over a cell that is not erased, the
 * result is the old value AND the new one, and no error says so. */
static inline void flash_cell(uint32_t addr, cell_t v)
{
    FLASH_CR = (FLASH_CR & ~(3u << 8)) | CR_PSIZE_32 | CR_PG;
    *(volatile cell_t *)addr = v;
    flash_wait();
    FLASH_CR &= ~CR_PG;
}

/* Programming mode on or off, for code that writes many cells in one go. */
static inline void flash_pg(int on)
{
    if (on)
        FLASH_CR = (FLASH_CR & ~(3u << 8)) | CR_PSIZE_32 | CR_PG;
    else
        FLASH_CR &= ~CR_PG;
}

static inline void flash_word(uint32_t addr, uint32_t v)
{
    flash_cell(addr, v);
}

#ifdef BUG_SELF_LOCK
/* Write-protect the bootloader's own sector by setting the option register to what
 * it "should" be: everything at its factory value, sector 0 protected. The chip
 * erases its option bytes and writes them again by itself. A cut in between leaves
 * them erased, which reads as read protection level 1, and when the next boot asks
 * for level 0 again the chip answers by mass-erasing the flash. */
static inline void lock_bootloader(void)
{
    if ((FLASH_OPTCR & (1u << 16)) == 0)
        return;                 /* already done */
    FLASH_OPTKEYR = 0x08192A3Bu;
    FLASH_OPTKEYR = 0x4C5D6E7Fu;
    FLASH_OPTCR = 0x0FFEAAECu;  /* RDP level 0, sector 0 write-protected */
    FLASH_OPTCR |= OPTCR_OPTSTRT;
    flash_wait();
}
#endif

#endif
