/* Shared by the demo bootloader and the demo app: the image header, the chip
 * (flash map, flash primitives, UART pins) and the registers both chips share. */
#ifndef DEMO_H
#define DEMO_H

#include <stdint.h>

#define REG(a)         (*(volatile uint32_t *)(a))

static inline void wdg_feed(void);

#if defined(STM32F4)
#include "chip_f411.h"
#elif defined(STM32H5)
#include "chip_h563.h"
#else
#include "chip_f103.h"
#endif

#define CELL           ((uint32_t)sizeof(cell_t))

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

/* ---- registers the F1 and the F4 have in the same place -------------------- */
#ifndef UART_SR                       /* USART2; the H563's UART is in chip_h563.h */
#define UART_SR        REG(0x40004400u)
#define UART_DR        REG(0x40004404u)
#define UART_BRR       REG(0x40004408u)
#define UART_CR1       REG(0x4000440Cu)
#define UART_CR1_ON    ((1u << 13) | (1u << 3))  /* UE, TE */
#endif
#define SCB_VTOR       REG(0xE000ED08u)

/* ---- independent watchdog (in the same place on all three chips) ------------- */
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

/* ---- uart.c -------------------------------------------------------------- */
void uart_init(void);
void uart_puts(const char *s);
void uart_putc(char c);

#endif
