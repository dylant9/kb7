#include <stdint.h>

#include "kb7/mcu2_protocol.h"

static uint8_t configure_count;

bool kb7_gpio_pinmux_known(uint8_t logical, uint8_t function) {
    (void)logical;
    (void)function;
    return false;
}

void kb7_gpio_configure(uint8_t logical, enum kb7_gpio_direction direction,
                        uint8_t function, enum kb7_gpio_pull pull) {
    (void)logical;
    (void)direction;
    (void)function;
    (void)pull;
    ++configure_count;
}

int main(void) {
    if (kb7_mcu2_init() || configure_count != 0U) return 1;
    return 0;
}
