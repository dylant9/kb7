#include "kb7/drivers.h"

static uint8_t history;

void kb7_encoder_init(void) {
    kb7_gpio_configure(72U, KB7_GPIO_INPUT, 0U, KB7_GPIO_PULL_UP);
    kb7_gpio_configure(73U, KB7_GPIO_INPUT, 0U, KB7_GPIO_PULL_UP);
    history = (uint8_t)((kb7_gpio_read(72U) ? 2U : 0U) |
                        (kb7_gpio_read(73U) ? 1U : 0U));
}

enum kb7_encoder_event kb7_encoder_poll(void) {
    const uint8_t current = (uint8_t)((kb7_gpio_read(72U) ? 2U : 0U) |
                                      (kb7_gpio_read(73U) ? 1U : 0U));
    history = (uint8_t)((history << 2U) | current);
    if (history == 0x34U || history == 0x0bU) {
        return KB7_ENCODER_CW;
    }
    if (history == 0x07U || history == 0x38U) {
        return KB7_ENCODER_CCW;
    }
    return KB7_ENCODER_NONE;
}
