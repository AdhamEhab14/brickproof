/* The demo on an STM32L476: 1 MB of flash in two banks of 2 KB pages, programmed 64 bits
 * at a time, each double word with its own ECC. A double word is written once between
 * erases (all zeros is the one exception), and a program or erase cut short can leave its
 * ECC wrong: a read of it then raises an NMI with ECCD set. */
#ifndef CHIP_H
#define CHIP_H

/* ---- flash map ----------------------------------------------------------- */
#define BL_BASE        0x08000000u   /* pages 0-7, 16 KB: bootloader              */
#define META_0         0x08004000u   /* page 8: rollback floor, in two pages, so  */
#define META_1         0x08004800u   /* page 9: one is always intact              */
#define SLOT_A         0x08020000u   /* pages 64-127, 128 KB: the image that runs  */
#define SLOT_B         0x08040000u   /* pages 128-191, 128 KB: staging             */
#define SLOT_SIZE      0x20000u
#define FLASH_PAGE     0x800u
#define FLASH_BANK     0x80000u      /* bank 2 starts half way                     */

/* ---- uart: USART2 on PA2, the bus at the reset 4 MHz MSI ------------------ */
#define RCC_AHB2ENR    REG(0x4002104Cu)
#define RCC_APB1ENR1   REG(0x40021058u)
#define GPIOA_MODER    REG(0x48000000u)
#define GPIOA_AFRL     REG(0x48000020u)
#define UART_BRR_115200 35u          /* 4 MHz / 115200 */

static inline void uart_pins(void)
{
    RCC_AHB2ENR |= (1u << 0);                         /* GPIOA */
    RCC_APB1ENR1 |= (1u << 17);                       /* USART2 */
    GPIOA_MODER = (GPIOA_MODER & ~(3u << 4)) | (2u << 4);   /* PA2: alternate function */
    GPIOA_AFRL = (GPIOA_AFRL & ~(0xFu << 8)) | (7u << 8);   /* AF7 is USART2 */
}

/* ---- flash --------------------------------------------------------------- */
#define FLASH_KEYR     REG(0x40022008u)
#define FLASH_SR       REG(0x40022010u)
#define FLASH_CR       REG(0x40022014u)
#define FLASH_ECCR     REG(0x40022018u)
#define CR_PG          (1u << 0)
#define CR_PER         (1u << 1)
#define CR_PNB(n)      ((uint32_t)(n) << 3)
#define CR_BKER        (1u << 11)
#define CR_STRT        (1u << 16)
#define CR_LOCK        (1u << 31)
#define SR_BSY         (1u << 16)
#define SR_ERRORS      0xC3FAu       /* every error flag, and EOP: write 1 to clear */
#define ECCR_ECCD      (1u << 31)

typedef uint64_t cell_t;              /* what one program writes */

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

/* Erase every page that has a byte in `addr` .. `addr + size`. */
static inline void flash_erase(uint32_t addr, uint32_t size)
{
    for (uint32_t a = addr & ~(FLASH_PAGE - 1u); a < addr + size; a += FLASH_PAGE) {
        uint32_t off = a - BL_BASE;
        uint32_t bank = off >= FLASH_BANK ? CR_BKER : 0;
        FLASH_SR = SR_ERRORS;             /* an old error flag would stop the erase */
        FLASH_CR = (FLASH_CR & ~(CR_PNB(0xFF) | CR_BKER)) | CR_PER | bank
                   | CR_PNB((off % FLASH_BANK) / FLASH_PAGE);
        FLASH_CR |= CR_STRT;
        flash_wait();
        FLASH_CR &= ~(CR_PER | CR_PNB(0xFF) | CR_BKER);
    }
}

/* A double word: two word stores, the first at the 8-byte boundary. The chip refuses
 * anything else, and refuses every program after that until the error flag is cleared. */
static inline void flash_cell(uint32_t addr, cell_t v)
{
    FLASH_SR = SR_ERRORS;
    FLASH_CR |= CR_PG;
    *(volatile uint32_t *)addr = (uint32_t)v;
    *(volatile uint32_t *)(addr + 4) = (uint32_t)(v >> 32);
    flash_wait();
    FLASH_CR &= ~CR_PG;
}

/* Programming mode on or off, for code that writes many cells in one go. */
static inline void flash_pg(int on)
{
    if (on) {
        FLASH_SR = SR_ERRORS;
        FLASH_CR |= CR_PG;
    } else {
        FLASH_CR &= ~CR_PG;
    }
}

/* ---- ECC ----------------------------------------------------------------- */

/* Set by the NMI handler when a read hit a double word whose ECC is wrong. Whatever was
 * read with it set is not to be trusted. */
extern volatile int ecc_error;

static inline void ecc_clear(void)
{
    ecc_error = 0;
}

static inline int ecc_seen(void)
{
    return ecc_error;
}

#endif
