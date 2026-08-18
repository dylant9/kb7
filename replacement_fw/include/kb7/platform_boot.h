#ifndef KB7_PLATFORM_BOOT_H
#define KB7_PLATFORM_BOOT_H

#include "kb7/platform.h"

#define KB7_PLL_CLOCK_HZ UINT32_C(198000000)
#define KB7_CORE_CLOCK_HZ (KB7_PLL_CLOCK_HZ / 2U)
#define KB7_IHRC_CLOCK_HZ UINT32_C(12000000)
#define KB7_ILRC_CLOCK_HZ UINT32_C(32767)

uint32_t kb7_bitfield_insert(uint32_t value, uint8_t high, uint8_t low,
                             uint32_t field);
uint32_t kb7_clock_hz_for_state(uint32_t state, uint32_t divider_shift,
                                uint32_t pll_hz);
uint32_t kb7_system_clock_hz(void);
uint32_t kb7_peripheral_clock_hz(void);
uint32_t kb7_systick_reload(uint32_t clock_hz);

bool kb7_gpio_pinmux_known(uint8_t logical, uint8_t function);
uint32_t kb7_pwm_compare(uint32_t period, uint16_t resolution, uint16_t duty);

bool kb7_cache_prepare_region1(void);
bool kb7_flash_range_mutable(uint32_t offset, uint32_t length);
bool kb7_flash_sync_xip(uint32_t offset, uint32_t length);

#define KB7_FAULT_MAGIC UINT32_C(0x4b423746)
#define KB7_FAULT_VERSION 1U

struct kb7_fault_record {
    uint32_t magic;
    uint32_t version;
    uint32_t cause;
    uint32_t stacked_r0;
    uint32_t stacked_r1;
    uint32_t stacked_r2;
    uint32_t stacked_r3;
    uint32_t stacked_r12;
    uint32_t stacked_lr;
    uint32_t stacked_pc;
    uint32_t stacked_xpsr;
    uint32_t cfsr;
    uint32_t hfsr;
    uint32_t dfsr;
    uint32_t afsr;
    uint32_t mmfar;
    uint32_t bfar;
    uint32_t icsr;
    uint32_t shcsr;
};

void kb7_fault_capture(uint32_t cause, const uint32_t *stack) KB7_NORETURN;

#endif
