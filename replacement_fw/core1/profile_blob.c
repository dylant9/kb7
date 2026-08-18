#include "kb7/profile_blob.h"

struct KB7_PACKED kb7_profile_header_wire {
    uint32_t magic;
    uint16_t version;
    uint16_t header_length;
    uint32_t total_length;
    uint32_t body_crc32;
    uint8_t profile_count;
    uint8_t active_profile;
    uint16_t record_size;
    uint32_t records_offset;
    uint32_t flags;
    uint8_t reserved[20];
};

struct KB7_PACKED kb7_lighting_wire {
    uint8_t enabled;
    uint8_t effect;
    uint8_t brightness;
    uint8_t speed;
    uint8_t direction;
    uint8_t primary[3];
    uint8_t secondary[3];
    uint8_t reactive[3];
};

struct KB7_PACKED kb7_hall_wire {
    uint8_t actuation;
    uint8_t rapid_press_delta;
    uint8_t rapid_release_delta;
    uint8_t flags;
};

struct KB7_PACKED kb7_action_wire {
    uint16_t code;
    uint8_t kind;
    uint8_t argument;
};

struct KB7_PACKED kb7_analog_wire {
    uint8_t enabled;
    uint8_t output;
    uint8_t curve;
    uint8_t deadzone;
    uint8_t saturation;
    uint8_t smoothing;
    uint8_t flags;
    uint8_t logical_key[KB7_ANALOG_BINDING_COUNT];
    uint8_t reserved;
};

struct KB7_PACKED kb7_profile_record_wire {
    uint8_t name[64];
    uint8_t layout;
    uint8_t initial_mode;
    struct kb7_lighting_wire lighting;
    struct kb7_hall_wire hall[KB7_LOGICAL_KEY_COUNT];
    struct kb7_action_wire actions[KB7_INPUT_MODE_COUNT][KB7_LOGICAL_KEY_COUNT];
    struct kb7_analog_wire analog;
};

_Static_assert(sizeof(struct kb7_profile_header_wire) == KB7_PROFILE_HEADER_SIZE,
               "profile header wire size changed");
_Static_assert(sizeof(struct kb7_profile_record_wire) == KB7_PROFILE_RECORD_SIZE,
               "profile record wire size changed");

static bool bytes_zero(const uint8_t *bytes, size_t length) {
    while (length-- != 0U) {
        if (*bytes++ != 0U) return false;
    }
    return true;
}

static bool utf8_name_valid(const uint8_t name[64]) {
    size_t length = 0U;
    while (length < 64U && name[length] != 0U) ++length;
    if (length == 0U || length == 64U || !bytes_zero(name + length, 64U - length)) {
        return false;
    }
    size_t index = 0U;
    while (index < length) {
        const uint8_t first = name[index++];
        uint8_t continuation = 0U;
        uint32_t codepoint = 0U;
        if (first < 0x80U) continue;
        if (first >= 0xc2U && first <= 0xdfU) {
            continuation = 1U;
            codepoint = first & 0x1fU;
        } else if (first >= 0xe0U && first <= 0xefU) {
            continuation = 2U;
            codepoint = first & 0x0fU;
        } else if (first >= 0xf0U && first <= 0xf4U) {
            continuation = 3U;
            codepoint = first & 0x07U;
        } else {
            return false;
        }
        if ((size_t)continuation > length - index) return false;
        for (uint8_t count = 0U; count < continuation; ++count) {
            const uint8_t next = name[index++];
            if ((next & 0xc0U) != 0x80U) return false;
            codepoint = (codepoint << 6U) | (next & 0x3fU);
        }
        if ((continuation == 1U && codepoint < 0x80U) ||
            (continuation == 2U && codepoint < 0x800U) ||
            (continuation == 3U && codepoint < 0x10000U) ||
            codepoint > 0x10ffffU ||
            (codepoint >= 0xd800U && codepoint <= 0xdfffU)) {
            return false;
        }
    }
    return true;
}

static bool lighting_valid(const struct kb7_lighting_wire *wire) {
    return wire->enabled <= 1U && wire->effect <= KB7_LIGHTING_HEATMAP &&
           wire->brightness <= 100U && wire->speed <= 100U &&
           wire->direction <= KB7_LIGHTING_RADIAL;
}

static void copy_lighting(const struct kb7_lighting_wire *wire,
                          struct kb7_lighting_profile *lighting) {
    lighting->enabled = wire->enabled != 0U;
    lighting->effect = wire->effect;
    lighting->brightness = wire->brightness;
    lighting->speed = wire->speed;
    lighting->direction = wire->direction;
    lighting->primary = (struct kb7_rgb){wire->primary[0], wire->primary[1], wire->primary[2]};
    lighting->secondary =
        (struct kb7_rgb){wire->secondary[0], wire->secondary[1], wire->secondary[2]};
    lighting->reactive =
        (struct kb7_rgb){wire->reactive[0], wire->reactive[1], wire->reactive[2]};
}

static bool decode_record(const struct kb7_profile_record_wire *wire,
                          struct kb7_input_profile *profile,
                          struct kb7_lighting_profile *lighting,
                          uint8_t name[64]) {
    if (!utf8_name_valid(wire->name) || !lighting_valid(&wire->lighting) ||
        wire->analog.enabled > 1U || (wire->analog.flags & ~UINT8_C(0x07)) != 0U ||
        wire->analog.reserved != 0U) {
        return false;
    }
    kb7_memset(profile, 0, sizeof(*profile));
    profile->layout = wire->layout;
    profile->initial_mode = wire->initial_mode;
    for (uint8_t logical = 0U; logical < KB7_LOGICAL_KEY_COUNT; ++logical) {
        const struct kb7_hall_wire *const source = &wire->hall[logical];
        if ((source->flags & ~UINT8_C(0x01)) != 0U) return false;
        profile->hall[logical] = (struct kb7_hall_config){
            source->actuation,
            source->rapid_press_delta,
            source->rapid_release_delta,
            (source->flags & 1U) != 0U,
        };
        for (uint8_t mode = 0U; mode < KB7_INPUT_MODE_COUNT; ++mode) {
            const struct kb7_action_wire *const action = &wire->actions[mode][logical];
            profile->actions[mode][logical] =
                (struct kb7_key_action){action->code, action->kind, action->argument};
        }
    }
    profile->analog.enabled = wire->analog.enabled != 0U;
    profile->analog.output = wire->analog.output;
    profile->analog.curve = wire->analog.curve;
    profile->analog.deadzone = wire->analog.deadzone;
    profile->analog.saturation = wire->analog.saturation;
    profile->analog.smoothing = wire->analog.smoothing;
    profile->analog.invert_x = (wire->analog.flags & 1U) != 0U;
    profile->analog.invert_y = (wire->analog.flags & 2U) != 0U;
    profile->analog.digital_passthrough = (wire->analog.flags & 4U) != 0U;
    kb7_memcpy(profile->analog.logical_key, wire->analog.logical_key,
               sizeof(profile->analog.logical_key));
    if (!kb7_input_profile_valid(profile)) return false;
    copy_lighting(&wire->lighting, lighting);
    kb7_memcpy(name, wire->name, 64U);
    return true;
}

static enum kb7_profile_validation parse_blob(const void *data, size_t length,
                                              struct kb7_profile_store *store) {
    if (data == NULL || length < KB7_PROFILE_HEADER_SIZE) {
        return KB7_PROFILE_TRUNCATED;
    }
    const struct kb7_profile_header_wire *const header = data;
    if (header->magic != KB7_PROFILE_MAGIC || header->version != KB7_PROFILE_VERSION ||
        header->header_length != KB7_PROFILE_HEADER_SIZE ||
        header->records_offset != KB7_PROFILE_HEADER_SIZE || header->flags != 0U ||
        !bytes_zero(header->reserved, sizeof(header->reserved)) ||
        header->profile_count == 0U ||
        header->profile_count > KB7_INPUT_PROFILE_SLOT_COUNT ||
        header->active_profile >= header->profile_count ||
        header->record_size != KB7_PROFILE_RECORD_SIZE) {
        return KB7_PROFILE_BAD_HEADER;
    }
    const uint32_t expected = KB7_PROFILE_HEADER_SIZE +
        (uint32_t)header->profile_count * KB7_PROFILE_RECORD_SIZE;
    if (header->total_length != expected || length != expected) {
        return header->total_length > length ? KB7_PROFILE_TRUNCATED : KB7_PROFILE_BAD_HEADER;
    }
    const uint8_t *const body = (const uint8_t *)data + header->header_length;
    if (kb7_crc32(body, length - header->header_length) != header->body_crc32) {
        return KB7_PROFILE_BAD_CRC;
    }

    for (uint8_t slot = 0U; slot < header->profile_count; ++slot) {
        const struct kb7_profile_record_wire *const record =
            (const struct kb7_profile_record_wire *)(const void *)(
                body + (size_t)slot * KB7_PROFILE_RECORD_SIZE);
        struct kb7_input_profile profile;
        struct kb7_lighting_profile lighting;
        uint8_t name[64];
        if (!decode_record(record, &profile, &lighting, name)) {
            return KB7_PROFILE_BAD_RECORD;
        }
        if (store != NULL) {
            store->input.slot[slot] = profile;
            store->lighting[slot] = lighting;
            kb7_memcpy(store->names[slot], name, sizeof(name));
        }
    }
    if (store != NULL) {
        for (uint8_t slot = header->profile_count; slot < KB7_INPUT_PROFILE_SLOT_COUNT; ++slot) {
            kb7_input_profile_default(&store->input.slot[slot]);
            kb7_memset(&store->lighting[slot], 0, sizeof(store->lighting[slot]));
            kb7_memset(store->names[slot], 0, sizeof(store->names[slot]));
        }
        store->count = header->profile_count;
        store->input.active = header->active_profile;
    }
    return KB7_PROFILE_VALID;
}

enum kb7_profile_validation kb7_profile_validate(const void *data, size_t length) {
    return parse_blob(data, length, NULL);
}

enum kb7_profile_validation kb7_profile_parse(const void *data, size_t length,
                                              struct kb7_profile_store *store) {
    if (store == NULL) return KB7_PROFILE_TRUNCATED;
    return parse_blob(data, length, store);
}
