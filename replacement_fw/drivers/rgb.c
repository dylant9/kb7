#include "kb7/drivers.h"

/*
 * Board-specific LED topology and controller packets are deliberately omitted
 * from the public export. This fail-closed implementation prevents accidental
 * use of unverified or privately recovered mappings.
 */

bool kb7_rgb_present(uint16_t position) {
    (void)position;
    return false;
}

bool kb7_rgb_init(void) {
    return false;
}

void kb7_rgb_set_brightness(uint8_t percent) {
    (void)percent;
}

void kb7_rgb_show(const struct kb7_rgb colors[KB7_RGB_POSITION_COUNT]) {
    (void)colors;
}
