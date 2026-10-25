/* Shared by the demo bootloader and the demo app: the image header, the chip
 * (flash map, flash primitives, UART pins) and the registers the STM32s share. */
#ifndef DEMO_H
#define DEMO_H

#include <stdint.h>

#define REG(a)         (*(volatile uint32_t *)(a))

static inline void wdg_feed(void);

#if defined(NRF52)
#include "chip_nrf52.h"
#elif defined(STM32F4)
#include "chip_f411.h"
#elif defined(STM32L4)
#include "chip_l476.h"
#elif defined(STM32H5)
#include "chip_h563.h"
#else
#include "chip_f103.h"
#endif

#define CELL           ((uint32_t)sizeof(cell_t))

#ifndef STM32L4
/* Only the L4's flash has ECC (chip_l476.h); elsewhere no read is ever flagged. */
static inline void ecc_clear(void) {}
static inline int ecc_seen(void) { return 0; }
#endif

/* An image is a 16-byte header at the slot start, then the app itself at
 * +0x200 (the vector table needs that alignment). */
#define IMG_MAGIC      0x494D4250u   /* "BPMI" */
#define IMG_OFFSET     0x200u

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t size;       /* bytes of app after the header area */
    uint32_t crc;        /* CRC-32 of those bytes */
} img_hdr_t;

#ifndef NRF52
/* ---- registers the STM32s have in the same place --------------------------- */
#ifndef UART_SR                       /* USART2 on the F1 and the F4; the L4 and the H563
                                       * name theirs in chip_l476.h and chip_h563.h */
#define UART_SR        REG(0x40004400u)
#define UART_DR        REG(0x40004404u)
#define UART_BRR       REG(0x40004408u)
#define UART_CR1       REG(0x4000440Cu)
#define UART_CR1_ON    ((1u << 13) | (1u << 3))  /* UE, TE */
#endif
#define SCB_VTOR       REG(0xE000ED08u)

/* ---- independent watchdog (in the same place on every STM32 here) ------------ */
#define IWDG_KR        REG(0x40003000u)
#define IWDG_PR        REG(0x40003004u)
#define IWDG_SR        REG(0x4000300Cu)

/* On a device whose option bytes make the watchdog a hardware one, it runs from
 * reset and resets the chip unless this is called in time. Harmless otherwise. */
static inline void wdg_feed(void)
{
    IWDG_KR = 0xAAAAu;
}

/* Give the watchdog its longest timeout, about half a minute. The chip stands still
 * while it erases, and a big sector takes longer than the watchdog waits after reset. */
static inline void wdg_stretch(void)
{
    IWDG_KR = 0x5555u;                /* allow writing the prescaler */
    IWDG_PR = 6u;                     /* divide by 256 */
    while (IWDG_SR & 1u)              /* until it has taken the new value */
        ;
    IWDG_KR = 0xAAAAu;
}
#endif

/* ---- uart.c -------------------------------------------------------------- */
void uart_init(void);
void uart_puts(const char *s);
void uart_putc(char c);

#endif
