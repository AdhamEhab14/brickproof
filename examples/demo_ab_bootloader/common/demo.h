/* Shared by the demo bootloader and the demo app: the image header, the chip
 * (flash map, flash primitives, UART pins) and the registers both chips share. */
#ifndef DEMO_H
#define DEMO_H

#include <stdint.h>

#define REG(a)         (*(volatile uint32_t *)(a))

#ifdef STM32F4
#include "chip_f411.h"
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

/* ---- registers both chips have in the same place -------------------------- */
#define USART2_SR      REG(0x40004400u)
#define USART2_DR      REG(0x40004404u)
#define USART2_BRR     REG(0x40004408u)
#define USART2_CR1     REG(0x4000440Cu)
#define SCB_VTOR       REG(0xE000ED08u)

/* ---- uart.c -------------------------------------------------------------- */
void uart_init(void);
void uart_puts(const char *s);
void uart_putc(char c);

#endif
