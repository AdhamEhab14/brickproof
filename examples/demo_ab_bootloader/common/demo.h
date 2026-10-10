/* Shared by the demo bootloader and the demo app: the flash map, the image
 * header, and the few STM32F103 registers both of them touch. */
#ifndef DEMO_H
#define DEMO_H

#include <stdint.h>

/* ---- flash map (STM32F103RB, 128 KB in 1 KB pages) ---------------------- */
#define PAGE_SIZE      0x400u
#define BL_BASE        0x08000000u   /*  8 KB bootloader                     */
#define SLOT_A         0x08002000u   /* 56 KB the image that runs            */
#define SLOT_B         0x08010000u   /* 56 KB staging: a new image waits here */
#define SLOT_SIZE      0xE000u
#define META_0         0x0801E000u   /* rollback floor, two pages so one is  */
#define META_1         0x0801E400u   /* always intact while the other is rewritten */

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

/* ---- registers ----------------------------------------------------------- */
#define REG(a)         (*(volatile uint32_t *)(a))

#define RCC_APB2ENR    REG(0x40021018u)
#define RCC_APB1ENR    REG(0x4002101Cu)
#define GPIOA_CRL      REG(0x40010800u)
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
