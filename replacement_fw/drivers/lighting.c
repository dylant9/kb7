#include "kb7/lighting.h"

static uint8_t blend_channel(uint8_t left, uint8_t right, uint8_t weight) {
    const uint32_t inverse = UINT32_C(255) - weight;
    return (uint8_t)(((uint32_t)left * inverse + (uint32_t)right * weight + 127U) / 255U);
}

static struct kb7_rgb blend(struct kb7_rgb left, struct kb7_rgb right, uint8_t weight) {
    return (struct kb7_rgb){
        blend_channel(left.red, right.red, weight),
        blend_channel(left.green, right.green, weight),
        blend_channel(left.blue, right.blue, weight),
    };
}

static uint8_t position_weight(uint16_t position, uint8_t direction) {
    uint16_t normalized = (uint16_t)(((uint32_t)position * 255U) /
                                     (KB7_RGB_POSITION_COUNT - 1U));
    if (direction == KB7_LIGHTING_WEST || direction == KB7_LIGHTING_SOUTH) {
        normalized = (uint16_t)(255U - normalized);
    } else if (direction == KB7_LIGHTING_RADIAL) {
        normalized = normalized <= 127U ? (uint16_t)(normalized * 2U)
                                        : (uint16_t)((255U - normalized) * 2U);
    }
    return (uint8_t)normalized;
}

static uint8_t triangle(uint32_t phase) {
    phase %= 510U;
    return (uint8_t)(phase <= 255U ? phase : 510U - phase);
}

static uint8_t maximum_travel(const uint8_t travel[KB7_HALL_KEY_COUNT]) {
    uint8_t maximum = 0U;
    if (travel == NULL) return maximum;
    for (uint8_t key = 0U; key < KB7_HALL_KEY_COUNT; ++key) {
        if (travel[key] > maximum) maximum = travel[key];
    }
    return maximum > KB7_HALL_TRAVEL_MAX ? KB7_HALL_TRAVEL_MAX : maximum;
}

void kb7_lighting_render(const struct kb7_lighting_profile *profile,
                         uint32_t milliseconds,
                         const uint8_t travel[KB7_HALL_KEY_COUNT],
                         struct kb7_rgb colors[KB7_RGB_POSITION_COUNT]) {
    if (profile == NULL || colors == NULL) return;
    const uint8_t maximum = maximum_travel(travel);
    for (uint16_t position = 0U; position < KB7_RGB_POSITION_COUNT; ++position) {
        struct kb7_rgb color = {0U, 0U, 0U};
        if (!profile->enabled || !kb7_rgb_present(position)) {
            colors[position] = color;
            continue;
        }
        switch (profile->effect) {
        case KB7_LIGHTING_STATIC:
            color = profile->primary;
            break;
        case KB7_LIGHTING_GRADIENT:
            color = blend(profile->primary, profile->secondary,
                          position_weight(position, profile->direction));
            break;
        case KB7_LIGHTING_AURORA: {
            const uint32_t rate = 1U + profile->speed;
            const uint32_t phase = (milliseconds * rate) / 20U +
                                   (uint32_t)position_weight(position, profile->direction) * 2U;
            color = blend(profile->primary, profile->secondary, triangle(phase));
            break;
        }
        case KB7_LIGHTING_REACTIVE:
            color = maximum == 0U ? profile->primary : profile->reactive;
            break;
        case KB7_LIGHTING_HEATMAP:
            color = blend(profile->primary, profile->reactive,
                          (uint8_t)(((uint32_t)maximum * 255U) / KB7_HALL_TRAVEL_MAX));
            break;
        default:
            color = profile->primary;
            break;
        }
        colors[position] = color;
    }
}
