#include "kb7/drivers.h"
#include "kb7/regs.h"

uint32_t kb7_gpio_bank(uint8_t logical) {
    if (logical >= 80U) {
        return 0U;
    }
    return SNC_GPIO_A_BASE + ((uint32_t)(logical >> 4U) * UINT32_C(0x1000));
}

uint16_t kb7_gpio_mask(uint8_t logical) {
    return logical < 80U ? (uint16_t)(UINT16_C(1) << (logical & 15U)) : 0U;
}

void kb7_gpio_configure(uint8_t logical, enum kb7_gpio_direction direction,
                        uint8_t function, enum kb7_gpio_pull pull) {
    const uint32_t bank = kb7_gpio_bank(logical);
    const uint32_t bit = logical & 15U;
    if (bank == 0U || function > 3U || pull > KB7_GPIO_PULL_DOWN) {
        return;
    }
    uint32_t direction_value = KB7_MMIO32(bank + SNC_GPIO_DIRECTION);
    if (direction == KB7_GPIO_OUTPUT) {
        direction_value |= KB7_BIT(bit);
    } else {
        direction_value &= ~KB7_BIT(bit);
    }
    KB7_MMIO32(bank + SNC_GPIO_DIRECTION) = direction_value;

    uint32_t mode = KB7_MMIO32(bank + SNC_GPIO_MODE);
    mode &= ~(UINT32_C(3) << (bit * 2U));
    mode |= ((uint32_t)function & 3U) << (bit * 2U);
    KB7_MMIO32(bank + SNC_GPIO_MODE) = mode;

    /* Pull encoding is inferred; zero/floating is the conservative default. */
    if (pull != KB7_GPIO_FLOATING) {
        uint32_t mux = KB7_MMIO32(bank + SNC_GPIO_MUX);
        const uint32_t pull_bit = KB7_BIT(bit);
        mux = pull == KB7_GPIO_PULL_UP ? (mux | pull_bit) : (mux & ~pull_bit);
        KB7_MMIO32(bank + SNC_GPIO_MUX) = mux;
    }
    kb7_dsb();
}

void kb7_gpio_write(uint8_t logical, bool high) {
    const uint32_t bank = kb7_gpio_bank(logical);
    const uint16_t mask = kb7_gpio_mask(logical);
    if (bank != 0U && mask != 0U) {
        KB7_MMIO32(bank + (high ? SNC_GPIO_SET : SNC_GPIO_CLEAR)) = mask;
    }
}

bool kb7_gpio_read(uint8_t logical) {
    const uint32_t bank = kb7_gpio_bank(logical);
    const uint16_t mask = kb7_gpio_mask(logical);
    return bank != 0U && mask != 0U && (KB7_MMIO32(bank + SNC_GPIO_DATA) & mask) != 0U;
}
