#include "kb7/input.h"

/*
 * V1.22's 256-byte conversion at 0x10058fa0 is monotonic, so its exact runs
 * can be represented by the inclusive raw ceiling for travel levels 32..0.
 * MCU2 A3 polarity is inverse: small wire values mean greater key travel.
 */
static const uint8_t raw_ceiling_by_descending_travel[KB7_HALL_TRAVEL_MAX + 1U] = {
    11U, 36U, 49U, 75U, 97U, 109U, 123U, 135U, 153U, 158U, 170U,
    177U, 187U, 193U, 200U, 205U, 210U, 213U, 218U, 222U, 226U,
    230U, 235U, 238U, 240U, 242U, 246U, 247U, 249U, 250U, 251U,
    252U, 255U,
};

uint8_t kb7_hall_raw_to_travel(uint8_t raw) {
    for (uint8_t index = 0U; index <= KB7_HALL_TRAVEL_MAX; ++index) {
        if (raw <= raw_ceiling_by_descending_travel[index]) {
            return (uint8_t)(KB7_HALL_TRAVEL_MAX - index);
        }
    }
    return 0U;
}

void kb7_hall_reset(struct kb7_hall_state state[KB7_HALL_KEY_COUNT]) {
    if (state == NULL) return;
    for (size_t key = 0U; key < KB7_HALL_KEY_COUNT; ++key) {
        state[key].pressed = false;
        state[key].peak = 0U;
        state[key].valley = KB7_HALL_TRAVEL_MAX;
    }
}

bool kb7_hall_update(struct kb7_hall_state *state, uint8_t sample,
                     const struct kb7_hall_config *config) {
    if (state == NULL || config == NULL) return false;
    if (sample > KB7_HALL_TRAVEL_MAX) sample = KB7_HALL_TRAVEL_MAX;

    if (!config->rapid_trigger) {
        state->pressed = sample >= config->actuation;
        state->peak = sample;
        state->valley = sample;
        return state->pressed;
    }

    if (state->pressed) {
        if (sample > state->peak) state->peak = sample;
        if ((uint16_t)sample + config->rapid_release_delta <= state->peak) {
            state->pressed = false;
            state->valley = sample;
        }
        return state->pressed;
    }

    if (sample < state->valley) state->valley = sample;
    const bool first_absolute_crossing = state->peak == 0U &&
                                         sample >= config->actuation;
    const bool repeat_delta_crossing = state->peak != 0U &&
        sample >= (uint16_t)state->valley + config->rapid_press_delta;
    if (first_absolute_crossing || repeat_delta_crossing) {
        state->pressed = true;
        state->peak = sample;
    }
    return state->pressed;
}
