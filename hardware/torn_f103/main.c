/* What an STM32F103 leaves in flash when a page erase or a halfword program is cut short.
 *
 * The firmware starts an erase (or a program) and resets the chip a chosen number of CPU
 * cycles later, then reads back what the flash holds and prints it. It sweeps the delay from
 * nothing to a little past the time the operation really takes, one reset per step, and
 * keeps its place in RAM that start-up does not clear. The code that starts the operation
 * and resets runs from RAM, so the CPU keeps counting while the flash is busy.
 *
 * Output: USART2 on PA2 (the Nucleo's ST-LINK virtual COM port), 115200 8N1. The chip runs
 * on its reset clock, the 8 MHz HSI, so one cycle is 125 ns.
 *
 * Lines:
 *   CAL erase_cycles=N program_cycles=N
 *   E <step> <delay> <bytes FF> <bits 1> <map>     map: one char per 16 bytes of the page,
 *                                                  '#' all 0xFF, '.' all 0x00, 'x' mixed
 *   P <step> <delay> <value> <value read again>
 *   DONE
 *
 * A reset is not a power loss: it stops the operation cleanly, where a power loss lets the
 * supply sag. This measures the first; a switch on the supply is needed for the second.
 */
#include <stdint.h>

#define REG(a)          (*(volatile uint32_t *)(a))
#define RCC_APB2ENR     REG(0x40021018u)
#define RCC_APB1ENR     REG(0x4002101Cu)
#define RCC_CSR         REG(0x40021024u)
#define CSR_RMVF        (1u << 24)
#define CSR_ANY_RESET   (0x3Fu << 26)
#define CSR_SFTRSTF     (1u << 28)
#define GPIOA_CRL       REG(0x40010800u)
#define USART2_SR       REG(0x40004400u)
#define USART2_DR       REG(0x40004404u)
#define USART2_BRR      REG(0x40004408u)
#define USART2_CR1      REG(0x4000440Cu)
#define FLASH_KEYR      REG(0x40022004u)
#define FLASH_SR        REG(0x4002200Cu)
#define FLASH_CR        REG(0x40022010u)
#define FLASH_AR        REG(0x40022014u)
#define CR_PG           (1u << 0)
#define CR_PER          (1u << 1)
#define CR_STRT         (1u << 6)
#define SR_BSY          (1u << 0)
#define DEMCR           REG(0xE000EDFCu)
#define DWT_CTRL        REG(0xE0001000u)
#define DWT_CYCCNT      REG(0xE0001004u)
#define SCB_AIRCR       REG(0xE000ED0Cu)

#define RAMFUNC __attribute__((section(".ramfunc"), noinline, long_call))

#define ERASE_PAGE      0x0801F000u     /* the page that is erased and cut */
#define PROG_PAGE       0x0801F800u     /* the page that holds the cut program */
#define PROG_ADDR       (PROG_PAGE + 0x100u)
#define PAGE_SIZE       0x400u
/* v2: the first half millisecond of an erase in 40-cycle (5 us) steps, the first 2 us of a
 * program in single cycles, each delay tried REPEATS times */
#define ERASE_STEPS     100
#define ERASE_STEP      40u
#define PROG_STEPS      24
#define PROG_STEP       1u
#define REPEATS         3
#define MAGIC           0x544F524Eu

struct state {
    uint32_t magic, phase, step, pending, erase_cycles, program_cycles, check, rep;
};
__attribute__((section(".noinit"))) static struct state st;

static uint32_t checksum(void)
{
    return MAGIC ^ st.phase ^ (st.step << 8) ^ (st.pending << 16) ^ st.erase_cycles
           ^ (st.program_cycles << 3) ^ (st.rep << 24);
}

static void save(void)
{
    st.magic = MAGIC;
    st.check = checksum();
}

static int valid(void)
{
    return st.magic == MAGIC && st.check == checksum();
}

/* ---- uart ---------------------------------------------------------------- */

static void uart_init(void)
{
    RCC_APB2ENR |= (1u << 2);
    RCC_APB1ENR |= (1u << 17);
    GPIOA_CRL = (GPIOA_CRL & ~(0xFu << 8)) | (0xBu << 8);
    USART2_BRR = 0x45u;                 /* 115200 from 8 MHz */
    USART2_CR1 = (1u << 13) | (1u << 3);
}

static void putc_(char c)
{
    while (!(USART2_SR & (1u << 7)))
        ;
    USART2_DR = (uint8_t)c;
}

static void puts_(const char *s)
{
    while (*s)
        putc_(*s++);
}

static void putu(uint32_t v)
{
    char buf[11];
    int i = 10;
    buf[i] = 0;
    do {
        buf[--i] = (char)('0' + v % 10);
        v /= 10;
    } while (v);
    puts_(buf + i);
}

static void puthex(uint32_t v, int digits)
{
    puts_("0x");
    while (digits--)
        putc_("0123456789ABCDEF"[(v >> (4 * digits)) & 0xF]);
}

static void flush(void)
{
    while (!(USART2_SR & (1u << 6)))    /* TC: the last byte has left */
        ;
}

/* ---- flash, from RAM ------------------------------------------------------ */

RAMFUNC static uint32_t time_erase(uint32_t page)
{
    FLASH_CR |= CR_PER;
    FLASH_AR = page;
    uint32_t t0 = DWT_CYCCNT;
    FLASH_CR |= CR_STRT;
    while (FLASH_SR & SR_BSY)
        ;
    uint32_t t = DWT_CYCCNT - t0;
    FLASH_CR &= ~CR_PER;
    return t;
}

RAMFUNC static uint32_t time_program(uint32_t addr, uint16_t v)
{
    FLASH_CR |= CR_PG;
    uint32_t t0 = DWT_CYCCNT;
    *(volatile uint16_t *)addr = v;
    while (FLASH_SR & SR_BSY)
        ;
    uint32_t t = DWT_CYCCNT - t0;
    FLASH_CR &= ~CR_PG;
    return t;
}

RAMFUNC static void cut_erase(uint32_t page, uint32_t delay)
{
    FLASH_CR |= CR_PER;
    FLASH_AR = page;
    uint32_t t0 = DWT_CYCCNT;
    FLASH_CR |= CR_STRT;
    /* the loop takes several cycles a turn, so the count bound never ends it first on the
     * chip; it only keeps a counter that does not run (an emulator) from waiting forever */
    for (uint32_t n = 0; DWT_CYCCNT - t0 < delay && n < delay; n++)
        ;
    SCB_AIRCR = 0x05FA0004u;
    for (;;)
        ;
}

RAMFUNC static void cut_program(uint32_t addr, uint16_t v, uint32_t delay)
{
    FLASH_CR |= CR_PG;
    uint32_t t0 = DWT_CYCCNT;
    *(volatile uint16_t *)addr = v;
    /* the loop takes several cycles a turn, so the count bound never ends it first on the
     * chip; it only keeps a counter that does not run (an emulator) from waiting forever */
    for (uint32_t n = 0; DWT_CYCCNT - t0 < delay && n < delay; n++)
        ;
    SCB_AIRCR = 0x05FA0004u;
    for (;;)
        ;
}

/* ---- the sweep -------------------------------------------------------------- */

static void fill_zero(uint32_t page)
{
    for (uint32_t a = page; a < page + PAGE_SIZE; a += 2)
        time_program(a, 0x0000);
}

static void report_erase(void)
{
    const volatile uint8_t *p = (const volatile uint8_t *)ERASE_PAGE;
    uint32_t ff = 0, ones = 0;
    for (uint32_t i = 0; i < PAGE_SIZE; i++) {
        uint8_t b = p[i];
        ff += b == 0xFF;
        ones += (uint32_t)__builtin_popcount(b);
    }
    puts_(" ");
    putu(ff);
    puts_(" ");
    putu(ones);
    puts_(" ");
    for (uint32_t c = 0; c < PAGE_SIZE; c += 16) {
        uint32_t f = 0, z = 0;
        for (uint32_t i = c; i < c + 16; i++) {
            f += p[i] == 0xFF;
            z += p[i] == 0x00;
        }
        putc_(f == 16 ? '#' : z == 16 ? '.' : 'x');
    }
    if (ff != PAGE_SIZE) {
        volatile uint32_t hist[9];
        for (int k = 0; k <= 8; k++)
            hist[k] = 0;
        for (uint32_t i = 0; i < PAGE_SIZE; i++)
            hist[__builtin_popcount(p[i])]++;
        puts_(" H");
        for (int k = 0; k <= 8; k++) {
            puts_(k ? "," : " ");
            putu(hist[k]);
        }
        puts_(" B ");
        for (uint32_t i = 0; i < 32; i++)
            puthex(p[i], 2);
    }
}

static void report_program(void)
{
    puts_(" ");
    puthex(*(volatile uint16_t *)PROG_ADDR, 4);
    puts_(" ");
    puthex(*(volatile uint16_t *)PROG_ADDR, 4);
}

static uint32_t delay_for(void)
{
    if (st.phase == 0)
        return st.step * ERASE_STEP;
    return st.step * PROG_STEP;
}

int main(void)
{
    uart_init();
    DEMCR |= (1u << 24);
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1u;
    FLASH_KEYR = 0x45670123u;
    FLASH_KEYR = 0xCDEF89ABu;

    uint32_t csr = RCC_CSR;
    RCC_CSR |= CSR_RMVF;
    /* a real chip always says why it reset; an emulator may not, and then the state decides */
    int soft = (csr & CSR_SFTRSTF) || !(csr & CSR_ANY_RESET);

    if (valid() && st.pending && soft) {
        puts_(st.phase == 0 ? "E " : "P ");
        putu(st.step);
        puts_(" ");
        putu(delay_for());
        puts_(" r");
        putu(st.rep);
        if (st.phase == 0)
            report_erase();
        else
            report_program();
        puts_("\r\n");
        st.pending = 0;
        if (++st.rep >= REPEATS) {
            st.rep = 0;
            st.step++;
        }
        if (st.phase == 0 && st.step > ERASE_STEPS) {
            st.phase = 1;
            st.step = 0;
        } else if (st.phase == 1 && st.step > PROG_STEPS) {
            st.phase = 2;
        }
        save();
    } else if (!valid() || !soft) {
        puts_("\r\nTORN v2 STM32F103 page erase and halfword program, cut by a reset\r\n");
        fill_zero(ERASE_PAGE);
        st.erase_cycles = time_erase(ERASE_PAGE);
        time_erase(PROG_PAGE);
        st.program_cycles = time_program(PROG_ADDR, 0x0000);
        st.phase = 0;
        st.step = 0;
        st.rep = 0;
        st.pending = 0;
        save();
        puts_("CAL erase_cycles=");
        putu(st.erase_cycles);
        puts_(" program_cycles=");
        putu(st.program_cycles);
        puts_("\r\n");
    }

    if (st.phase == 2) {
        puts_("DONE\r\n");
        for (;;)
            ;
    }

    if (st.phase == 0) {
        time_erase(ERASE_PAGE);
        fill_zero(ERASE_PAGE);
    } else {
        time_erase(PROG_PAGE);
    }
    uint32_t delay = delay_for();
    st.pending = 1;
    save();
    flush();
    if (st.phase == 0)
        cut_erase(ERASE_PAGE, delay);
    else
        cut_program(PROG_ADDR, 0x0000, delay);
    return 0;
}

/* ---- start-up --------------------------------------------------------------- */

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    for (uint32_t *dst = &_sdata; dst < &_edata; )
        *dst++ = *src++;
    for (uint32_t *dst = &_sbss; dst < &_ebss; )
        *dst++ = 0;
    main();
    for (;;)
        ;
}

void Default_Handler(void)
{
    puts_("FAULT\r\n");
    for (;;)
        ;
}

__attribute__((section(".isr_vector"), used))
void (*const vectors[16])(void) = {
    (void (*)(void))&_estack, Reset_Handler,
    Default_Handler, Default_Handler, Default_Handler, Default_Handler, Default_Handler,
    0, 0, 0, 0,
    Default_Handler, Default_Handler, 0, Default_Handler, Default_Handler,
};
