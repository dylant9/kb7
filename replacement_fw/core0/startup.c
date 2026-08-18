#include "kb7/platform.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"
#include "kb7/drivers.h"
#include "kb7/platform_boot.h"

extern uint32_t __data_load_start__, __data_start__, __data_end__;
extern uint32_t __bss_start__, __bss_end__;
void core0_main(void) KB7_NORETURN;
void kb7_usb_irq_handler(void);

static void default_handler(void) {
    uint32_t exception;
    __asm__ volatile("mrs %0, ipsr" : "=r"(exception));
    kb7_shared()->last_error = UINT32_C(0xdeadc000) | (exception & UINT32_C(0xff));
    kb7_fault_capture(exception, NULL);
}

void hardfault_handler(void) __attribute__((naked));
void hardfault_handler(void) {
    __asm__ volatile(
        "tst lr, #4\n"
        "ite eq\n"
        "mrseq r1, msp\n"
        "mrsne r1, psp\n"
        "movs r0, #3\n"
        "b kb7_fault_capture\n");
}

void systick_handler(void) {
    ++kb7_shared()->milliseconds;
}

void reset_handler(void) {
    uint32_t *source = &__data_load_start__;
    for (uint32_t *destination = &__data_start__; destination < &__data_end__;) {
        *destination++ = *source++;
    }
    for (uint32_t *destination = &__bss_start__; destination < &__bss_end__;) {
        *destination++ = 0U;
    }
    /* Stock feeds the active watchdog, then disables both instances. */
    const uint32_t active_wdt =
        KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_OSC_CONTROL) == 0U &&
                KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_CLOCK_SELECT) == 0U
            ? SNC_WDT0_BASE
            : SNC_WDT1_BASE;
    KB7_MMIO32(active_wdt + SNC_WDT_FEED) = UINT32_C(0x5afa55aa);
    KB7_MMIO32(SNC_WDT1_BASE + SNC_WDT_CONFIGURATION) = UINT32_C(0x5afa0000);
    KB7_MMIO32(SNC_WDT0_BASE + SNC_WDT_CONFIGURATION) = UINT32_C(0x5afa0000);
    core0_main();
}

typedef void (*handler_t)(void);
__attribute__((section(".isr_vector"), used))
const handler_t vectors[79] = {
    [0] = (handler_t)(uintptr_t)KB7_CORE0_STACK_TOP,
    [1] = reset_handler,
    [2] = default_handler,
    [3] = hardfault_handler,
    [4 ... 14] = default_handler,
    [15] = systick_handler,
    [16 ... 21] = default_handler,
    [22] = kb7_usb_irq_handler, /* recovered USB device IRQ6 */
    [23 ... 78] = default_handler,
};
