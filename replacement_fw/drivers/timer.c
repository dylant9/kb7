#include "kb7/drivers.h"
#include "kb7/config.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"

void kb7_delay_cycles(volatile uint32_t cycles) {
    while (cycles-- != 0U) {
        __asm__ volatile("nop" ::: "memory");
    }
}

bool kb7_delay_ms(uint32_t milliseconds) {
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (api->magic != KB7_RUNTIME_MAGIC || api->milliseconds == NULL) {
        return false;
    }
    const uint32_t start = api->milliseconds();
    while ((uint32_t)(api->milliseconds() - start) < milliseconds) {
        /* A wrapping 32-bit millisecond counter remains valid for short waits. */
    }
    return true;
}

void kb7_backlight_init(void) {
#if KB7_ENABLE_DISPLAY
    KB7_MMIO32(SNC_CLOCK_BASE + 0x20U) |= KB7_BIT(17);
    kb7_gpio_configure(6U, KB7_GPIO_OUTPUT, 1U, KB7_GPIO_FLOATING);
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_CONTROL) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PRESCALER) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COUNTER) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PERIOD) = 1023U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COMPARE1) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_IRQ) = UINT32_C(0xffffffff);
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PWM_ENABLE) = KB7_BIT(1);
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_CONTROL) = 1U;
    kb7_dsb();
#endif
}

void kb7_backlight_set(uint16_t duty) {
#if KB7_ENABLE_DISPLAY
    if (duty > 1023U) {
        duty = 1023U;
    }
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COMPARE1) = duty;
#else
    (void)duty;
#endif
}
