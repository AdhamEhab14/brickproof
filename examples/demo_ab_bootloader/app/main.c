/* BrickProof demo app: says which version it is, over and over. That banner is
 * how a test (or a person on a serial terminal) knows which image booted. */
#include "demo.h"

#ifndef APP_VERSION
#define APP_VERSION 1
#endif

int main(void)
{
    uart_init();
    for (;;) {
        uart_puts("APP v");
        uart_putc('0' + APP_VERSION);
        uart_puts("\r\n");
        for (volatile uint32_t i = 0; i < 200000u; i++)
            ;
    }
}
