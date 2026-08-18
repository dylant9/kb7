#include <stdint.h>

#include "kb7/drivers.h"

static uint8_t sample;
static uint8_t configured;

uint32_t kb7_gpio_bank(uint8_t logical) { return logical; }
uint16_t kb7_gpio_mask(uint8_t logical) { return logical; }
void kb7_gpio_configure(uint8_t logical, enum kb7_gpio_direction direction,
                        uint8_t function, enum kb7_gpio_pull pull) {
    if ((logical == 72U || logical == 73U) && direction == KB7_GPIO_INPUT &&
        function == 0U && pull == KB7_GPIO_PULL_UP) ++configured;
}
void kb7_gpio_write(uint8_t logical, bool high) { (void)logical; (void)high; }
bool kb7_gpio_read(uint8_t logical) {
    return logical == 72U ? (sample & 2U) != 0U : (sample & 1U) != 0U;
}

int main(void) {
    sample = 0U;
    kb7_encoder_init();
    if (configured != 2U) return 1;
    for (uint8_t repeat = 0U; repeat < 20U; ++repeat) {
        if (kb7_encoder_poll() != KB7_ENCODER_NONE) return 2;
    }
    sample = 3U;
    if (kb7_encoder_poll() != KB7_ENCODER_NONE) return 3;
    for (uint8_t repeat = 0U; repeat < 20U; ++repeat) {
        if (kb7_encoder_poll() != KB7_ENCODER_NONE) return 4;
    }
    sample = 1U;
    if (kb7_encoder_poll() != KB7_ENCODER_NONE) return 5;
    sample = 0U;
    if (kb7_encoder_poll() != KB7_ENCODER_CW) return 6;
    return 0;
}
