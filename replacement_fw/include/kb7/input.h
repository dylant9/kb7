#ifndef KB7_INPUT_H
#define KB7_INPUT_H

#include "kb7/drivers.h"

#define KB7_LOGICAL_KEY_COUNT 85U
#define KB7_HALL_TRAVEL_MAX 32U
#define KB7_FN_LOGICAL_KEY 0x4eU
#define KB7_INTERNAL_USAGE_FN 0xf1U

#define KB7_GAMEPAD_REPORT_ID 0x07U
#define KB7_GAMEPAD_REPORT_BYTES 14U
#define KB7_INPUT_LINK_FAILURE_LIMIT 3U

enum kb7_layout_variant {
    KB7_LAYOUT_DEFAULT_80 = 0,
    KB7_LAYOUT_ALTERNATE_82 = 1,
    /* Stock variant-field values 2 and 3 take the same 80-route branch as 0. */
    KB7_LAYOUT_DEFAULT_80_VARIANT_2 = 2,
    KB7_LAYOUT_DEFAULT_80_VARIANT_3 = 3,
};

enum kb7_input_mode {
    KB7_INPUT_PRIMARY = 0,
    KB7_INPUT_GAME = 1,
    KB7_INPUT_EASY_SHIFT = 2,
    KB7_INPUT_FN1 = 3,
    KB7_INPUT_MODE_COUNT = 4,
};

enum kb7_key_action_kind {
    KB7_KEY_ACTION_TRANSPARENT = 0,
    KB7_KEY_ACTION_NONE = 1,
    KB7_KEY_ACTION_KEYBOARD = 2,
    KB7_KEY_ACTION_CONSUMER = 3,
    KB7_KEY_ACTION_MOMENTARY_LAYER = 4,
};

enum kb7_analog_curve {
    KB7_ANALOG_LINEAR = 0,
    KB7_ANALOG_EXPONENTIAL = 1,
    KB7_ANALOG_S_CURVE = 2,
};

enum kb7_analog_output {
    KB7_ANALOG_LEFT_STICK = 0,
    KB7_ANALOG_RIGHT_STICK = 1,
    KB7_ANALOG_TRIGGERS = 2,
};

enum kb7_analog_binding {
    KB7_ANALOG_X_NEGATIVE = 0,
    KB7_ANALOG_X_POSITIVE = 1,
    KB7_ANALOG_Y_NEGATIVE = 2,
    KB7_ANALOG_Y_POSITIVE = 3,
    KB7_ANALOG_BINDING_COUNT = 4,
};

struct kb7_key_action {
    uint16_t code;
    uint8_t kind;
    uint8_t argument;
};

_Static_assert(sizeof(struct kb7_key_action) == 4U,
               "action records must remain four bytes");
_Static_assert(sizeof(struct kb7_hall_config) == 4U,
               "per-key Hall records must remain four bytes");

struct kb7_analog_config {
    bool enabled;
    uint8_t output;
    uint8_t curve;
    uint8_t deadzone;
    uint8_t saturation;
    uint8_t smoothing;
    bool invert_x;
    bool invert_y;
    bool digital_passthrough;
    uint8_t logical_key[KB7_ANALOG_BINDING_COUNT];
};

struct kb7_input_profile {
    uint8_t layout;
    uint8_t initial_mode;
    struct kb7_hall_config hall[KB7_LOGICAL_KEY_COUNT];
    struct kb7_key_action actions[KB7_INPUT_MODE_COUNT][KB7_LOGICAL_KEY_COUNT];
    struct kb7_analog_config analog;
};

struct kb7_gamepad_report {
    uint8_t report_id;
    uint16_t buttons;
    uint8_t hat;
    int16_t left_x;
    int16_t left_y;
    int16_t right_x;
    int16_t right_y;
    uint8_t left_trigger;
    uint8_t right_trigger;
} KB7_PACKED;

_Static_assert(sizeof(struct kb7_gamepad_report) == KB7_GAMEPAD_REPORT_BYTES,
               "gamepad wire report size changed");

struct kb7_input_state {
    struct kb7_hall_state hall[KB7_HALL_KEY_COUNT];
    bool logical_pressed[KB7_LOGICAL_KEY_COUNT];
    bool fn_down;
    bool fn_layer_active;
    bool analog_initialized;
    uint8_t mode;
    uint8_t saved_mode;
    int32_t filtered_x;
    int32_t filtered_y;
};

struct kb7_input_frame {
    uint8_t keyboard_bits[19];
    uint8_t modifiers;
    uint16_t consumer_usage;
    uint8_t travel[KB7_HALL_KEY_COUNT];
    struct kb7_gamepad_report gamepad;
};

struct kb7_input_link_guard {
    uint8_t consecutive_failures;
    bool neutralized;
};

/* Exact V1.22 routing and default-usage model, expressed as clean C data. */
bool kb7_keymap_route(uint8_t sensor, uint8_t layout, uint8_t *logical_key);
bool kb7_keymap_default_usage(uint8_t logical_key, uint8_t *usage);
bool kb7_keymap_lookup_layout(uint8_t sensor, uint8_t layout,
                              struct kb7_hid_binding *binding);

/* Convert MCU2 A3 wire polarity/range to the stock 0..3.2 mm representation. */
uint8_t kb7_hall_raw_to_travel(uint8_t raw);

void kb7_input_profile_default(struct kb7_input_profile *profile);
bool kb7_input_profile_valid(const struct kb7_input_profile *profile);
bool kb7_input_profile_set_action(struct kb7_input_profile *profile, uint8_t mode,
                                  uint8_t logical_key,
                                  const struct kb7_key_action *action);
bool kb7_input_profile_set_hall(struct kb7_input_profile *profile, uint8_t logical_key,
                                const struct kb7_hall_config *config);
void kb7_input_profile_set_global_hall(struct kb7_input_profile *profile,
                                       const struct kb7_hall_config *config);
bool kb7_input_profile_set_analog(struct kb7_input_profile *profile,
                                  const struct kb7_analog_config *analog);
void kb7_input_reset(struct kb7_input_state *state,
                     const struct kb7_input_profile *profile);
bool kb7_input_set_mode(struct kb7_input_state *state, uint8_t mode);
void kb7_input_process(struct kb7_input_state *state,
                       const struct kb7_input_profile *profile,
                       const uint8_t raw[KB7_HALL_KEY_COUNT],
                       struct kb7_input_frame *frame);

/* Returns true exactly once when persistent transport loss requires a neutral
 * physical-input report. A later valid sample rearms the guard. */
bool kb7_input_link_should_neutralize(struct kb7_input_link_guard *guard,
                                      bool sample_valid);

#endif
