#include "kb7/screen.h"
#include "kb7/input_profiles.h"
#include "kb7/reports.h"
#include "kb7/regs.h"

_Static_assert(sizeof(struct kb7_screen_header) == KB7_SCREEN_HEADER_SIZE,
               "screen header wire size changed");
_Static_assert(sizeof(struct kb7_screen_record) == 16U, "screen record wire size changed");
_Static_assert(sizeof(struct kb7_widget_record) == 40U, "widget record wire size changed");

static bool range_valid(size_t offset, size_t bytes, size_t total) {
    return offset <= total && bytes <= total - offset;
}

static bool action_valid(uint8_t action) {
    switch (action) {
    case KB7_ACTION_NONE:
    case KB7_ACTION_NAVIGATE:
    case KB7_ACTION_RGB_COLOR:
    case KB7_ACTION_RGB_EFFECT:
    case KB7_ACTION_BRIGHTNESS:
    case KB7_ACTION_PROFILE:
    case KB7_ACTION_ACTUATION:
    case KB7_ACTION_RAPID_TRIGGER:
    case KB7_ACTION_HID_KEY:
    case KB7_ACTION_MEDIA_KEY:
    case KB7_ACTION_HOST_EVENT:
        return true;
    default:
        return false;
    }
}

static bool action_fields_valid(const struct kb7_widget_record *widget) {
    if (widget->action_flags != 0U ||
        (widget->action != KB7_ACTION_NAVIGATE && widget->target_screen != 0U)) {
        return false;
    }
    switch (widget->action) {
    case KB7_ACTION_NONE:
    case KB7_ACTION_NAVIGATE:
        return widget->action_arg0 == 0U && widget->action_arg1 == 0U;
    case KB7_ACTION_RGB_COLOR:
        return widget->action_arg0 == 0U && widget->action_arg1 <= UINT32_C(0x00ffffff);
    case KB7_ACTION_RGB_EFFECT:
        return widget->action_arg0 <= 4U && widget->action_arg1 == 0U;
    case KB7_ACTION_PROFILE:
        return widget->action_arg0 < KB7_INPUT_PROFILE_SLOT_COUNT &&
               widget->action_arg1 == 0U;
    case KB7_ACTION_BRIGHTNESS:
        return widget->minimum >= 0 && widget->maximum <= 100 &&
               widget->action_arg0 == 0U && widget->action_arg1 == 0U;
    case KB7_ACTION_ACTUATION:
        return widget->minimum >= 0 && widget->maximum <= UINT8_MAX &&
               widget->action_arg0 == 0U && widget->action_arg1 == 0U;
    case KB7_ACTION_RAPID_TRIGGER:
        return widget->minimum >= 0 && widget->maximum <= 1 &&
               widget->action_arg0 <= UINT8_MAX && widget->action_arg1 <= UINT8_MAX;
    case KB7_ACTION_HID_KEY:
        return widget->action_arg0 != 0U &&
               (widget->action_arg0 < KB7_KEYBOARD_USAGE_BITS ||
                (widget->action_arg0 >= 0xe0U && widget->action_arg0 <= 0xe7U)) &&
               widget->action_arg1 == 0U;
    case KB7_ACTION_MEDIA_KEY:
        return widget->action_arg0 != 0U && widget->action_arg1 == 0U;
    case KB7_ACTION_HOST_EVENT:
        return true;
    default:
        return false;
    }
}

static bool utf8_valid(const uint8_t *text, size_t length) {
    size_t index = 0U;
    while (index < length) {
        const uint8_t first = text[index++];
        if (first <= 0x7fU) continue;
        uint32_t codepoint;
        uint8_t continuation;
        uint32_t minimum;
        if (first >= 0xc2U && first <= 0xdfU) {
            codepoint = first & 0x1fU;
            continuation = 1U;
            minimum = 0x80U;
        } else if (first >= 0xe0U && first <= 0xefU) {
            codepoint = first & 0x0fU;
            continuation = 2U;
            minimum = 0x800U;
        } else if (first >= 0xf0U && first <= 0xf4U) {
            codepoint = first & 0x07U;
            continuation = 3U;
            minimum = 0x10000U;
        } else {
            return false;
        }
        if ((size_t)continuation > length - index) return false;
        while (continuation-- != 0U) {
            const uint8_t next = text[index++];
            if ((next & 0xc0U) != 0x80U) return false;
            codepoint = (codepoint << 6U) | (next & 0x3fU);
        }
        if (codepoint < minimum || codepoint > 0x10ffffU ||
            (codepoint >= 0xd800U && codepoint <= 0xdfffU)) {
            return false;
        }
    }
    return true;
}

static bool screen_id_exists(const struct kb7_screen_record *screens, uint16_t count,
                             uint16_t id) {
    for (uint16_t index = 0U; index < count; ++index) {
        if (screens[index].id == id) return true;
    }
    return false;
}

enum kb7_screen_error kb7_screen_parse(const void *bytes, size_t length,
                                        struct kb7_screen_store *store) {
    if (store == NULL) {
        return KB7_SCREEN_LAYOUT_ERROR;
    }
    store->bytes = NULL;
    store->length = 0U;
    store->header = NULL;
    if (bytes == NULL || length < KB7_SCREEN_HEADER_SIZE) {
        return KB7_SCREEN_TRUNCATED;
    }
    const struct kb7_screen_header *header = (const struct kb7_screen_header *)bytes;
    if (header->magic != KB7_SCREEN_MAGIC) {
        return KB7_SCREEN_MAGIC_ERROR;
    }
    if (header->version != KB7_SCREEN_VERSION ||
        header->header_length != KB7_SCREEN_HEADER_SIZE) {
        return KB7_SCREEN_VERSION_ERROR;
    }
    if (header->total_length != length) {
        return KB7_SCREEN_TRUNCATED;
    }
    if (header->screen_count == 0U || header->screen_count > KB7_SCREEN_MAX_SCREENS ||
        header->widget_count > KB7_SCREEN_MAX_WIDGETS) {
        return KB7_SCREEN_LIMIT_ERROR;
    }
    const size_t screen_bytes = (size_t)header->screen_count * sizeof(struct kb7_screen_record);
    const size_t widget_bytes = (size_t)header->widget_count * sizeof(struct kb7_widget_record);
    if (header->flags != 0U || header->format_features != 0U || header->reserved != 0U ||
        header->screens_offset != KB7_SCREEN_HEADER_SIZE ||
        header->widgets_offset != header->screens_offset + screen_bytes ||
        header->strings_offset != header->widgets_offset + widget_bytes ||
        !range_valid(header->strings_offset, header->strings_length, header->total_length) ||
        header->strings_offset + header->strings_length != header->total_length) {
        return KB7_SCREEN_LAYOUT_ERROR;
    }
    if (header->body_crc32 != kb7_crc32((const uint8_t *)bytes + header->header_length,
                                        header->total_length - header->header_length)) {
        return KB7_SCREEN_CRC_ERROR;
    }
    const struct kb7_screen_record *screens =
        (const struct kb7_screen_record *)((const uint8_t *)bytes + header->screens_offset);
    const uint8_t *strings = (const uint8_t *)bytes + header->strings_offset;
    bool boot_found = false;
    uint16_t next_widget = 0U;
    for (uint16_t index = 0; index < header->screen_count; ++index) {
        const struct kb7_screen_record *screen = &screens[index];
        if (screen->id == header->boot_screen) {
            boot_found = true;
        }
        for (uint16_t earlier = 0U; earlier < index; ++earlier) {
            if (screens[earlier].id == screen->id) return KB7_SCREEN_LAYOUT_ERROR;
        }
        if (screen->flags != 0U || screen->first_widget != next_widget ||
            (uint32_t)screen->first_widget + screen->widget_count > header->widget_count ||
            screen->name_offset > header->strings_length ||
            screen->name_length > header->strings_length - screen->name_offset ||
            !utf8_valid(strings + screen->name_offset, screen->name_length)) {
            return KB7_SCREEN_LAYOUT_ERROR;
        }
        next_widget = (uint16_t)(next_widget + screen->widget_count);
    }
    if (!boot_found || next_widget != header->widget_count) {
        return KB7_SCREEN_LAYOUT_ERROR;
    }
    const struct kb7_widget_record *widgets =
        (const struct kb7_widget_record *)((const uint8_t *)bytes + header->widgets_offset);
    for (uint16_t index = 0; index < header->widget_count; ++index) {
        const struct kb7_widget_record *widget = &widgets[index];
        for (uint16_t earlier = 0U; earlier < index; ++earlier) {
            if (widgets[earlier].id == widget->id) return KB7_SCREEN_LAYOUT_ERROR;
        }
        if (widget->type < KB7_WIDGET_LABEL || widget->type > KB7_WIDGET_GAUGE ||
            widget->flags != 0U || !action_valid(widget->action) ||
            !action_fields_valid(widget) || widget->reserved != 0U ||
            widget->width <= 0 || widget->height <= 0 || widget->x < 0 || widget->y < 0 ||
            (uint32_t)widget->x + (uint32_t)widget->width > KB7_DISPLAY_WIDTH ||
            (uint32_t)widget->y + (uint32_t)widget->height > KB7_DISPLAY_HEIGHT ||
            widget->minimum > widget->maximum || widget->value < widget->minimum ||
            widget->value > widget->maximum ||
            widget->text_offset > header->strings_length ||
            widget->text_length > header->strings_length - widget->text_offset ||
            !utf8_valid(strings + widget->text_offset, widget->text_length)) {
            return KB7_SCREEN_LAYOUT_ERROR;
        }
        if (widget->action == KB7_ACTION_NAVIGATE &&
            !screen_id_exists(screens, header->screen_count, widget->target_screen)) {
            return KB7_SCREEN_LAYOUT_ERROR;
        }
    }
    if (!utf8_valid(strings, header->strings_length)) {
        return KB7_SCREEN_LAYOUT_ERROR;
    }
    store->bytes = (const uint8_t *)bytes;
    store->length = header->total_length;
    store->header = header;
    return KB7_SCREEN_VALID;
}

const struct kb7_screen_record *kb7_screen_find(const struct kb7_screen_store *store,
                                                uint16_t id) {
    if (store == NULL || store->header == NULL) {
        return NULL;
    }
    const struct kb7_screen_record *screens = (const struct kb7_screen_record *)(
        store->bytes + store->header->screens_offset);
    for (uint16_t index = 0; index < store->header->screen_count; ++index) {
        if (screens[index].id == id) {
            return &screens[index];
        }
    }
    return NULL;
}

const struct kb7_widget_record *kb7_screen_widget(const struct kb7_screen_store *store,
                                                  uint16_t index) {
    if (store == NULL || store->header == NULL || index >= store->header->widget_count) {
        return NULL;
    }
    const struct kb7_widget_record *widgets = (const struct kb7_widget_record *)(
        store->bytes + store->header->widgets_offset);
    return &widgets[index];
}

bool kb7_screen_text(const struct kb7_screen_store *store, uint32_t offset,
                     uint16_t length, const char **text) {
    if (store == NULL || store->header == NULL || text == NULL ||
        offset > store->header->strings_length ||
        length > store->header->strings_length - offset) {
        return false;
    }
    *text = (const char *)(store->bytes + store->header->strings_offset + offset);
    return true;
}
