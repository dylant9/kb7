#include <stdint.h>

#include "kb7/action_bar.h"

static uint8_t configured_pin[KB7_ACTION_BAR_KEY_COUNT];
static uint8_t configured_count;
static uint8_t low_pin;

uint32_t kb7_gpio_bank(uint8_t logical) { return logical; }
uint16_t kb7_gpio_mask(uint8_t logical) { return (uint16_t)logical; }
void kb7_gpio_configure(uint8_t logical, enum kb7_gpio_direction direction,
                        uint8_t function, enum kb7_gpio_pull pull) {
    if (configured_count < KB7_ACTION_BAR_KEY_COUNT) {
        configured_pin[configured_count++] = logical;
    }
    if (direction != KB7_GPIO_INPUT || function != 0U || pull != KB7_GPIO_PULL_UP) {
        configured_count = 0xffU;
    }
}
void kb7_gpio_write(uint8_t logical, bool high) { (void)logical; (void)high; }
bool kb7_gpio_read(uint8_t logical) { return logical != low_pin; }

int main(void) {
    struct kb7_action_bar_state state;
    kb7_memset(&state, 0xff, sizeof(state));
    kb7_action_bar_init(&state);
    const uint8_t expected_pin[KB7_ACTION_BAR_KEY_COUNT] = {
        75U, 76U, 77U, 64U, 74U, 78U, 79U,
    };
    if (configured_count != KB7_ACTION_BAR_KEY_COUNT ||
        kb7_memcmp(configured_pin, expected_pin, sizeof(expected_pin)) != 0 ||
        state.stable_pressed != 0U || state.candidate_pressed != 0U) return 1;
    low_pin = 64U;
    if (kb7_action_bar_sample() != KB7_BIT(3)) return 2;

    uint8_t pressed;
    uint8_t released;
    kb7_action_bar_update(&state, 1U, &pressed, &released);
    if (pressed != 0U || released != 0U) return 3;
    kb7_action_bar_update(&state, 1U, &pressed, &released);
    if (pressed != 0U) return 4;
    kb7_action_bar_update(&state, 1U, &pressed, &released);
    if (pressed != 1U || released != 0U || state.stable_pressed != 1U) return 5;
    kb7_action_bar_update(&state, 0U, &pressed, &released);
    kb7_action_bar_update(&state, 0U, &pressed, &released);
    kb7_action_bar_update(&state, 0U, &pressed, &released);
    if (pressed != 0U || released != 1U || state.stable_pressed != 0U) return 6;

    /* Bouncing away from a candidate restarts, rather than accumulates, time. */
    kb7_action_bar_update(&state, 2U, &pressed, &released);
    kb7_action_bar_update(&state, 0U, &pressed, &released);
    kb7_action_bar_update(&state, 2U, &pressed, &released);
    kb7_action_bar_update(&state, 2U, &pressed, &released);
    if (pressed != 0U) return 7;
    kb7_action_bar_update(&state, 2U, &pressed, &released);
    if (pressed != 2U) return 8;
    return 0;
}
