#include <stdint.h>

#include "kb7/input.h"

static bool bit_set(const uint8_t bits[19], uint8_t usage) {
    return (bits[usage >> 3U] & KB7_BIT(usage & 7U)) != 0U;
}

static void release_all(uint8_t raw[KB7_HALL_KEY_COUNT]) {
    kb7_memset(raw, 0xff, KB7_HALL_KEY_COUNT);
}

int main(void) {
    static const uint8_t expected_usage[KB7_LOGICAL_KEY_COUNT] = {
        0x29U,0x1fU,0x39U,0x64U,0x3bU,0x21U,0x07U,0x06U,0x3eU,0x25U,
        0x0cU,0x05U,0x40U,0x27U,0x0fU,0x37U,0x43U,0x2aU,0x28U,0xe4U,
        0x3aU,0x2bU,0x04U,0x1dU,0x3cU,0x22U,0x09U,0x19U,0x3fU,0x17U,
        0x0bU,0x11U,0x41U,0x2dU,0x33U,0x38U,0x44U,0x2fU,0xe5U,0x50U,
        0x35U,0x14U,0x16U,0xe0U,0x3dU,0x08U,0x0aU,0xe2U,0x23U,0x1cU,
        0x0dU,0x10U,0x42U,0x12U,0x34U,0xe6U,0x45U,0x30U,0x52U,0x51U,
        0x1eU,0x1aU,0xe1U,0xe3U,0x20U,0x15U,0x1bU,0x2cU,0x24U,0x18U,
        0x0eU,0x36U,0x26U,0x13U,0x32U,0x65U,0x2eU,0x31U,0xf1U,0x4fU,
        0x8aU,0x87U,0x8bU,0x88U,0x89U,
    };
    uint8_t logical = 0xffU;
    if (!kb7_keymap_route(0x4fU, KB7_LAYOUT_DEFAULT_80, &logical) || logical != 0x4fU)
        return 1;
    if (kb7_keymap_route(0x50U, KB7_LAYOUT_DEFAULT_80, &logical)) return 2;
    if (!kb7_keymap_route(0x03U, KB7_LAYOUT_ALTERNATE_82, &logical) || logical != 0x52U)
        return 3;
    if (!kb7_keymap_route(0x37U, KB7_LAYOUT_ALTERNATE_82, &logical) || logical != 0x53U)
        return 4;
    if (!kb7_keymap_route(0x4dU, KB7_LAYOUT_ALTERNATE_82, &logical) || logical != 0x54U)
        return 5;

    for (uint8_t sensor = 0U; sensor < KB7_HALL_KEY_COUNT; ++sensor) {
        const bool default_valid = kb7_keymap_route(sensor, KB7_LAYOUT_DEFAULT_80,
                                                    &logical);
        if (default_valid != (sensor < 80U) ||
            (default_valid && logical != sensor)) return 6;
        const bool variant2_valid = kb7_keymap_route(
            sensor, KB7_LAYOUT_DEFAULT_80_VARIANT_2, &logical);
        if (variant2_valid != (sensor < 80U) ||
            (variant2_valid && logical != sensor)) return 7;
        const bool variant3_valid = kb7_keymap_route(
            sensor, KB7_LAYOUT_DEFAULT_80_VARIANT_3, &logical);
        if (variant3_valid != (sensor < 80U) ||
            (variant3_valid && logical != sensor)) return 8;
        if (!kb7_keymap_route(sensor, KB7_LAYOUT_ALTERNATE_82, &logical)) return 7;
        const uint8_t expected_logical = sensor == 0x03U ? 0x52U :
            (sensor == 0x37U ? 0x53U : (sensor == 0x4dU ? 0x54U : sensor));
        if (logical != expected_logical) return 8;
    }

    uint8_t usage;
    for (uint8_t key = 0U; key < KB7_LOGICAL_KEY_COUNT; ++key) {
        if (!kb7_keymap_default_usage(key, &usage) || usage != expected_usage[key]) return 9;
    }
    if (!kb7_keymap_default_usage(0U, &usage) || usage != 0x29U) return 10;
    if (!kb7_keymap_default_usage(KB7_FN_LOGICAL_KEY, &usage) ||
        usage != KB7_INTERNAL_USAGE_FN) return 11;
    struct kb7_hid_binding binding;
    if (kb7_keymap_lookup(KB7_FN_LOGICAL_KEY, &binding)) return 12;
    if (!kb7_keymap_lookup(0x3eU, &binding) || binding.modifier_mask != 2U) return 13;

    uint8_t conversion[256];
    for (uint16_t raw = 0U; raw <= 255U; ++raw) {
        conversion[raw] = kb7_hall_raw_to_travel((uint8_t)raw);
        if (raw != 0U && conversion[raw] > conversion[raw - 1U]) return 14;
    }
    if (conversion[0] != 32U || conversion[11] != 32U || conversion[12] != 31U ||
        conversion[252] != 1U || conversion[253] != 0U || conversion[255] != 0U)
        return 15;
    if (kb7_crc32(conversion, sizeof(conversion)) != UINT32_C(0xae36c9e1)) return 16;

    struct kb7_hall_state hall[KB7_HALL_KEY_COUNT];
    kb7_hall_reset(hall);
    const struct kb7_hall_config rapid = {16U, 2U, 2U, true};
    if (kb7_hall_update(&hall[0], 10U, &rapid)) return 13;
    if (!kb7_hall_update(&hall[0], 16U, &rapid)) return 14;
    if (kb7_hall_update(&hall[0], 13U, &rapid)) return 15;
    if (kb7_hall_update(&hall[0], 14U, &rapid)) return 16;
    if (!kb7_hall_update(&hall[0], 15U, &rapid)) return 17;

    struct kb7_input_profile profile;
    struct kb7_input_state state;
    struct kb7_input_frame frame;
    kb7_input_profile_default(&profile);
    struct kb7_hall_config simple = {16U, 2U, 2U, false};
    kb7_input_profile_set_global_hall(&profile, &simple);
    profile.analog.smoothing = 0U;
    profile.analog.deadzone = 0U;
    profile.analog.saturation = 32U;
    kb7_input_reset(&state, &profile);

    uint8_t raw[KB7_HALL_KEY_COUNT];
    release_all(raw);
    raw[0] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (!bit_set(frame.keyboard_bits, 0x29U) || frame.travel[0] != 32U) return 18;

    release_all(raw);
    raw[0x3eU] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (frame.modifiers != 2U) return 19;

    const struct kb7_key_action fn_b = {0x05U, KB7_KEY_ACTION_KEYBOARD, 0U};
    if (!kb7_input_profile_set_action(&profile, KB7_INPUT_FN1, 0U, &fn_b)) return 20;
    release_all(raw);
    raw[KB7_FN_LOGICAL_KEY] = 0U;
    raw[0] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (!state.fn_down || state.mode != KB7_INPUT_FN1 ||
        !bit_set(frame.keyboard_bits, 0x05U) || bit_set(frame.keyboard_bits, 0x29U))
        return 21;
    release_all(raw);
    raw[0] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (state.fn_down || state.mode != KB7_INPUT_PRIMARY ||
        !bit_set(frame.keyboard_bits, 0x29U)) return 22;

    const struct kb7_key_action game_b = {0x06U, KB7_KEY_ACTION_KEYBOARD, 0U};
    const struct kb7_key_action easy_b = {0x07U, KB7_KEY_ACTION_KEYBOARD, 0U};
    if (!kb7_input_profile_set_action(&profile, KB7_INPUT_GAME, 0U, &game_b) ||
        !kb7_input_profile_set_action(&profile, KB7_INPUT_EASY_SHIFT, 0U, &easy_b) ||
        !kb7_input_set_mode(&state, KB7_INPUT_GAME)) return 35;
    kb7_input_process(&state, &profile, raw, &frame);
    if (state.mode != KB7_INPUT_GAME || !bit_set(frame.keyboard_bits, 0x06U)) return 36;
    raw[KB7_FN_LOGICAL_KEY] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (state.mode != KB7_INPUT_FN1 || !bit_set(frame.keyboard_bits, 0x05U)) return 37;
    release_all(raw);
    raw[0] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (state.mode != KB7_INPUT_GAME || !bit_set(frame.keyboard_bits, 0x06U)) return 38;

    const struct kb7_key_action game_fn_none = {0U, KB7_KEY_ACTION_NONE, 0U};
    if (!kb7_input_profile_set_action(&profile, KB7_INPUT_GAME,
                                      KB7_FN_LOGICAL_KEY, &game_fn_none)) return 48;
    raw[KB7_FN_LOGICAL_KEY] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (!state.fn_down || state.fn_layer_active || state.mode != KB7_INPUT_GAME ||
        !bit_set(frame.keyboard_bits, 0x06U)) return 49;
    release_all(raw);
    raw[0] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (state.fn_down || state.fn_layer_active || state.mode != KB7_INPUT_GAME ||
        !bit_set(frame.keyboard_bits, 0x06U)) return 50;

    if (!kb7_input_set_mode(&state, KB7_INPUT_EASY_SHIFT)) return 39;
    kb7_input_process(&state, &profile, raw, &frame);
    if (!bit_set(frame.keyboard_bits, 0x07U)) return 40;
    if (!kb7_input_set_mode(&state, KB7_INPUT_PRIMARY)) return 41;

    const struct kb7_hall_config strict = {24U, 2U, 2U, false};
    if (!kb7_input_profile_set_hall(&profile, 0U, &strict)) return 42;
    release_all(raw);
    raw[0] = 206U;
    raw[1] = 206U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (bit_set(frame.keyboard_bits, 0x29U) ||
        !bit_set(frame.keyboard_bits, 0x1fU)) return 43;
    if (!kb7_input_profile_set_hall(&profile, 0U, &simple)) return 44;

    profile.analog.digital_passthrough = false;
    release_all(raw);
    raw[0x27U] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (frame.gamepad.left_x != -32767 || bit_set(frame.keyboard_bits, 0x50U)) return 23;
    raw[0x4fU] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (frame.gamepad.left_x != 0) return 24;
    release_all(raw);
    raw[0x3bU] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (frame.gamepad.left_y != 32767) return 25;

    profile.analog.curve = KB7_ANALOG_EXPONENTIAL;
    release_all(raw);
    raw[0x4fU] = 206U; /* exact stock conversion: 16 tenths of a millimetre */
    kb7_input_process(&state, &profile, raw, &frame);
    if (frame.gamepad.left_x < 8190 || frame.gamepad.left_x > 8192) return 26;
    profile.analog.curve = KB7_ANALOG_S_CURVE;
    kb7_input_process(&state, &profile, raw, &frame);
    if (frame.gamepad.left_x < 16382 || frame.gamepad.left_x > 16384) return 27;

    profile.layout = KB7_LAYOUT_ALTERNATE_82;
    profile.analog.enabled = false;
    kb7_input_reset(&state, &profile);
    release_all(raw);
    raw[0x03U] = 0U;
    kb7_input_process(&state, &profile, raw, &frame);
    if (!bit_set(frame.keyboard_bits, 0x8bU) || bit_set(frame.keyboard_bits, 0x64U))
        return 28;

    const struct kb7_key_action invalid = {KB7_INTERNAL_USAGE_FN,
                                            KB7_KEY_ACTION_KEYBOARD, 0U};
    if (kb7_input_profile_set_action(&profile, KB7_INPUT_PRIMARY, 0U, &invalid)) return 29;
    const struct kb7_key_action unsupported_layer = {
        0U, KB7_KEY_ACTION_MOMENTARY_LAYER, KB7_INPUT_GAME,
    };
    if (kb7_input_profile_set_action(&profile, KB7_INPUT_PRIMARY, 0U,
                                     &unsupported_layer)) return 30;
    const struct kb7_key_action fn_rebind = {0x04U, KB7_KEY_ACTION_KEYBOARD, 0U};
    if (kb7_input_profile_set_action(&profile, KB7_INPUT_PRIMARY,
                                     KB7_FN_LOGICAL_KEY, &fn_rebind)) return 31;
    const struct kb7_key_action fn_none = {0U, KB7_KEY_ACTION_NONE, 0U};
    if (kb7_input_profile_set_action(&profile, KB7_INPUT_PRIMARY,
                                     KB7_FN_LOGICAL_KEY, &fn_none)) return 32;
    struct kb7_analog_config bad_analog = profile.analog;
    bad_analog.enabled = true;
    bad_analog.logical_key[KB7_ANALOG_X_POSITIVE] =
        bad_analog.logical_key[KB7_ANALOG_X_NEGATIVE];
    if (kb7_input_profile_set_analog(&profile, &bad_analog)) return 33;
    const struct kb7_hall_config bad_hall = {0U, 2U, 2U, true};
    if (kb7_input_profile_set_hall(&profile, 0U, &bad_hall)) return 34;
    const struct kb7_key_action last_usage = {
        KB7_KEYBOARD_USAGE_BITS - 1U, KB7_KEY_ACTION_KEYBOARD, 0U,
    };
    const struct kb7_key_action past_bits = {
        KB7_KEYBOARD_USAGE_BITS, KB7_KEY_ACTION_KEYBOARD, 0U,
    };
    if (!kb7_input_profile_set_action(&profile, KB7_INPUT_PRIMARY, 0U,
                                      &last_usage) ||
        kb7_input_profile_set_action(&profile, KB7_INPUT_PRIMARY, 0U,
                                     &past_bits)) return 45;

    struct kb7_input_link_guard link = {0};
    if (kb7_input_link_should_neutralize(&link, true) ||
        kb7_input_link_should_neutralize(&link, false) ||
        kb7_input_link_should_neutralize(&link, false) ||
        !kb7_input_link_should_neutralize(&link, false) ||
        kb7_input_link_should_neutralize(&link, false)) return 46;
    if (kb7_input_link_should_neutralize(&link, true) ||
        kb7_input_link_should_neutralize(&link, false) ||
        kb7_input_link_should_neutralize(&link, false) ||
        !kb7_input_link_should_neutralize(&link, false)) return 47;
    return 0;
}
