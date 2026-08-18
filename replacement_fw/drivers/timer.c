#include "kb7/drivers.h"
#include "kb7/config.h"
#include "kb7/platform_boot.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"

#define KB7_BACKLIGHT_RESOLUTION 1023U
#define KB7_BACKLIGHT_PERIOD_US UINT32_C(10000)
#define KB7_DELAY_US_LIMIT UINT32_C(10000000)

/* Region 1 links independently after clocks have already been established. */
__attribute__((weak)) uint32_t kb7_system_clock_hz(void) {
    return KB7_CORE_CLOCK_HZ;
}

__attribute__((weak)) uint32_t kb7_peripheral_clock_hz(void) {
    return KB7_PLL_CLOCK_HZ;
}

void kb7_delay_cycles(volatile uint32_t cycles) {
#ifdef KB7_HOST_TEST
    while (cycles != 0U) {
        --cycles;
        __asm__ volatile("nop" ::: "memory");
    }
#else
    if (cycles != 0U) {
        __asm__ volatile(
            "1: subs %0, %0, #1\n"
            "bne 1b\n"
            : "+r"(cycles)
            :
            : "cc", "memory");
    }
#endif
}

bool kb7_delay_us(uint32_t microseconds) {
    if (microseconds == 0U) {
        return true;
    }
    const uint32_t hz = kb7_system_clock_hz();
    if (hz == 0U || microseconds > KB7_DELAY_US_LIMIT) {
        return false;
    }
    const uint64_t cycles = (uint64_t)(hz / UINT32_C(1000000)) * microseconds;
    /* Stock compensates 46 cycles of call/setup overhead and four per loop. */
    if (cycles < 46U) {
        return true;
    }
    const uint64_t iterations = (cycles - 46U) / 4U;
    if (iterations > UINT32_MAX) {
        return false;
    }
    kb7_delay_cycles((uint32_t)iterations);
    return true;
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

uint32_t kb7_pwm_compare(uint32_t period, uint16_t resolution, uint16_t duty) {
    if (resolution == 0U) {
        return 0U;
    }
    if (duty > resolution) {
        duty = resolution;
    }
    return (uint32_t)(((uint64_t)(resolution - duty) * period) / resolution);
}

#if KB7_ENABLE_DISPLAY
static bool timer6_reset(void) {
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_CONTROL) |= KB7_BIT(1);
    uint32_t timeout = UINT32_C(100000);
    while ((KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_CONTROL) & KB7_BIT(1)) != 0U) {
        if (timeout == 0U) {
            return false;
        }
        --timeout;
    }
    return true;
}
#endif

void kb7_backlight_init(void) {
#if KB7_ENABLE_DISPLAY
    kb7_gpio_configure(6U, KB7_GPIO_OUTPUT, 7U, KB7_GPIO_FLOATING);
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_CONTROL) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COUNTER) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COMPARE0) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COMPARE1) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COMPARE2) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PERIOD) = 0U;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PRESCALER) = 0U;
    if (!timer6_reset()) {
        return;
    }

    uint32_t prescaler = KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PRESCALER);
    prescaler = (prescaler & ~(UINT32_C(7) << 9U)) | (UINT32_C(2) << 9U);
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PRESCALER) = prescaler;
    const uint32_t period =
        (kb7_peripheral_clock_hz() / UINT32_C(1000000)) * KB7_BACKLIGHT_PERIOD_US;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PERIOD) = period;
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COMPARE1) =
        kb7_pwm_compare(period, KB7_BACKLIGHT_RESOLUTION, 103U);
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_IRQ) = UINT32_C(0xffffffff);
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PWM_ENABLE) =
        KB7_BIT(1) | KB7_BIT(21);
    if (!timer6_reset()) {
        return;
    }
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_CONTROL) = 1U;
    kb7_dsb();
#endif
}

void kb7_backlight_set(uint16_t duty) {
#if KB7_ENABLE_DISPLAY
    if (duty > 1023U) {
        duty = 1023U;
    }
    const uint32_t period = KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_PERIOD);
    KB7_MMIO32(SNC_TIMER6_BASE + SNC_TIMER_COMPARE1) =
        kb7_pwm_compare(period, KB7_BACKLIGHT_RESOLUTION, duty);
#else
    (void)duty;
#endif
}
