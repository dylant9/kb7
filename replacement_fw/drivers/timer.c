#include "kb7/drivers.h"
#include "kb7/regs.h"

void kb7_delay_cycles(volatile uint32_t cycles) {
    while (cycles-- != 0U) {
        __asm__ volatile("nop" ::: "memory");
    }
}

void kb7_backlight_init(void) {
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
}

void kb7_backlight_set(uint16_t duty) {
    if (duty > 1023U) {
        duty = 1023U;
    }
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COMPARE1) = duty;
}
