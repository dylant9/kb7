#include "kb7/drivers.h"
#include "kb7/platform_boot.h"
#include "kb7/regs.h"

typedef uint32_t (*rom_clock_fn_t)(uint32_t control, volatile uint32_t *instance);
#define KB7_ROM_CLOCK_TRANSITION ((rom_clock_fn_t)(uintptr_t)UINT32_C(0x0800603d))
#define KB7_CLOCK_WAIT_LIMIT UINT32_C(1000000)

static uint32_t system_clock_hz = KB7_IHRC_CLOCK_HZ;
static uint32_t peripheral_clock_hz = KB7_IHRC_CLOCK_HZ;

#if defined(KB7_HOST_TEST)
static bool clock_delay_us(uint32_t microseconds) {
    (void)microseconds;
    return true;
}
#else
#define clock_delay_us kb7_delay_us
#endif

uint32_t kb7_bitfield_insert(uint32_t value, uint8_t high, uint8_t low,
                             uint32_t field) {
    if (high > 31U || low > high) {
        return value;
    }
    const uint8_t width = (uint8_t)(high - low + 1U);
    const uint32_t unshifted_mask = width == 32U
                                        ? UINT32_MAX
                                        : ((UINT32_C(1) << width) - 1U);
    const uint32_t mask = unshifted_mask << low;
    return (value & ~mask) | ((field & unshifted_mask) << low);
}

uint32_t kb7_clock_hz_for_state(uint32_t state, uint32_t divider_shift,
                                uint32_t pll_hz) {
    uint32_t source_hz;
    switch (state & 7U) {
    case 1U:
    case 2U:
        source_hz = KB7_IHRC_CLOCK_HZ;
        break;
    case 3U:
        source_hz = KB7_ILRC_CLOCK_HZ;
        break;
    case 4U:
        source_hz = pll_hz / 2U;
        break;
    default:
        return 0U;
    }
    return divider_shift < 32U ? source_hz >> divider_shift : 0U;
}

uint32_t kb7_system_clock_hz(void) { return system_clock_hz; }

uint32_t kb7_peripheral_clock_hz(void) { return peripheral_clock_hz; }

uint32_t kb7_systick_reload(uint32_t clock_hz) {
    return clock_hz >= 1000U ? (clock_hz / 1000U) - 1U : 0U;
}

static bool wait_mask(uint32_t address, uint32_t mask, uint32_t expected) {
    uint32_t remaining = KB7_CLOCK_WAIT_LIMIT;
    while ((KB7_MMIO32(address) & mask) != expected) {
        if (remaining == 0U) {
            return false;
        }
        --remaining;
    }
    return true;
}

static bool switch_system_clock(uint32_t state, uint32_t divider_shift) {
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_CLOCK_SELECT) = state & 7U;
    uint32_t remaining = 100U;
    while (((KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_CLOCK_SELECT) >> 4U) & 7U) !=
           (state & 7U)) {
        if (remaining == 0U || !clock_delay_us(1000U)) {
            return false;
        }
        --remaining;
    }
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_CLOCK_DIVIDER) = divider_shift;
    kb7_dsb();
    kb7_isb();
    return true;
}

static bool configure_stock_pll(void) {
    const uint32_t select = KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_CLOCK_SELECT);
    const uint32_t active_state = (select >> 4U) & 7U;
    if (active_state == 4U) {
        const uint32_t fallback =
            (KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_OSC_CONTROL) & KB7_BIT(14)) != 0U
                ? 2U
                : 0U;
        if (!switch_system_clock(fallback, 0U)) {
            return false;
        }
    }

    /* 198 MHz / 6 MHz = 33, with no fractional component. */
    uint32_t pll = KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PLL_CONTROL);
    pll &= ~(UINT32_C(0xffff0000) | UINT32_C(0x3f0) | UINT32_C(0x0f));
    pll |= (UINT32_C(33) << 4U) | KB7_BIT(10);
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PLL_CONTROL) = pll;

    if (!clock_delay_us(1U)) {
        return false;
    }
    uint32_t oscillator = KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_OSC_CONTROL);
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_OSC_CONTROL) = oscillator | KB7_BIT(1);
    if (!clock_delay_us(1U) || !clock_delay_us(1U)) {
        return false;
    }
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_OSC_CONTROL) = oscillator & ~KB7_BIT(1);
    return switch_system_clock(4U, 0U);
}

uint32_t kb7_clock_control_for_state(uint32_t control, uint32_t clock_state) {
    if (clock_state != 4U) {
        control = (control & ~UINT32_C(0x3000)) | UINT32_C(0x1000);
    } else {
        /* Choose the first power-of-two divider which does not exceed 40 MHz. */
        uint32_t divider = 1U;
        while (divider < 3U &&
               (KB7_PLL_CLOCK_HZ >> divider) > UINT32_C(40000000)) {
            ++divider;
        }
        control = (control & ~UINT32_C(0x3000)) | ((divider & 3U) << 12U);
    }
    return control | UINT32_C(0x8000);
}

bool kb7_clock_rom_result_ok(uint32_t result) {
    /* Both sentinels enter fatal case 6 in the two reference versions. */
    return result != 0U && result != UINT32_C(0x00ffffff);
}

bool kb7_clock_init(void) {
    uint32_t peripheral_divider =
        KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PERIPHERAL_DIVIDER);
    peripheral_divider &= ~(KB7_BIT(0) | KB7_BIT(1));
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PERIPHERAL_DIVIDER) = peripheral_divider;

    uint32_t oscillator = KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_OSC_CONTROL);
    oscillator |= KB7_BIT(4) | KB7_BIT(14);
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_OSC_CONTROL) = oscillator;
    if (!wait_mask(SNC_SYS0_BASE + SNC_SYS0_OSC_STATUS, KB7_BIT(4), KB7_BIT(4))) {
        return false;
    }
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_OSC_CONTROL) = oscillator | KB7_BIT(15);
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_CLOCK_ENABLE) &= ~KB7_BIT(10);

    if ((KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_CLOCK_SELECT) & 7U) != 4U &&
        !switch_system_clock(4U, 0U)) {
        return false;
    }
    if (!configure_stock_pll()) {
        return false;
    }

    /* These are the stock post-PLL SYS1 gate/reset masks. */
    KB7_MMIO32(SNC_SYS1_BASE + SNC_SYS1_CLOCK_RESET) = UINT32_C(0x0000fffd);
    KB7_MMIO32(SNC_SYS1_BASE + SNC_SYS1_PERIPHERAL_CLOCK_ENABLE) =
        UINT32_C(0x00009fff);
    system_clock_hz = KB7_CORE_CLOCK_HZ;
    peripheral_clock_hz = KB7_PLL_CLOCK_HZ;

    volatile uint32_t *const instance =
        (volatile uint32_t *)(uintptr_t)SNC_SPI_NOR_BASE;
    const uint32_t clock_state =
        KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_CLOCK_SELECT) & 7U;
    const uint32_t control = kb7_clock_control_for_state(*instance, clock_state);
    *instance = control;
    const uint32_t result = KB7_ROM_CLOCK_TRANSITION(control, instance);
    kb7_dsb();
    kb7_isb();
    return kb7_clock_rom_result_ok(result);
}
