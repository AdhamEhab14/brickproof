/* Minimal Cortex-M3 start-up: core vectors only, copy .data, clear .bss, main(). */
#include <stdint.h>

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;
int main(void);

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

/* A fault means the image is broken. Hang without printing anything, so the
 * test sees what a user would: a device that never says hello. */
void Default_Handler(void)
{
    for (;;)
        ;
}

/* The bootloader may handle the NMI itself (on the L4 it reports ECC errors). */
void NMI_Handler(void) __attribute__((weak, alias("Default_Handler")));

__attribute__((section(".isr_vector"), used))
void (*const vectors[16])(void) = {
    (void (*)(void))&_estack,
    Reset_Handler,
    NMI_Handler,
    Default_Handler,     /* HardFault */
    Default_Handler,     /* MemManage */
    Default_Handler,     /* BusFault */
    Default_Handler,     /* UsageFault */
    0, 0, 0, 0,
    Default_Handler,     /* SVC */
    Default_Handler,     /* DebugMon */
    0,
    Default_Handler,     /* PendSV */
    Default_Handler,     /* SysTick */
};
