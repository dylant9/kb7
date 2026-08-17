#ifndef KB7_SCREEN_H
#define KB7_SCREEN_H

#include "kb7/platform.h"

#define KB7_SCREEN_MAGIC UINT32_C(0x3153424b) /* KBS1 */
#define KB7_SCREEN_VERSION 1U
#define KB7_SCREEN_HEADER_SIZE 48U
#define KB7_SCREEN_MAX_SCREENS 16U
#define KB7_SCREEN_MAX_WIDGETS 128U

enum kb7_widget_type {
    KB7_WIDGET_LABEL = 1,
    KB7_WIDGET_BUTTON = 2,
    KB7_WIDGET_SLIDER = 3,
    KB7_WIDGET_TOGGLE = 4,
    KB7_WIDGET_GAUGE = 5,
};

enum kb7_action_opcode {
    KB7_ACTION_NONE = 0x00,
    KB7_ACTION_NAVIGATE = 0x01,
    KB7_ACTION_RGB_COLOR = 0x10,
    KB7_ACTION_RGB_EFFECT = 0x11,
    KB7_ACTION_BRIGHTNESS = 0x12,
    KB7_ACTION_PROFILE = 0x20,
    KB7_ACTION_ACTUATION = 0x21,
    KB7_ACTION_RAPID_TRIGGER = 0x22,
    KB7_ACTION_HID_KEY = 0x30,
    KB7_ACTION_MEDIA_KEY = 0x31,
    KB7_ACTION_HOST_EVENT = 0x40,
};

struct KB7_PACKED kb7_screen_header {
    uint32_t magic;
    uint16_t version;
    uint16_t header_length;
    uint32_t total_length;
    uint32_t body_crc32;
    uint16_t screen_count;
    uint16_t boot_screen;
    uint16_t widget_count;
    uint16_t flags;
    uint32_t screens_offset;
    uint32_t widgets_offset;
    uint32_t strings_offset;
    uint32_t strings_length;
    uint32_t format_features;
    uint32_t reserved;
};

struct KB7_PACKED kb7_screen_record {
    uint16_t id;
    uint16_t first_widget;
    uint16_t widget_count;
    uint16_t background_rgb565;
    uint32_t name_offset;
    uint16_t name_length;
    uint16_t flags;
};

struct KB7_PACKED kb7_widget_record {
    uint16_t id;
    uint8_t type;
    uint8_t flags;
    int16_t x;
    int16_t y;
    int16_t width;
    int16_t height;
    uint16_t foreground_rgb565;
    uint16_t background_rgb565;
    int16_t minimum;
    int16_t maximum;
    int16_t value;
    uint16_t target_screen;
    uint8_t action;
    uint8_t action_flags;
    uint16_t action_arg0;
    uint32_t action_arg1;
    uint32_t text_offset;
    uint16_t text_length;
    uint16_t reserved;
};

struct kb7_screen_store {
    const uint8_t *bytes;
    size_t length;
    const struct kb7_screen_header *header;
};

enum kb7_screen_error {
    KB7_SCREEN_VALID = 0,
    KB7_SCREEN_TRUNCATED,
    KB7_SCREEN_MAGIC_ERROR,
    KB7_SCREEN_VERSION_ERROR,
    KB7_SCREEN_LAYOUT_ERROR,
    KB7_SCREEN_CRC_ERROR,
    KB7_SCREEN_LIMIT_ERROR,
};

enum kb7_screen_error kb7_screen_parse(const void *bytes, size_t length,
                                        struct kb7_screen_store *store);
const struct kb7_screen_record *kb7_screen_find(const struct kb7_screen_store *store,
                                                uint16_t id);
const struct kb7_widget_record *kb7_screen_widget(const struct kb7_screen_store *store,
                                                  uint16_t index);
bool kb7_screen_text(const struct kb7_screen_store *store, uint32_t offset,
                     uint16_t length, const char **text);

#endif
