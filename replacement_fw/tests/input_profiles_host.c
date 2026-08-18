#include <stdint.h>

#include "kb7/input_profiles.h"

int main(void) {
    struct kb7_input_profile_bank bank;
    struct kb7_input_state state;
    kb7_input_profile_bank_default(&bank);
    if (bank.active != 0U || kb7_input_profile_active(&bank) != &bank.slot[0]) return 1;

    struct kb7_input_profile custom = bank.slot[0];
    custom.initial_mode = KB7_INPUT_GAME;
    const struct kb7_key_action action = {0x05U, KB7_KEY_ACTION_KEYBOARD, 0U};
    if (!kb7_input_profile_set_action(&custom, KB7_INPUT_GAME, 0U, &action) ||
        !kb7_input_profile_bank_replace(&bank, 2U, &custom)) return 2;
    kb7_input_reset(&state, &bank.slot[0]);
    if (!kb7_input_profile_bank_select(&bank, 2U, &state) || bank.active != 2U ||
        state.mode != KB7_INPUT_GAME ||
        kb7_input_profile_active_const(&bank)->actions[KB7_INPUT_GAME][0].code != 0x05U) {
        return 3;
    }
    if (kb7_input_profile_bank_select(&bank, KB7_INPUT_PROFILE_SLOT_COUNT, &state)) return 4;
    struct kb7_input_profile invalid = custom;
    invalid.layout = 8U;
    if (kb7_input_profile_bank_replace(&bank, 1U, &invalid)) return 5;
    invalid = custom;
    invalid.hall[12].actuation = 0U;
    if (kb7_input_profile_bank_replace(&bank, 1U, &invalid)) return 6;
    invalid = custom;
    invalid.actions[KB7_INPUT_PRIMARY][12].kind = 0xffU;
    if (kb7_input_profile_bank_replace(&bank, 1U, &invalid)) return 7;
    invalid = custom;
    invalid.layout = KB7_LAYOUT_DEFAULT_80_VARIANT_3;
    if (!kb7_input_profile_bank_replace(&bank, 1U, &invalid)) return 8;
    return 0;
}
