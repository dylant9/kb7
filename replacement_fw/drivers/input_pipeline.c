#include "kb7/input.h"

static bool keyboard_usage_valid(uint16_t usage) {
    return (usage > 0U && usage < KB7_KEYBOARD_USAGE_BITS) ||
           (usage >= 0xe0U && usage <= 0xe7U);
}

static struct kb7_hall_config sanitized_hall(const struct kb7_hall_config *source) {
    struct kb7_hall_config result = *source;
    if (result.actuation == 0U) result.actuation = 1U;
    if (result.actuation > KB7_HALL_TRAVEL_MAX) result.actuation = KB7_HALL_TRAVEL_MAX;
    if (result.rapid_press_delta == 0U) result.rapid_press_delta = 1U;
    if (result.rapid_press_delta > KB7_HALL_TRAVEL_MAX) {
        result.rapid_press_delta = KB7_HALL_TRAVEL_MAX;
    }
    if (result.rapid_release_delta == 0U) result.rapid_release_delta = 1U;
    if (result.rapid_release_delta > KB7_HALL_TRAVEL_MAX) {
        result.rapid_release_delta = KB7_HALL_TRAVEL_MAX;
    }
    return result;
}

void kb7_input_profile_default(struct kb7_input_profile *profile) {
    if (profile == NULL) return;
    kb7_memset(profile, 0, sizeof(*profile));
    profile->layout = KB7_LAYOUT_DEFAULT_80;
    profile->initial_mode = KB7_INPUT_PRIMARY;
    const struct kb7_hall_config hall = {16U, 2U, 2U, true};
    for (uint8_t logical = 0U; logical < KB7_LOGICAL_KEY_COUNT; ++logical) {
        profile->hall[logical] = hall;
        uint8_t usage = 0U;
        (void)kb7_keymap_default_usage(logical, &usage);
        struct kb7_key_action *const primary =
            &profile->actions[KB7_INPUT_PRIMARY][logical];
        if (usage == KB7_INTERNAL_USAGE_FN) {
            primary->kind = KB7_KEY_ACTION_MOMENTARY_LAYER;
            primary->argument = KB7_INPUT_FN1;
        } else if (keyboard_usage_valid(usage)) {
            primary->kind = KB7_KEY_ACTION_KEYBOARD;
            primary->code = usage;
        } else {
            primary->kind = KB7_KEY_ACTION_NONE;
        }
        for (uint8_t mode = KB7_INPUT_GAME; mode < KB7_INPUT_MODE_COUNT; ++mode) {
            profile->actions[mode][logical].kind = KB7_KEY_ACTION_TRANSPARENT;
        }
    }

    profile->analog.enabled = true;
    profile->analog.output = KB7_ANALOG_LEFT_STICK;
    profile->analog.curve = KB7_ANALOG_LINEAR;
    profile->analog.deadzone = 1U;
    profile->analog.saturation = KB7_HALL_TRAVEL_MAX;
    profile->analog.smoothing = 2U;
    profile->analog.digital_passthrough = true;
    profile->analog.logical_key[KB7_ANALOG_X_NEGATIVE] = 0x27U;
    profile->analog.logical_key[KB7_ANALOG_X_POSITIVE] = 0x4fU;
    profile->analog.logical_key[KB7_ANALOG_Y_NEGATIVE] = 0x3aU;
    profile->analog.logical_key[KB7_ANALOG_Y_POSITIVE] = 0x3bU;
}

bool kb7_input_profile_set_action(struct kb7_input_profile *profile, uint8_t mode,
                                  uint8_t logical_key,
                                  const struct kb7_key_action *action) {
    if (profile == NULL || action == NULL || mode >= KB7_INPUT_MODE_COUNT ||
        logical_key >= KB7_LOGICAL_KEY_COUNT) {
        return false;
    }
    if (logical_key == KB7_FN_LOGICAL_KEY && mode == KB7_INPUT_PRIMARY &&
        action->kind != KB7_KEY_ACTION_MOMENTARY_LAYER) {
        return false;
    }
    switch (action->kind) {
    case KB7_KEY_ACTION_TRANSPARENT:
    case KB7_KEY_ACTION_NONE:
        if (action->code != 0U || action->argument != 0U) return false;
        break;
    case KB7_KEY_ACTION_KEYBOARD:
        if (logical_key == KB7_FN_LOGICAL_KEY ||
            !keyboard_usage_valid(action->code) || action->argument != 0U) return false;
        break;
    case KB7_KEY_ACTION_CONSUMER:
        if (logical_key == KB7_FN_LOGICAL_KEY || action->code == 0U ||
            action->argument != 0U) return false;
        break;
    case KB7_KEY_ACTION_MOMENTARY_LAYER:
        if (logical_key != KB7_FN_LOGICAL_KEY || action->code != 0U ||
            action->argument != KB7_INPUT_FN1) {
            return false;
        }
        break;
    default:
        return false;
    }
    profile->actions[mode][logical_key] = *action;
    return true;
}

bool kb7_input_profile_valid(const struct kb7_input_profile *profile) {
    if (profile == NULL || profile->layout > KB7_LAYOUT_DEFAULT_80_VARIANT_3 ||
        profile->initial_mode >= KB7_INPUT_FN1) {
        return false;
    }
    for (uint8_t logical = 0U; logical < KB7_LOGICAL_KEY_COUNT; ++logical) {
        const struct kb7_hall_config *const hall = &profile->hall[logical];
        if (hall->actuation == 0U || hall->actuation > KB7_HALL_TRAVEL_MAX ||
            hall->rapid_press_delta == 0U ||
            hall->rapid_press_delta > KB7_HALL_TRAVEL_MAX ||
            hall->rapid_release_delta == 0U ||
            hall->rapid_release_delta > KB7_HALL_TRAVEL_MAX) {
            return false;
        }
        for (uint8_t mode = 0U; mode < KB7_INPUT_MODE_COUNT; ++mode) {
            const struct kb7_key_action *const action =
                &profile->actions[mode][logical];
            switch (action->kind) {
            case KB7_KEY_ACTION_TRANSPARENT:
            case KB7_KEY_ACTION_NONE:
                if (action->code != 0U || action->argument != 0U) return false;
                break;
            case KB7_KEY_ACTION_KEYBOARD:
                if (logical == KB7_FN_LOGICAL_KEY ||
                    !keyboard_usage_valid(action->code) || action->argument != 0U) {
                    return false;
                }
                break;
            case KB7_KEY_ACTION_CONSUMER:
                if (logical == KB7_FN_LOGICAL_KEY || action->code == 0U ||
                    action->argument != 0U) return false;
                break;
            case KB7_KEY_ACTION_MOMENTARY_LAYER:
                if (logical != KB7_FN_LOGICAL_KEY || action->code != 0U ||
                    action->argument != KB7_INPUT_FN1) {
                    return false;
                }
                break;
            default:
                return false;
            }
        }
    }
    const struct kb7_key_action *const primary_fn =
        &profile->actions[KB7_INPUT_PRIMARY][KB7_FN_LOGICAL_KEY];
    if (primary_fn->kind != KB7_KEY_ACTION_MOMENTARY_LAYER ||
        primary_fn->argument != KB7_INPUT_FN1) {
        return false;
    }
    const struct kb7_analog_config *const analog = &profile->analog;
    if (analog->output > KB7_ANALOG_TRIGGERS || analog->curve > KB7_ANALOG_S_CURVE ||
        analog->deadzone >= analog->saturation ||
        analog->saturation > KB7_HALL_TRAVEL_MAX || analog->smoothing > 10U) {
        return false;
    }
    for (uint8_t left = 0U; left < KB7_ANALOG_BINDING_COUNT; ++left) {
        if (analog->logical_key[left] >= KB7_LOGICAL_KEY_COUNT) return false;
        for (uint8_t right = (uint8_t)(left + 1U); right < KB7_ANALOG_BINDING_COUNT;
             ++right) {
            if (analog->logical_key[left] == analog->logical_key[right]) return false;
        }
    }
    return true;
}

bool kb7_input_profile_set_hall(struct kb7_input_profile *profile, uint8_t logical_key,
                                const struct kb7_hall_config *config) {
    if (profile == NULL || config == NULL || logical_key >= KB7_LOGICAL_KEY_COUNT ||
        config->actuation == 0U || config->actuation > KB7_HALL_TRAVEL_MAX ||
        config->rapid_press_delta == 0U ||
        config->rapid_press_delta > KB7_HALL_TRAVEL_MAX ||
        config->rapid_release_delta == 0U ||
        config->rapid_release_delta > KB7_HALL_TRAVEL_MAX) {
        return false;
    }
    profile->hall[logical_key] = *config;
    return true;
}

void kb7_input_profile_set_global_hall(struct kb7_input_profile *profile,
                                       const struct kb7_hall_config *config) {
    if (profile == NULL || config == NULL) return;
    const struct kb7_hall_config safe = sanitized_hall(config);
    for (uint8_t logical = 0U; logical < KB7_LOGICAL_KEY_COUNT; ++logical) {
        profile->hall[logical] = safe;
    }
}

bool kb7_input_profile_set_analog(struct kb7_input_profile *profile,
                                  const struct kb7_analog_config *analog) {
    if (profile == NULL || analog == NULL || analog->output > KB7_ANALOG_TRIGGERS ||
        analog->curve > KB7_ANALOG_S_CURVE || analog->deadzone >= analog->saturation ||
        analog->saturation > KB7_HALL_TRAVEL_MAX || analog->smoothing > 10U) {
        return false;
    }
    for (uint8_t left = 0U; left < KB7_ANALOG_BINDING_COUNT; ++left) {
        if (analog->logical_key[left] >= KB7_LOGICAL_KEY_COUNT) return false;
        for (uint8_t right = (uint8_t)(left + 1U); right < KB7_ANALOG_BINDING_COUNT;
             ++right) {
            if (analog->logical_key[left] == analog->logical_key[right]) return false;
        }
    }
    profile->analog = *analog;
    return true;
}

void kb7_input_reset(struct kb7_input_state *state,
                     const struct kb7_input_profile *profile) {
    if (state == NULL) return;
    kb7_memset(state, 0, sizeof(*state));
    kb7_hall_reset(state->hall);
    if (profile != NULL && profile->initial_mode < KB7_INPUT_FN1) {
        state->mode = profile->initial_mode;
    } else {
        state->mode = KB7_INPUT_PRIMARY;
    }
    state->saved_mode = state->mode;
}

bool kb7_input_set_mode(struct kb7_input_state *state, uint8_t mode) {
    if (state == NULL || mode >= KB7_INPUT_FN1) return false;
    if (state->fn_layer_active) state->saved_mode = mode;
    else state->mode = mode;
    return true;
}

static const struct kb7_key_action *resolved_action(
    const struct kb7_input_profile *profile, uint8_t mode, uint8_t logical) {
    const struct kb7_key_action *action = &profile->actions[mode][logical];
    if (action->kind == KB7_KEY_ACTION_TRANSPARENT && mode != KB7_INPUT_PRIMARY) {
        action = &profile->actions[KB7_INPUT_PRIMARY][logical];
    }
    return action;
}

static bool is_analog_binding(const struct kb7_analog_config *analog, uint8_t logical) {
    for (uint8_t index = 0U; index < KB7_ANALOG_BINDING_COUNT; ++index) {
        if (analog->logical_key[index] == logical) return true;
    }
    return false;
}

static int32_t analog_magnitude(uint8_t travel, const struct kb7_analog_config *analog) {
    uint8_t deadzone = analog->deadzone;
    uint8_t saturation = analog->saturation;
    if (saturation > KB7_HALL_TRAVEL_MAX) saturation = KB7_HALL_TRAVEL_MAX;
    if (deadzone >= saturation || travel <= deadzone) return 0;
    if (travel >= saturation) return 32767;
    const uint32_t position = (uint32_t)travel - deadzone;
    const uint32_t span = (uint32_t)saturation - deadzone;
    if (analog->curve == KB7_ANALOG_EXPONENTIAL) {
        return (int32_t)((position * position * UINT32_C(32767)) / (span * span));
    }
    if (analog->curve == KB7_ANALOG_S_CURVE) {
        const uint32_t numerator = position * position * (3U * span - 2U * position);
        return (int32_t)((numerator * UINT32_C(32767)) / (span * span * span));
    }
    return (int32_t)((position * UINT32_C(32767)) / span);
}

static int32_t smooth_axis(int32_t previous, int32_t target, uint8_t smoothing) {
    if (smoothing == 0U) return target;
    if (smoothing > 10U) smoothing = 10U;
    const int32_t delta = target - previous;
    int32_t step = delta / (int32_t)(smoothing + 1U);
    if (step == 0 && delta != 0) step = delta > 0 ? 1 : -1;
    return previous + step;
}

static uint8_t logical_travel(const uint8_t values[KB7_LOGICAL_KEY_COUNT], uint8_t logical) {
    return logical < KB7_LOGICAL_KEY_COUNT ? values[logical] : 0U;
}

static uint8_t trigger_value(int32_t magnitude) {
    if (magnitude <= 0) return 0U;
    if (magnitude >= 32767) return 255U;
    return (uint8_t)(((uint32_t)magnitude * 255U) / 32767U);
}

static void build_gamepad(struct kb7_input_state *state,
                          const struct kb7_analog_config *analog,
                          const uint8_t values[KB7_LOGICAL_KEY_COUNT],
                          struct kb7_gamepad_report *report) {
    kb7_memset(report, 0, sizeof(*report));
    report->report_id = KB7_GAMEPAD_REPORT_ID;
    report->hat = 0x0fU;
    if (!analog->enabled) return;

    const int32_t negative_x = analog_magnitude(logical_travel(
        values, analog->logical_key[KB7_ANALOG_X_NEGATIVE]), analog);
    const int32_t positive_x = analog_magnitude(logical_travel(
        values, analog->logical_key[KB7_ANALOG_X_POSITIVE]), analog);
    const int32_t negative_y = analog_magnitude(logical_travel(
        values, analog->logical_key[KB7_ANALOG_Y_NEGATIVE]), analog);
    const int32_t positive_y = analog_magnitude(logical_travel(
        values, analog->logical_key[KB7_ANALOG_Y_POSITIVE]), analog);
    int32_t target_x = positive_x - negative_x;
    int32_t target_y = positive_y - negative_y;
    if (analog->invert_x) target_x = -target_x;
    if (analog->invert_y) target_y = -target_y;

    if (!state->analog_initialized) {
        state->filtered_x = 0;
        state->filtered_y = 0;
        state->analog_initialized = true;
    }
    state->filtered_x = smooth_axis(state->filtered_x, target_x, analog->smoothing);
    state->filtered_y = smooth_axis(state->filtered_y, target_y, analog->smoothing);

    if (analog->output == KB7_ANALOG_LEFT_STICK) {
        report->left_x = (int16_t)state->filtered_x;
        report->left_y = (int16_t)state->filtered_y;
    } else if (analog->output == KB7_ANALOG_RIGHT_STICK) {
        report->right_x = (int16_t)state->filtered_x;
        report->right_y = (int16_t)state->filtered_y;
    } else if (analog->output == KB7_ANALOG_TRIGGERS) {
        /* Four directional bindings remain useful: either negative/positive
         * member of an axis can drive its corresponding trigger. */
        const int32_t left = negative_x > negative_y ? negative_x : negative_y;
        const int32_t right = positive_x > positive_y ? positive_x : positive_y;
        report->left_trigger = trigger_value(left);
        report->right_trigger = trigger_value(right);
    }
}

void kb7_input_process(struct kb7_input_state *state,
                       const struct kb7_input_profile *profile,
                       const uint8_t raw[KB7_HALL_KEY_COUNT],
                       struct kb7_input_frame *frame) {
    if (state == NULL || profile == NULL || raw == NULL || frame == NULL) return;
    kb7_memset(frame, 0, sizeof(*frame));
    kb7_memset(state->logical_pressed, 0, sizeof(state->logical_pressed));
    uint8_t logical_values[KB7_LOGICAL_KEY_COUNT];
    kb7_memset(logical_values, 0, sizeof(logical_values));

    for (uint8_t sensor = 0U; sensor < KB7_HALL_KEY_COUNT; ++sensor) {
        const uint8_t travel = kb7_hall_raw_to_travel(raw[sensor]);
        frame->travel[sensor] = travel;
        uint8_t logical;
        if (!kb7_keymap_route(sensor, profile->layout, &logical) ||
            logical >= KB7_LOGICAL_KEY_COUNT) {
            continue;
        }
        logical_values[logical] = travel;
        const struct kb7_hall_config hall = sanitized_hall(&profile->hall[logical]);
        if (kb7_hall_update(&state->hall[sensor], travel, &hall)) {
            state->logical_pressed[logical] = true;
        }
    }

    const bool fn_pressed = state->logical_pressed[KB7_FN_LOGICAL_KEY];
    if (fn_pressed && !state->fn_down) {
        const uint8_t base_mode = state->mode < KB7_INPUT_FN1
                                      ? state->mode : KB7_INPUT_PRIMARY;
        const struct kb7_key_action *const fn_action =
            resolved_action(profile, base_mode, KB7_FN_LOGICAL_KEY);
        if (fn_action->kind == KB7_KEY_ACTION_MOMENTARY_LAYER &&
            fn_action->argument == KB7_INPUT_FN1) {
            state->saved_mode = base_mode;
            state->mode = KB7_INPUT_FN1;
            state->fn_layer_active = true;
        } else {
            state->fn_layer_active = false;
        }
    } else if (!fn_pressed && state->fn_down) {
        if (state->fn_layer_active) {
            state->mode = state->saved_mode < KB7_INPUT_FN1
                              ? state->saved_mode : KB7_INPUT_PRIMARY;
        }
        state->fn_layer_active = false;
    }
    state->fn_down = fn_pressed;
    if (state->mode >= KB7_INPUT_MODE_COUNT) state->mode = KB7_INPUT_PRIMARY;

    for (uint8_t logical = 0U; logical < KB7_LOGICAL_KEY_COUNT; ++logical) {
        if (!state->logical_pressed[logical]) continue;
        const struct kb7_key_action *const action =
            resolved_action(profile, state->mode, logical);
        if (action->kind == KB7_KEY_ACTION_MOMENTARY_LAYER ||
            action->kind == KB7_KEY_ACTION_NONE ||
            action->kind == KB7_KEY_ACTION_TRANSPARENT) {
            continue;
        }
        if (profile->analog.enabled && !profile->analog.digital_passthrough &&
            is_analog_binding(&profile->analog, logical)) {
            continue;
        }
        if (action->kind == KB7_KEY_ACTION_CONSUMER) {
            if (frame->consumer_usage == 0U) frame->consumer_usage = action->code;
            continue;
        }
        if (action->kind != KB7_KEY_ACTION_KEYBOARD) continue;
        const uint16_t usage = action->code;
        if (usage >= 0xe0U && usage <= 0xe7U) {
            frame->modifiers |= (uint8_t)KB7_BIT(usage - 0xe0U);
        } else if (usage > 0U && usage < KB7_KEYBOARD_USAGE_BITS) {
            frame->keyboard_bits[usage >> 3U] |= (uint8_t)KB7_BIT(usage & 7U);
        }
    }
    build_gamepad(state, &profile->analog, logical_values, &frame->gamepad);
}

bool kb7_input_link_should_neutralize(struct kb7_input_link_guard *guard,
                                      bool sample_valid) {
    if (guard == NULL) return false;
    if (sample_valid) {
        guard->consecutive_failures = 0U;
        guard->neutralized = false;
        return false;
    }
    if (guard->consecutive_failures < KB7_INPUT_LINK_FAILURE_LIMIT) {
        ++guard->consecutive_failures;
    }
    if (guard->consecutive_failures < KB7_INPUT_LINK_FAILURE_LIMIT ||
        guard->neutralized) {
        return false;
    }
    guard->neutralized = true;
    return true;
}
