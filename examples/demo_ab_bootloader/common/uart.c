/* USART2 on PA2 (the Nucleo's ST-LINK virtual COM port), 115200 8N1, polled.
 * Nothing touches the clocks, so the bus runs at the chip's reset HSI. */
#include "demo.h"

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
