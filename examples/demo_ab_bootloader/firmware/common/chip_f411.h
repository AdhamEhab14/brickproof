/* The demo on an STM32F411: 512 KB of flash in eight sectors of 16, 64 and
 * 128 KB, programmed a word at a time. An erase wipes a whole sector, so each
 * part of the map gets sectors of its own. */
#ifndef CHIP_H
#define CHIP_H

/* ---- flash map ----------------------------------------------------------- */
#define BL_BASE        0x08000000u   /* sector 0, 16 KB: bootloader              */
#if !defined(EXT_FLASH) && !defined(EEPROM_FLOOR)
#define META_0         0x08004000u   /* sector 1, 16 KB: rollback floor, in two  */
#define META_1         0x08008000u   /* sector 2, 16 KB: sectors, so one is always intact */
#endif
#define SLOT_A         0x08020000u   /* sector 5, 128 KB: the image that runs    */
#ifndef EXT_FLASH
#define SLOT_B         0x08040000u   /* sector 6, 128 KB: staging                */
#endif
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

#ifdef EXT_FLASH
/* ---- an external SPI NOR flash chip on SPI1, chip select on PA4 -------------
 * With EXT_FLASH the new image waits in this chip, not in an internal sector, and the
 * rollback floor is kept there too. Offsets inside the chip: */
#define EXT_STAGING    0x00000u      /* the staged image                         */
#define META_0         0x10000u      /* rollback floor, in two 4 KB sectors so   */
#define META_1         0x11000u      /* one is always intact                     */
#define STAGED_MAX     0x2000u       /* the largest image the bootloader takes   */

#define RCC_APB2ENR    REG(0x40023844u)
#define GPIOA_BSRR     REG(0x40020018u)
#define SPI1_CR1       REG(0x40013000u)
#define SPI1_SR        REG(0x40013008u)
#define SPI1_DR        REG(0x4001300Cu)

static inline void ext_init(void)
{
    RCC_AHB1ENR |= (1u << 0);                         /* GPIOA */
    RCC_APB2ENR |= (1u << 12);                        /* SPI1 */
    GPIOA_BSRR = (1u << 4);                           /* chip select high: not selected */
    /* PA4 output, PA5 to PA7 alternate function 5 (SCK, MISO, MOSI) */
    GPIOA_MODER = (GPIOA_MODER & ~(0xFFu << 8)) | (0x1u << 8) | (0x2Au << 10);
    GPIOA_AFRL = (GPIOA_AFRL & ~(0xFFFu << 20)) | (0x555u << 20);
    SPI1_CR1 = (1u << 9) | (1u << 8) | (1u << 6) | (1u << 3) | (1u << 2);  /* SSM, SSI, SPE, /4, master */
}

static inline uint8_t ext_byte(uint8_t out)
{
    while (!(SPI1_SR & (1u << 1)))                    /* TXE */
        ;
    SPI1_DR = out;
    while (!(SPI1_SR & (1u << 0)))                    /* RXNE */
        ;
    return (uint8_t)SPI1_DR;
}

static inline void ext_select(uint8_t command, uint32_t addr)
{
    GPIOA_BSRR = (1u << 20);                          /* chip select low */
    ext_byte(command);
    ext_byte((uint8_t)(addr >> 16));
    ext_byte((uint8_t)(addr >> 8));
    ext_byte((uint8_t)addr);
}

static inline void ext_release(void)
{
    GPIOA_BSRR = (1u << 4);
}

static inline void ext_read(uint32_t addr, void *to, uint32_t n)
{
    uint8_t *p = to;
    ext_select(0x03, addr);
    while (n--)
        *p++ = ext_byte(0);
    ext_release();
}

/* Every program and erase needs a write enable first, and the chip is busy for a
 * while afterwards. */
static inline void ext_write_enable(void)
{
    GPIOA_BSRR = (1u << 20);
    ext_byte(0x06);
    ext_release();
}

static inline void ext_wait(void)
{
    uint8_t status;
    do {
        GPIOA_BSRR = (1u << 20);
        ext_byte(0x05);
        status = ext_byte(0);
        ext_release();
        wdg_feed();
    } while (status & 1u);
}

/* At most one 256-byte page, and not across a page boundary. */
static inline void ext_program(uint32_t addr, const void *from, uint32_t n)
{
    const uint8_t *p = from;
    ext_write_enable();
    ext_select(0x02, addr);
    while (n--)
        ext_byte(*p++);
    ext_release();
    ext_wait();
}

static inline void ext_erase_sector(uint32_t addr)
{
    ext_write_enable();
    ext_select(0x20, addr);
    ext_release();
    ext_wait();
}
#endif

#ifdef EEPROM_FLOOR
/* ---- an I2C EEPROM (a 24C256: 32 KB, 64-byte pages) on I2C1, PB8 and PB9 -------
 * With EEPROM_FLOOR the rollback floor is kept in it, a record per page. Offsets: */
#define META_0         0x0000u
#define META_1         0x0040u
#define EE_I2C         0x50u         /* its bus address, with A0 to A2 tied low   */

#define RCC_APB1ENR_I2C1 (1u << 21)
#define GPIOB_MODER    REG(0x40020400u)
#define GPIOB_OTYPER   REG(0x40020404u)
#define GPIOB_AFRH     REG(0x40020424u)
#define I2C1_CR1       REG(0x40005400u)
#define I2C1_CR2       REG(0x40005404u)
#define I2C1_DR        REG(0x40005410u)
#define I2C1_SR1       REG(0x40005414u)
#define I2C1_SR2       REG(0x40005418u)
#define I2C1_CCR       REG(0x4000541Cu)
#define I2C1_TRISE     REG(0x40005420u)
#define CR1_PE         (1u << 0)
#define CR1_START      (1u << 8)
#define CR1_STOP       (1u << 9)
#define CR1_ACK        (1u << 10)
#define SR1_SB         (1u << 0)
#define SR1_ADDR       (1u << 1)
#define SR1_BTF        (1u << 2)
#define SR1_RXNE       (1u << 6)
#define SR1_TXE        (1u << 7)
#define SR1_AF         (1u << 10)

static inline void ee_init(void)
{
    RCC_AHB1ENR |= (1u << 1);                         /* GPIOB */
    RCC_APB1ENR |= RCC_APB1ENR_I2C1;
    /* PB8 and PB9: alternate function 4, open drain */
    GPIOB_MODER = (GPIOB_MODER & ~(0xFu << 16)) | (0xAu << 16);
    GPIOB_OTYPER |= (3u << 8);
    GPIOB_AFRH = (GPIOB_AFRH & ~0xFFu) | 0x44u;
    I2C1_CR2 = 16;                                    /* APB1 at 16 MHz */
    I2C1_CCR = 80;                                    /* 100 kHz */
    I2C1_TRISE = 17;
    I2C1_CR1 = CR1_PE;
}

static inline void ee_until(uint32_t flags)
{
    while (!(I2C1_SR1 & flags))
        ;
}

/* A start condition and the EEPROM's address. 0 if it did not answer, which it does
 * not while a write cycle is still going on. ADDR is left for the caller to clear. */
static inline int ee_start(uint32_t read)
{
    I2C1_CR1 |= CR1_START;
    ee_until(SR1_SB);
    I2C1_DR = (EE_I2C << 1) | read;
    ee_until(SR1_ADDR | SR1_AF);
    if (I2C1_SR1 & SR1_AF) {
        I2C1_SR1 &= ~SR1_AF;
        I2C1_CR1 |= CR1_STOP;
        return 0;
    }
    return 1;
}

static inline void ee_send(uint8_t b)
{
    ee_until(SR1_TXE);
    I2C1_DR = b;
}

static inline void ee_address(uint32_t off)
{
    while (!ee_start(0))
        wdg_feed();                                   /* busy: try again */
    (void)I2C1_SR2;
    ee_send((uint8_t)(off >> 8));
    ee_send((uint8_t)off);
}

static inline void ee_read(uint32_t off, void *to, uint32_t n)
{
    uint8_t *p = to;
    ee_address(off);
    ee_until(SR1_BTF);
    /* a repeated start, now reading. Every byte is acknowledged except the last, which
     * tells the EEPROM to stop sending. */
    if (n > 1)
        I2C1_CR1 |= CR1_ACK;
    else
        I2C1_CR1 &= ~CR1_ACK;
    ee_start(1);
    (void)I2C1_SR2;
    if (n == 1)
        I2C1_CR1 |= CR1_STOP;
    for (uint32_t i = 0; i < n; i++) {
        ee_until(SR1_RXNE);
        p[i] = (uint8_t)I2C1_DR;
        if (i + 2 == n) {
            I2C1_CR1 &= ~CR1_ACK;
            I2C1_CR1 |= CR1_STOP;
        }
    }
}

/* At most one 64-byte page, and not across a page boundary: the chip would wrap. */
static inline void ee_write(uint32_t off, const void *from, uint32_t n)
{
    const uint8_t *p = from;
    ee_address(off);
    while (n--)
        ee_send(*p++);
    ee_until(SR1_BTF);
    I2C1_CR1 |= CR1_STOP;
    /* the write cycle: the chip answers its address again once it is done */
    while (!ee_start(0))
        wdg_feed();
    I2C1_CR1 |= CR1_STOP;
}
#endif

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
