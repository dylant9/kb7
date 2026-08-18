#ifndef KB7_ACTION_BAR_H
#define KB7_ACTION_BAR_H

#include "kb7/drivers.h"

#define KB7_ACTION_BAR_KEY_COUNT 7U
#define KB7_ACTION_BAR_DEBOUNCE_SAMPLES 3U
#define KB7_HOST_ACTION_BAR_EVENT 0x41U

struct kb7_action_bar_state {
    uint8_t stable_pressed;
    uint8_t candidate_pressed;
    uint8_t candidate_count[KB7_ACTION_BAR_KEY_COUNT];
};

void kb7_action_bar_init(struct kb7_action_bar_state *state);
uint8_t kb7_action_bar_sample(void);
void kb7_action_bar_update(struct kb7_action_bar_state *state, uint8_t raw_pressed,
                           uint8_t *pressed_edges, uint8_t *released_edges);

#endif
