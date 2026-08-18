#include "kb7/lighting.h"

bool kb7_rgb_present(uint16_t position) {
    return position != 11U && position < KB7_RGB_POSITION_COUNT;
}

int main(void) {
    const struct kb7_lighting_profile profile = {
        true, KB7_LIGHTING_GRADIENT, 100U, 50U, KB7_LIGHTING_EAST,
        {0U, 0U, 0U}, {255U, 128U, 64U}, {255U, 0U, 0U},
    };
    struct kb7_rgb colors[KB7_RGB_POSITION_COUNT];
    uint8_t travel[KB7_HALL_KEY_COUNT] = {0};
    kb7_lighting_render(&profile, 0U, travel, colors);
    if (colors[0].red != 0U || colors[KB7_RGB_POSITION_COUNT - 1U].red != 255U) return 1;
    if (colors[11].red != 0U || colors[11].green != 0U || colors[11].blue != 0U) return 2;

    struct kb7_lighting_profile reactive = profile;
    reactive.effect = KB7_LIGHTING_REACTIVE;
    travel[4] = 1U;
    kb7_lighting_render(&reactive, 0U, travel, colors);
    if (colors[0].red != 255U || colors[0].green != 0U) return 3;
    reactive.enabled = false;
    kb7_lighting_render(&reactive, 0U, travel, colors);
    if (colors[0].red != 0U || colors[80].green != 0U) return 4;
    return 0;
}
