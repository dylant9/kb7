#include "kb7/action_bar.h"

/* Stock bitmap order, not package-pin or visual order. Inputs are active-low. */
static const uint8_t action_bar_pin[KB7_ACTION_BAR_KEY_COUNT] = {
    75U, 76U, 77U, 64U, 74U, 78U, 79U,
};

void kb7_action_bar_init(struct kb7_action_bar_state *state) {
    if (state != NULL) kb7_memset(state, 0, sizeof(*state));
    for (uint8_t key = 0U; key < KB7_ACTION_BAR_KEY_COUNT; ++key) {
        kb7_gpio_configure(action_bar_pin[key], KB7_GPIO_INPUT, 0U, KB7_GPIO_PULL_UP);
    }
}

uint8_t kb7_action_bar_sample(void) {
    uint8_t result = 0U;
    for (uint8_t key = 0U; key < KB7_ACTION_BAR_KEY_COUNT; ++key) {
        if (!kb7_gpio_read(action_bar_pin[key])) result |= (uint8_t)KB7_BIT(key);
    }
    return result;
}

void kb7_action_bar_update(struct kb7_action_bar_state *state, uint8_t raw_pressed,
                           uint8_t *pressed_edges, uint8_t *released_edges) {
    if (pressed_edges != NULL) *pressed_edges = 0U;
    if (released_edges != NULL) *released_edges = 0U;
    if (state == NULL) return;
    raw_pressed &= (uint8_t)((1U << KB7_ACTION_BAR_KEY_COUNT) - 1U);
    for (uint8_t key = 0U; key < KB7_ACTION_BAR_KEY_COUNT; ++key) {
        const uint8_t mask = (uint8_t)KB7_BIT(key);
        const bool raw = (raw_pressed & mask) != 0U;
        const bool stable = (state->stable_pressed & mask) != 0U;
        const bool candidate = (state->candidate_pressed & mask) != 0U;
        if (raw == stable) {
            state->candidate_count[key] = 0U;
            if (raw) state->candidate_pressed |= mask;
            else state->candidate_pressed &= (uint8_t)~mask;
            continue;
        }
        if (raw != candidate) {
            if (raw) state->candidate_pressed |= mask;
            else state->candidate_pressed &= (uint8_t)~mask;
            state->candidate_count[key] = 1U;
            continue;
        }
        if (state->candidate_count[key] < KB7_ACTION_BAR_DEBOUNCE_SAMPLES) {
            ++state->candidate_count[key];
        }
        if (state->candidate_count[key] < KB7_ACTION_BAR_DEBOUNCE_SAMPLES) continue;
        state->candidate_count[key] = 0U;
        if (raw) {
            state->stable_pressed |= mask;
            if (pressed_edges != NULL) *pressed_edges |= mask;
        } else {
            state->stable_pressed &= (uint8_t)~mask;
            if (released_edges != NULL) *released_edges |= mask;
        }
    }
}
