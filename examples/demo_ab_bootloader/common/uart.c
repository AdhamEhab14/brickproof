/* USART2 on PA2 (the Nucleo's ST-LINK virtual COM port), 115200 8N1, polled.
 * Nothing touches the clocks, so the bus runs at the chip's reset HSI. On the
 * nRF52840 it is UARTE0, whose details are in chip_nrf52.h. */
#include "demo.h"

#ifdef NRF52

static char tx[64];                   /* EasyDMA sends from RAM only */

void uart_init(void)
{
    uart_hw_init();
}

void uart_putc(char c)
{
    tx[0] = c;
    uart_hw_send(tx, 1);
}

/* A line at a time, so the app's banner is one transfer, not one per character. */
void uart_puts(const char *s)
{
    uint32_t n = 0;
    while (*s) {
        tx[n++] = *s++;
        if (n == sizeof tx) {
            uart_hw_send(tx, n);
            n = 0;
        }
    }
    if (n)
        uart_hw_send(tx, n);
}

#else

void uart_init(void)
{
    uart_pins();
    USART2_BRR = UART_BRR_115200;
    USART2_CR1 = (1u << 13) | (1u << 3);              /* UE, TE */
}

void uart_putc(char c)
{
    while (!(USART2_SR & (1u << 7)))                  /* TXE */
        ;
    USART2_DR = (uint8_t)c;
}

void uart_puts(const char *s)
{
    while (*s)
        uart_putc(*s++);
}

#endif
