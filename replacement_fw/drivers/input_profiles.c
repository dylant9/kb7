#include "kb7/input_profiles.h"

void kb7_input_profile_bank_default(struct kb7_input_profile_bank *bank) {
    if (bank == NULL) return;
    bank->active = 0U;
    for (uint8_t slot = 0U; slot < KB7_INPUT_PROFILE_SLOT_COUNT; ++slot) {
        kb7_input_profile_default(&bank->slot[slot]);
    }
}

struct kb7_input_profile *kb7_input_profile_active(struct kb7_input_profile_bank *bank) {
    if (bank == NULL || bank->active >= KB7_INPUT_PROFILE_SLOT_COUNT) return NULL;
    return &bank->slot[bank->active];
}

const struct kb7_input_profile *kb7_input_profile_active_const(
    const struct kb7_input_profile_bank *bank) {
    if (bank == NULL || bank->active >= KB7_INPUT_PROFILE_SLOT_COUNT) return NULL;
    return &bank->slot[bank->active];
}

bool kb7_input_profile_bank_replace(struct kb7_input_profile_bank *bank, uint8_t slot,
                                    const struct kb7_input_profile *profile) {
    if (bank == NULL || slot >= KB7_INPUT_PROFILE_SLOT_COUNT ||
        !kb7_input_profile_valid(profile)) {
        return false;
    }
    bank->slot[slot] = *profile;
    return true;
}

bool kb7_input_profile_bank_select(struct kb7_input_profile_bank *bank, uint8_t slot,
                                   struct kb7_input_state *state) {
    if (bank == NULL || state == NULL || slot >= KB7_INPUT_PROFILE_SLOT_COUNT) return false;
    bank->active = slot;
    kb7_input_reset(state, &bank->slot[slot]);
    return true;
}
