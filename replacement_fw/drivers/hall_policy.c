#include "kb7/drivers.h"

void kb7_hall_reset(struct kb7_hall_state state[KB7_HALL_KEY_COUNT]) {
    for (size_t key = 0U; key < KB7_HALL_KEY_COUNT; ++key) {
        state[key].pressed = false;
        state[key].peak = 0U;
        state[key].valley = 255U;
    }
}

bool kb7_hall_update(struct kb7_hall_state *state, uint8_t sample,
                     const struct kb7_hall_config *config) {
    if (state == NULL || config == NULL) {
        return false;
    }
    if (!config->rapid_trigger) {
        state->pressed = sample >= config->actuation;
        state->peak = sample;
        state->valley = sample;
        return state->pressed;
    }
    if (state->pressed) {
        if (sample > state->peak) {
            state->peak = sample;
        }
        if ((uint8_t)(state->peak - sample) >= config->rapid_release_delta) {
            state->pressed = false;
            state->valley = sample;
        }
    } else {
        if (sample < state->valley) {
            state->valley = sample;
        }
        const bool crossed_absolute = sample >= config->actuation;
        const bool crossed_delta = (uint8_t)(sample - state->valley) >= config->rapid_press_delta;
        if (crossed_absolute || crossed_delta) {
            state->pressed = true;
            state->peak = sample;
        }
    }
    return state->pressed;
}
