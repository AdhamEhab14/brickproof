/* The console UART, 115200 8N1, polled: USART2 on PA2 on the F1 and the F4 (the
 * Nucleo's ST-LINK virtual COM port), USART3 on PD8 on the H563 (the Nucleo-H563ZI's).
 * Nothing touches the clocks, so the bus runs at the chip's reset HSI. */
#include "demo.h"

void uart_init(void)
{
    uart_pins();
    UART_BRR = UART_BRR_115200;
    UART_CR1 = UART_CR1_ON;
}

void uart_putc(char c)
{
    while (!(UART_SR & (1u << 7)))                    /* TXE */
        ;
    UART_DR = (uint8_t)c;
}

void uart_puts(const char *s)
{
    while (*s)
        uart_putc(*s++);
}
