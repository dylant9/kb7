#ifndef KB7_PROFILE_BLOB_H
#define KB7_PROFILE_BLOB_H

#include "kb7/input_profiles.h"

#define KB7_PROFILE_MAGIC UINT32_C(0x3150424b) /* KBP1 */
#define KB7_PROFILE_VERSION 1U
#define KB7_PROFILE_HEADER_SIZE 48U
#define KB7_PROFILE_RECORD_SIZE 1792U
#define KB7_PROFILE_MIN_SIZE (KB7_PROFILE_HEADER_SIZE + KB7_PROFILE_RECORD_SIZE)
#define KB7_PROFILE_MAX_SIZE \
    (KB7_PROFILE_HEADER_SIZE + KB7_INPUT_PROFILE_SLOT_COUNT * KB7_PROFILE_RECORD_SIZE)

enum kb7_lighting_effect {
    KB7_LIGHTING_STATIC = 0,
    KB7_LIGHTING_GRADIENT = 1,
    KB7_LIGHTING_AURORA = 2,
    KB7_LIGHTING_REACTIVE = 3,
    KB7_LIGHTING_HEATMAP = 4,
};

enum kb7_lighting_direction {
    KB7_LIGHTING_EAST = 0,
    KB7_LIGHTING_WEST = 1,
    KB7_LIGHTING_NORTH = 2,
    KB7_LIGHTING_SOUTH = 3,
    KB7_LIGHTING_RADIAL = 4,
};

struct kb7_lighting_profile {
    bool enabled;
    uint8_t effect;
    uint8_t brightness;
    uint8_t speed;
    uint8_t direction;
    struct kb7_rgb primary;
    struct kb7_rgb secondary;
    struct kb7_rgb reactive;
};

struct kb7_profile_store {
    struct kb7_input_profile_bank input;
    struct kb7_lighting_profile lighting[KB7_INPUT_PROFILE_SLOT_COUNT];
    uint8_t names[KB7_INPUT_PROFILE_SLOT_COUNT][64];
    uint8_t count;
};

enum kb7_profile_validation {
    KB7_PROFILE_VALID = 0,
    KB7_PROFILE_TRUNCATED,
    KB7_PROFILE_BAD_HEADER,
    KB7_PROFILE_BAD_CRC,
    KB7_PROFILE_BAD_RECORD,
};

enum kb7_profile_validation kb7_profile_parse(const void *data, size_t length,
                                              struct kb7_profile_store *store);
enum kb7_profile_validation kb7_profile_validate(const void *data, size_t length);

#endif
