/* USART2 on PA2 (the Nucleo's ST-LINK virtual COM port), 115200 8N1, polled.
 * Nothing touches the clocks, so the bus runs at the reset 8 MHz HSI. */
#include "demo.h"

void uart_init(void)
{
    RCC_APB2ENR |= (1u << 2);                         /* GPIOA */
    RCC_APB1ENR |= (1u << 17);                        /* USART2 */
    GPIOA_CRL = (GPIOA_CRL & ~(0xFu << 8)) | (0xBu << 8);   /* PA2: AF push-pull */
    USART2_BRR = 0x45;                                /* 8 MHz / 115200 */
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
