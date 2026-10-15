/* The demo on an STM32H563, running secure from the secure flash alias. 2 MB of
 * flash in two banks of 128 sectors of 8 KB (RM0481); the demo stays in bank 1.
 *
 * What a power cut meets here is unlike either F-series chip: a program writes a
 * whole 128-bit word with its ECC, and a word that has been programmed must not be
 * programmed again until its sector is erased (the ECC would no longer match). So a
 * cell is 16 bytes, and nothing is ever written twice: where the F1 and F4 builds
 * mark Slot B consumed by programming zeros over its magic, this one programs a
 * marker cell of its own (CELL_IS_BLOCK in bootloader/main.c). */
#ifndef CHIP_H
#define CHIP_H

/* ---- flash map ----------------------------------------------------------- */
#define BL_BASE        0x0C000000u   /* sector 0, 8 KB: bootloader. Sectors 0 to 3 are
                                        one write-protection group, kept for it */
#define META_0         0x0C008000u   /* sector 4: rollback floor, in two sectors */
#define META_1         0x0C00A000u   /* sector 5: so one is always intact        */
#define SLOT_A         0x0C010000u   /* sectors 8 to 15, 64 KB: the image that runs */
#define SLOT_B         0x0C020000u   /* sectors 16 to 23, 64 KB: staging          */
#define SLOT_SIZE      0x10000u
#define SECTOR_SIZE    0x2000u

/* Slot B's consumed marker: a cell of its own in the header area, which images
 * leave erased (the app starts at +0x200). */
#define CONSUMED       (SLOT_B + 0x40u)

/* ---- uart: USART3 on PD8, the Nucleo-H563ZI's virtual COM port ------------
 * Peripherals are left non-secure, so the secure code reaches them through their
 * non-secure addresses. The kernel clock is the reset HSI, 64 MHz divided by 2. */
#define RCC_AHB2ENR    REG(0x44020C8Cu)
#define RCC_APB1LENR   REG(0x44020C9Cu)
#define GPIOD_MODER    REG(0x42020C00u)
#define GPIOD_AFRH     REG(0x42020C24u)
#define UART_SR        REG(0x4000481Cu)   /* ISR: bit 7 is TXE, as SR's on the F1 */
#define UART_DR        REG(0x40004828u)   /* TDR */
#define UART_BRR       REG(0x4000480Cu)
#define UART_CR1       REG(0x40004800u)
#define UART_CR1_ON    ((1u << 0) | (1u << 3))   /* UE, TE */
#define UART_BRR_115200 0x116u                   /* 32 MHz / 115200 */

static inline void uart_pins(void)
{
    RCC_AHB2ENR |= (1u << 3);                         /* GPIOD */
    RCC_APB1LENR |= (1u << 18);                       /* USART3 */
    GPIOD_MODER = (GPIOD_MODER & ~(3u << 16)) | (2u << 16);   /* PD8: alternate function */
    GPIOD_AFRH = (GPIOD_AFRH & ~0xFu) | 7u;                   /* AF7 is USART3 */
}

/* ---- flash: the secure registers, through the secure alias ----------------- */
#define FLASH_SECKEYR  REG(0x50022008u)
#define FLASH_SECSR    REG(0x50022024u)
#define FLASH_SECCR    REG(0x5002202Cu)
#define FLASH_SECCCR   REG(0x50022034u)
#define CR_LOCK        (1u << 0)
#define CR_PG          (1u << 1)
#define CR_SER         (1u << 2)
#define CR_STRT        (1u << 5)
#define CR_SNB(n)      ((uint32_t)(n) << 6)
#define SR_BSY         (1u << 0)
#define SR_WBNE        (1u << 1)
#define SR_DBNE        (1u << 3)

#define CELL_IS_BLOCK  1
typedef struct {
    uint32_t w[4];
} cell_t;                             /* what one program writes: 128 bits */

static const cell_t CELL_ZERO = {{0, 0, 0, 0}};

static inline int cell_same(const volatile cell_t *a, const cell_t *b)
{
    return a->w[0] == b->w[0] && a->w[1] == b->w[1] && a->w[2] == b->w[2] && a->w[3] == b->w[3];
}

static inline int cell_clear(const volatile cell_t *a)
{
    return (a->w[0] | a->w[1] | a->w[2] | a->w[3]) == 0;
}

static inline void flash_wait(void)
{
    while (FLASH_SECSR & (SR_BSY | SR_WBNE | SR_DBNE))
        ;
}

/* Writing the keys to a controller that is already unlocked locks it until the
 * next reset, so only when it is locked. */
static inline void flash_unlock(void)
{
    if (FLASH_SECCR & CR_LOCK) {
        FLASH_SECKEYR = 0x45670123u;
        FLASH_SECKEYR = 0xCDEF89ABu;
    }
}

static inline void flash_lock(void)
{
    FLASH_SECCR |= CR_LOCK;
}

/* Erase every sector that has a byte in `addr` .. `addr + size`. */
static inline void flash_erase(uint32_t addr, uint32_t size)
{
    uint32_t first = (addr - BL_BASE) / SECTOR_SIZE;
    uint32_t last = (addr + size - 1u - BL_BASE) / SECTOR_SIZE;
    for (uint32_t n = first; n <= last; n++) {
        FLASH_SECCR = (FLASH_SECCR & ~(CR_PG | CR_SNB(0x7F))) | CR_SER | CR_SNB(n);
        FLASH_SECCR |= CR_STRT;
        flash_wait();
        FLASH_SECCR &= ~(CR_SER | CR_SNB(0x7F));
        wdg_feed();
    }
}

/* One 128-bit program: four word stores fill the write buffer, and the fourth
 * starts the program. */
static inline void flash_cell(uint32_t addr, cell_t v)
{
    volatile uint32_t *p = (volatile uint32_t *)addr;
    FLASH_SECCR |= CR_PG;
    p[0] = v.w[0];
    p[1] = v.w[1];
    p[2] = v.w[2];
    p[3] = v.w[3];
    flash_wait();
    FLASH_SECCR &= ~CR_PG;
}

/* Programming mode on or off, for code that writes many cells in one go. */
static inline void flash_pg(int on)
{
    if (on)
        FLASH_SECCR |= CR_PG;
    else
        FLASH_SECCR &= ~CR_PG;
}

/* A cell as plain stores, for code that keeps PG set itself (HOLD_PG and the
 * BUG_EARLY_UNPG build). */
static inline void cell_store(uint32_t addr, const cell_t *v)
{
    volatile uint32_t *p = (volatile uint32_t *)addr;
    p[0] = v->w[0];
    p[1] = v->w[1];
    p[2] = v->w[2];
    p[3] = v->w[3];
}

#endif
