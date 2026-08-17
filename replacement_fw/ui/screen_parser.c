#include "kb7/screen.h"

_Static_assert(sizeof(struct kb7_screen_header) == KB7_SCREEN_HEADER_SIZE,
               "screen header wire size changed");
_Static_assert(sizeof(struct kb7_screen_record) == 16U, "screen record wire size changed");
_Static_assert(sizeof(struct kb7_widget_record) == 40U, "widget record wire size changed");

static bool range_valid(size_t offset, size_t bytes, size_t total) {
    return offset <= total && bytes <= total - offset;
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
    if (header->total_length < KB7_SCREEN_HEADER_SIZE || header->total_length > length) {
        return KB7_SCREEN_TRUNCATED;
    }
    if (header->screen_count == 0U || header->screen_count > KB7_SCREEN_MAX_SCREENS ||
        header->widget_count > KB7_SCREEN_MAX_WIDGETS) {
        return KB7_SCREEN_LIMIT_ERROR;
    }
    const size_t screen_bytes = (size_t)header->screen_count * sizeof(struct kb7_screen_record);
    const size_t widget_bytes = (size_t)header->widget_count * sizeof(struct kb7_widget_record);
    if (header->screens_offset < header->header_length ||
        !range_valid(header->screens_offset, screen_bytes, header->total_length) ||
        !range_valid(header->widgets_offset, widget_bytes, header->total_length) ||
        !range_valid(header->strings_offset, header->strings_length, header->total_length) ||
        header->screens_offset + screen_bytes > header->widgets_offset ||
        header->widgets_offset + widget_bytes > header->strings_offset) {
        return KB7_SCREEN_LAYOUT_ERROR;
    }
    if (header->body_crc32 != kb7_crc32((const uint8_t *)bytes + header->header_length,
                                        header->total_length - header->header_length)) {
        return KB7_SCREEN_CRC_ERROR;
    }
    const struct kb7_screen_record *screens =
        (const struct kb7_screen_record *)((const uint8_t *)bytes + header->screens_offset);
    bool boot_found = false;
    for (uint16_t index = 0; index < header->screen_count; ++index) {
        const struct kb7_screen_record *screen = &screens[index];
        if (screen->id == header->boot_screen) {
            boot_found = true;
        }
        if ((uint32_t)screen->first_widget + screen->widget_count > header->widget_count ||
            screen->name_offset > header->strings_length ||
            screen->name_length > header->strings_length - screen->name_offset) {
            return KB7_SCREEN_LAYOUT_ERROR;
        }
    }
    if (!boot_found) {
        return KB7_SCREEN_LAYOUT_ERROR;
    }
    const struct kb7_widget_record *widgets =
        (const struct kb7_widget_record *)((const uint8_t *)bytes + header->widgets_offset);
    for (uint16_t index = 0; index < header->widget_count; ++index) {
        const struct kb7_widget_record *widget = &widgets[index];
        if (widget->type < KB7_WIDGET_LABEL || widget->type > KB7_WIDGET_GAUGE ||
            widget->width <= 0 || widget->height <= 0 || widget->x < 0 || widget->y < 0 ||
            (uint32_t)widget->x + (uint32_t)widget->width > 480U ||
            (uint32_t)widget->y + (uint32_t)widget->height > 800U ||
            widget->text_offset > header->strings_length ||
            widget->text_length > header->strings_length - widget->text_offset) {
            return KB7_SCREEN_LAYOUT_ERROR;
        }
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
