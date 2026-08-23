#include "kb7/drivers.h"
#include "kb7/platform_boot.h"
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
    if (bank == 0U || direction > KB7_GPIO_OUTPUT || function > 7U ||
        pull > KB7_GPIO_PULL_DOWN || !kb7_gpio_pinmux_known(logical, function)) {
        return;
    }

    /* GPIO_PnCFG is the two-bit electrical pull/repeater field, not pinmux. */
    /* The stock backlight path proves P0.6/CT32B6_PWM1 at PINCTRL bit 17. */
    if (logical == 6U) {
        uint32_t pinctrl = KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PINCTRL);
        if (function == 7U) {
            pinctrl |= SNC_PINCTRL_TIMER6_PWM1_ROUTE;
        } else {
            pinctrl &= ~SNC_PINCTRL_TIMER6_PWM1_ROUTE;
        }
        KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PINCTRL) = pinctrl;
    }

    /* A selected peripheral owns the pad; stock does not rewrite GPIO state. */
    if (function == 0U) {
        uint32_t config = KB7_MMIO32(bank + SNC_GPIO_PIN_CONFIG);
        config &= ~(UINT32_C(3) << (bit * 2U));
        config |= ((uint32_t)pull & 3U) << (bit * 2U);
        KB7_MMIO32(bank + SNC_GPIO_PIN_CONFIG) = config;

        uint32_t direction_value = KB7_MMIO32(bank + SNC_GPIO_DIRECTION);
        if (direction == KB7_GPIO_OUTPUT) {
            direction_value |= KB7_BIT(bit);
        } else {
            direction_value &= ~KB7_BIT(bit);
        }
        KB7_MMIO32(bank + SNC_GPIO_DIRECTION) = direction_value;
    }
    kb7_dsb();
}

bool kb7_gpio_pinmux_known(uint8_t logical, uint8_t function) {
    if (logical >= 80U || function > 7U) {
        return false;
    }
    /* GPIO is the reset/default route for every pad used by this image. */
    if (function == 0U) {
        return true;
    }
    /* P0.6 is the one KB7 route requiring a recovered PINCTRL bit. */
    if (logical == 6U && function == 7U) {
        return true;
    }
    /*
     * These routes have no PINCTRL footnote in the data-sheet table.  Stock
     * leaves PINCTRL[1] clear for the P2.4..P3.9 LCD group and initializes
     * SPI0 on P0.14..P1.1 without another PINCTRL write.
     */
    if (function == 1U && logical >= 36U && logical <= 57U) {
        return true;
    }
    if (function == 4U && logical >= 14U && logical <= 17U) {
        return true;
    }
    return false;
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
