#ifndef KB7_INPUT_PROFILES_H
#define KB7_INPUT_PROFILES_H

#include "kb7/input.h"

/* Four independent project-defined RAM slots. Persistent KBP1 loading may copy
 * validated complete profiles into these slots through the API below. */
#define KB7_INPUT_PROFILE_SLOT_COUNT 4U

struct kb7_input_profile_bank {
    struct kb7_input_profile slot[KB7_INPUT_PROFILE_SLOT_COUNT];
    uint8_t active;
};

void kb7_input_profile_bank_default(struct kb7_input_profile_bank *bank);
struct kb7_input_profile *kb7_input_profile_active(struct kb7_input_profile_bank *bank);
const struct kb7_input_profile *kb7_input_profile_active_const(
    const struct kb7_input_profile_bank *bank);
bool kb7_input_profile_bank_replace(struct kb7_input_profile_bank *bank, uint8_t slot,
                                    const struct kb7_input_profile *profile);
bool kb7_input_profile_bank_select(struct kb7_input_profile_bank *bank, uint8_t slot,
                                   struct kb7_input_state *state);

#endif
