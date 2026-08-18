#include "kb7/input.h"

/*
 * Clean-room transcription of the V1.22 default logical usage sequence.  The
 * sequence agrees with all 77 independently observed ANSI key events.  Values
 * 0x87..0x8b are standard HID international/language usages; 0xf1 is the
 * firmware's internal Fn token and is deliberately rejected by HID lookup.
 */
static const uint8_t default_usage[KB7_LOGICAL_KEY_COUNT] = {
    0x29U, 0x1fU, 0x39U, 0x64U, 0x3bU, 0x21U, 0x07U, 0x06U,
    0x3eU, 0x25U, 0x0cU, 0x05U, 0x40U, 0x27U, 0x0fU, 0x37U,
    0x43U, 0x2aU, 0x28U, 0xe4U, 0x3aU, 0x2bU, 0x04U, 0x1dU,
    0x3cU, 0x22U, 0x09U, 0x19U, 0x3fU, 0x17U, 0x0bU, 0x11U,
    0x41U, 0x2dU, 0x33U, 0x38U, 0x44U, 0x2fU, 0xe5U, 0x50U,
    0x35U, 0x14U, 0x16U, 0xe0U, 0x3dU, 0x08U, 0x0aU, 0xe2U,
    0x23U, 0x1cU, 0x0dU, 0x10U, 0x42U, 0x12U, 0x34U, 0xe6U,
    0x45U, 0x30U, 0x52U, 0x51U, 0x1eU, 0x1aU, 0xe1U, 0xe3U,
    0x20U, 0x15U, 0x1bU, 0x2cU, 0x24U, 0x18U, 0x0eU, 0x36U,
    0x26U, 0x13U, 0x32U, 0x65U, 0x2eU, 0x31U, KB7_INTERNAL_USAGE_FN, 0x4fU,
    0x8aU, 0x87U, 0x8bU, 0x88U, 0x89U,
};

_Static_assert(KB7_ARRAY_LEN(default_usage) == KB7_LOGICAL_KEY_COUNT,
               "logical usage table size changed");

bool kb7_keymap_route(uint8_t sensor, uint8_t layout, uint8_t *logical_key) {
    if (logical_key == NULL) return false;
    if (layout == KB7_LAYOUT_DEFAULT_80 ||
        layout == KB7_LAYOUT_DEFAULT_80_VARIANT_2 ||
        layout == KB7_LAYOUT_DEFAULT_80_VARIANT_3) {
        if (sensor >= 80U) return false;
        *logical_key = sensor;
        return true;
    }
    if (layout != KB7_LAYOUT_ALTERNATE_82 || sensor >= KB7_HALL_KEY_COUNT) {
        return false;
    }
    switch (sensor) {
    case 0x03U:
        *logical_key = 0x52U;
        break;
    case 0x37U:
        *logical_key = 0x53U;
        break;
    case 0x4dU:
        *logical_key = 0x54U;
        break;
    default:
        *logical_key = sensor;
        break;
    }
    return true;
}

bool kb7_keymap_default_usage(uint8_t logical_key, uint8_t *usage) {
    if (usage == NULL || logical_key >= KB7_LOGICAL_KEY_COUNT) return false;
    *usage = default_usage[logical_key];
    return true;
}

bool kb7_keymap_lookup_layout(uint8_t sensor, uint8_t layout,
                              struct kb7_hid_binding *binding) {
    if (binding == NULL) return false;
    binding->usage = 0U;
    binding->modifier_mask = 0U;
    uint8_t logical_key;
    uint8_t usage;
    if (!kb7_keymap_route(sensor, layout, &logical_key) ||
        !kb7_keymap_default_usage(logical_key, &usage) ||
        usage == 0U || usage == KB7_INTERNAL_USAGE_FN) {
        return false;
    }
    if (usage >= 0xe0U && usage <= 0xe7U) {
        binding->modifier_mask = (uint8_t)KB7_BIT(usage - 0xe0U);
        return true;
    }
    if (usage >= KB7_KEYBOARD_USAGE_BITS) return false;
    binding->usage = usage;
    return true;
}

bool kb7_keymap_lookup(uint8_t sensor, struct kb7_hid_binding *binding) {
    return kb7_keymap_lookup_layout(sensor, KB7_LAYOUT_DEFAULT_80, binding);
}
