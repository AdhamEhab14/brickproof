/* The demo on an STM32F103RB: 128 KB of flash in 1 KB pages, programmed a
 * halfword at a time. */
#ifndef CHIP_H
#define CHIP_H

/* ---- flash map ----------------------------------------------------------- */
#define BL_BASE        0x08000000u   /*  8 KB bootloader                     */
#define SLOT_A         0x08002000u   /* 56 KB the image that runs            */
#define SLOT_B         0x08010000u   /* 56 KB staging: a new image waits here */
#define SLOT_SIZE      0xE000u
#define META_0         0x0801E000u   /* rollback floor, two pages so one is  */
#define META_1         0x0801E400u   /* always intact while the other is rewritten */

/* ---- uart: USART2 on PA2, the bus at the reset 8 MHz HSI ------------------ */
#define RCC_APB2ENR    REG(0x40021018u)
#define RCC_APB1ENR    REG(0x4002101Cu)
#define GPIOA_CRL      REG(0x40010800u)
#define UART_BRR_115200 0x45u

static inline void uart_pins(void)
{
    RCC_APB2ENR |= (1u << 2);                         /* GPIOA */
    RCC_APB1ENR |= (1u << 17);                        /* USART2 */
    GPIOA_CRL = (GPIOA_CRL & ~(0xFu << 8)) | (0xBu << 8);   /* PA2: AF push-pull */
}

/* ---- flash --------------------------------------------------------------- */
#define FLASH_KEYR     REG(0x40022004u)
#define FLASH_OPTKEYR  REG(0x40022008u)
#define FLASH_SR       REG(0x4002200Cu)
#define FLASH_CR       REG(0x40022010u)
#define FLASH_AR       REG(0x40022014u)
#define FLASH_WRPR     REG(0x40022020u)
#define CR_PG          (1u << 0)
#define CR_PER         (1u << 1)
#define CR_OPTPG       (1u << 4)
#define CR_OPTER       (1u << 5)
#define CR_STRT        (1u << 6)
#define CR_LOCK        (1u << 7)
#define SR_BSY         (1u << 0)
#define OPTION_BYTES   0x1FFFF800u
#define PAGE_SIZE      0x400u

typedef uint16_t cell_t;              /* what one program writes */

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

/* Erase everything from `addr` up to `addr + size`, page by page. */
static inline void flash_erase(uint32_t addr, uint32_t size)
{
    for (uint32_t page = addr; page < addr + size; page += PAGE_SIZE) {
        FLASH_CR |= CR_PER;
        FLASH_AR = page;
        FLASH_CR |= CR_STRT;
        flash_wait();
        FLASH_CR &= ~CR_PER;
    }
}

/* Programming 0x0000 over a written halfword is allowed on the F1; any other
 * value over a cell that is not erased is refused. */
static inline void flash_cell(uint32_t addr, cell_t v)
{
    FLASH_CR |= CR_PG;
    *(volatile cell_t *)addr = v;
    flash_wait();
    FLASH_CR &= ~CR_PG;
}

/* Programming mode on or off, for code that writes many cells in one go. */
static inline void flash_pg(int on)
{
    if (on)
        FLASH_CR |= CR_PG;
    else
        FLASH_CR &= ~CR_PG;
}

static inline void flash_word(uint32_t addr, uint32_t v)
{
    flash_cell(addr, (uint16_t)v);
    flash_cell(addr + 2, (uint16_t)(v >> 16));
}

#ifdef BUG_SELF_LOCK
/* Write-protect the bootloader's own two 4 KB units, the usual way on an F1:
 * erase the option bytes, then write all of them back. A cut in between leaves
 * the chip read-protected, and when the next boot writes "unprotected" again the
 * chip answers by mass-erasing the flash. */
static inline void lock_bootloader(void)
{
    static const uint16_t bytes[8] = {
        0x00A5,                 /* RDP: not read-protected */
        0x00FF, 0x00FF, 0x00FF, /* USER, Data0, Data1 */
        0x00FC,                 /* WRP0: units 0 and 1 protected */
        0x00FF, 0x00FF, 0x00FF, /* WRP1..WRP3 */
    };

    if ((FLASH_WRPR & 3u) == 0)
        return;                 /* already done */
    FLASH_OPTKEYR = 0x45670123u;
    FLASH_OPTKEYR = 0xCDEF89ABu;
    FLASH_CR |= CR_OPTER;
    FLASH_CR |= CR_STRT;
    flash_wait();
    FLASH_CR &= ~CR_OPTER;
    for (uint32_t i = 0; i < 8; i++) {
        FLASH_CR |= CR_OPTPG;
        *(volatile uint16_t *)(OPTION_BYTES + 2 * i) = bytes[i];
        flash_wait();
        FLASH_CR &= ~CR_OPTPG;
    }
}
#endif

#endif
