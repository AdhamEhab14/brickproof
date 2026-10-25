/* The demo on an nRF52840: 1 MB of flash at address 0, in pages of 4 KB, written
 * a whole aligned word at a time. The flash controller (NVMC) has no keys and no
 * lock: CONFIG says whether stores are programs (Wen), whether ERASEPAGE erases
 * (Een), or neither (Ren). A word can be written at most twice between two erases. */
#ifndef CHIP_H
#define CHIP_H

/* ---- flash map ----------------------------------------------------------- */
#define BL_BASE        0x00000000u   /* pages 0-3, 16 KB: bootloader              */
#define META_0         0x00004000u   /* page 4: rollback floor, in two pages so    */
#define META_1         0x00005000u   /* page 5: one is always intact               */
#define SLOT_A         0x00010000u   /* 128 KB: the image that runs                */
#define SLOT_B         0x00030000u   /* 128 KB: staging                            */
#define SLOT_SIZE      0x20000u
#define PAGE_SIZE      0x1000u

/* ---- uart: UARTE0, sending from RAM by EasyDMA ---------------------------- */
#define UARTE0_STARTTX REG(0x40002008u)
#define UARTE0_ENDTX   REG(0x40002120u)
#define UARTE0_ENABLE  REG(0x40002500u)
#define UARTE0_PSELTXD REG(0x4000250Cu)
#define UARTE0_BAUD    REG(0x40002524u)
#define UARTE0_TXDPTR  REG(0x40002544u)
#define UARTE0_TXDMAX  REG(0x40002548u)
#define UARTE_BAUD_115200 0x01D7E000u

static inline void uart_hw_init(void)
{
    UARTE0_PSELTXD = 6u;              /* P0.06, the DK's TX line to the J-Link VCOM */
    UARTE0_BAUD = UARTE_BAUD_115200;
    UARTE0_ENABLE = 8u;               /* 8 is UARTE; 4 would be the old UART */
}

/* EasyDMA reads RAM only, so even one character goes through a RAM buffer. */
static inline void uart_hw_send(const char *buf, uint32_t n)
{
    UARTE0_TXDPTR = (uint32_t)buf;
    UARTE0_TXDMAX = n;
    UARTE0_ENDTX = 0;
    UARTE0_STARTTX = 1;
    while (!UARTE0_ENDTX)
        ;
}

/* ---- watchdog -------------------------------------------------------------
 * The WDT runs only once something starts it, and its timeout cannot change while
 * it runs. Reloading it when it is stopped does nothing, so feeding is always safe. */
#define WDT_RR0        REG(0x40010600u)

static inline void wdg_feed(void)
{
    WDT_RR0 = 0x6E524635u;
}

static inline void wdg_stretch(void)
{
    wdg_feed();
}

/* ---- the core ------------------------------------------------------------ */
#define SCB_VTOR       REG(0xE000ED08u)

/* ---- flash --------------------------------------------------------------- */
#define NVMC_READY     REG(0x4001E400u)
#define NVMC_CONFIG    REG(0x4001E504u)
#define NVMC_ERASEPAGE REG(0x4001E508u)
#define CONFIG_REN     0u
#define CONFIG_WEN     1u
#define CONFIG_EEN     2u

typedef uint32_t cell_t;              /* what one program writes */

static inline void flash_wait(void)
{
    while (!(NVMC_READY & 1u))
        ;
}

/* No keys on this chip: CONFIG is set around each operation instead. */
static inline void flash_unlock(void)
{
}

static inline void flash_lock(void)
{
    NVMC_CONFIG = CONFIG_REN;
}

/* Erase every page that has a byte in `addr` .. `addr + size`. */
static inline void flash_erase(uint32_t addr, uint32_t size)
{
    NVMC_CONFIG = CONFIG_EEN;
    for (uint32_t p = addr & ~(PAGE_SIZE - 1u); p < addr + size; p += PAGE_SIZE) {
        wdg_feed();
        NVMC_ERASEPAGE = p;
        flash_wait();
    }
    NVMC_CONFIG = CONFIG_REN;
}

/* Like the F4, a program here can only clear bits, and nothing says so when the
 * cell was not erased. Unlike either STM32, a third write to the same word is out
 * of spec. */
static inline void flash_cell(uint32_t addr, cell_t v)
{
    NVMC_CONFIG = CONFIG_WEN;
    *(volatile cell_t *)addr = v;
    flash_wait();
    NVMC_CONFIG = CONFIG_REN;
}

/* Wen on or off, for code that writes many cells in one go. */
static inline void flash_pg(int on)
{
    NVMC_CONFIG = on ? CONFIG_WEN : CONFIG_REN;
}

static inline void flash_word(uint32_t addr, uint32_t v)
{
    flash_cell(addr, v);
}

#endif
