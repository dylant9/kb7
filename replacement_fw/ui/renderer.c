#include "kb7/regs.h"
#include "kb7/ui.h"

static uintptr_t target;
static const struct kb7_screen_store *screen_store;
static kb7_action_handler_t handle_action;
static uint16_t active_screen;
static uint16_t active_widget;
static int16_t widget_values[KB7_SCREEN_MAX_WIDGETS];

#define KB7_NO_ACTIVE_WIDGET UINT16_C(0xffff)

static void release_active_widget(void);

static void pixel(int16_t x, int16_t y, uint16_t color) {
    if (x >= 0 && y >= 0 && x < (int16_t)KB7_DISPLAY_WIDTH && y < (int16_t)KB7_DISPLAY_HEIGHT) {
        volatile uint16_t *framebuffer = (volatile uint16_t *)target;
        framebuffer[(uint32_t)y * KB7_FRAMEBUFFER_STRIDE_PIXELS + (uint32_t)x] = color;
    }
}

static void rectangle(int16_t x, int16_t y, int16_t width, int16_t height, uint16_t color) {
    for (int16_t row = 0; row < height; ++row) {
        for (int16_t column = 0; column < width; ++column) {
            pixel((int16_t)(x + column), (int16_t)(y + row), color);
        }
    }
}

static uint8_t glyph_column(char character, uint8_t column) {
    static const uint8_t digits[10][5] = {
        {0x3e,0x51,0x49,0x45,0x3e},{0,0x42,0x7f,0x40,0},{0x62,0x51,0x49,0x49,0x46},
        {0x22,0x49,0x49,0x49,0x36},{0x18,0x14,0x12,0x7f,0x10},{0x2f,0x49,0x49,0x49,0x31},
        {0x3e,0x49,0x49,0x49,0x32},{0x01,0x71,0x09,0x05,0x03},{0x36,0x49,0x49,0x49,0x36},
        {0x26,0x49,0x49,0x49,0x3e},
    };
    static const uint8_t letters[26][5] = {
        {0x7e,0x11,0x11,0x11,0x7e},{0x7f,0x49,0x49,0x49,0x36},{0x3e,0x41,0x41,0x41,0x22},
        {0x7f,0x41,0x41,0x22,0x1c},{0x7f,0x49,0x49,0x49,0x41},{0x7f,0x09,0x09,0x09,0x01},
        {0x3e,0x41,0x49,0x49,0x7a},{0x7f,0x08,0x08,0x08,0x7f},{0,0x41,0x7f,0x41,0},
        {0x20,0x40,0x41,0x3f,0x01},{0x7f,0x08,0x14,0x22,0x41},{0x7f,0x40,0x40,0x40,0x40},
        {0x7f,0x02,0x0c,0x02,0x7f},{0x7f,0x04,0x08,0x10,0x7f},{0x3e,0x41,0x41,0x41,0x3e},
        {0x7f,0x09,0x09,0x09,0x06},{0x3e,0x41,0x51,0x21,0x5e},{0x7f,0x09,0x19,0x29,0x46},
        {0x46,0x49,0x49,0x49,0x31},{0x01,0x01,0x7f,0x01,0x01},{0x3f,0x40,0x40,0x40,0x3f},
        {0x1f,0x20,0x40,0x20,0x1f},{0x3f,0x40,0x38,0x40,0x3f},{0x63,0x14,0x08,0x14,0x63},
        {0x07,0x08,0x70,0x08,0x07},{0x61,0x51,0x49,0x45,0x43},
    };
    if (column >= 5U) return 0U;
    if (character >= '0' && character <= '9') return digits[(uint8_t)character - '0'][column];
    if (character >= 'a' && character <= 'z') character = (char)(character - ('a' - 'A'));
    if (character >= 'A' && character <= 'Z') return letters[(uint8_t)character - 'A'][column];
    if (character == '-') return column == 2U ? 0x08U : 0U;
    if (character == '.') return column == 2U ? 0x60U : 0U;
    return 0U;
}

static void text(int16_t x, int16_t y, const char *value, uint16_t length, uint16_t color) {
    int32_t pen_x = x;
    for (uint16_t character = 0U; character < length; ++character) {
        if (pen_x >= (int32_t)KB7_DISPLAY_WIDTH) break;
        for (uint8_t column = 0U; column < 5U; ++column) {
            const uint8_t bits = glyph_column(value[character], column);
            for (uint8_t row = 0U; row < 7U; ++row) {
                if ((bits & KB7_BIT(row)) != 0U) {
                    pixel((int16_t)(pen_x + column), (int16_t)(y + row), color);
                }
            }
        }
        pen_x += 7;
    }
}

static void render_widget(uint16_t index, const struct kb7_widget_record *widget) {
    rectangle(widget->x, widget->y, widget->width, widget->height, widget->background_rgb565);
    if (widget->type == KB7_WIDGET_BUTTON || widget->type == KB7_WIDGET_TOGGLE) {
        rectangle((int16_t)(widget->x + 2), (int16_t)(widget->y + 2),
                  (int16_t)(widget->width - 4), 2, widget->foreground_rgb565);
    } else if (widget->type == KB7_WIDGET_SLIDER || widget->type == KB7_WIDGET_GAUGE) {
        int32_t span = (int32_t)widget->maximum - widget->minimum;
        int32_t value = (int32_t)widget_values[index] - widget->minimum;
        int16_t fill = span > 0 ? (int16_t)((value * widget->width) / span) : 0;
        rectangle(widget->x, (int16_t)(widget->y + widget->height / 2 - 3), fill, 6,
                  widget->foreground_rgb565);
    }
    const char *label;
    if (kb7_screen_text(screen_store, widget->text_offset, widget->text_length, &label)) {
        text((int16_t)(widget->x + 8), (int16_t)(widget->y + widget->height / 2 - 4),
             label, widget->text_length, widget->foreground_rgb565);
    }
}

void kb7_ui_init(uintptr_t framebuffer, const struct kb7_screen_store *store,
                 kb7_action_handler_t action_handler) {
    target = framebuffer;
    screen_store = store;
    handle_action = action_handler;
    active_screen = store != NULL && store->header != NULL ? store->header->boot_screen : 0U;
    active_widget = KB7_NO_ACTIVE_WIDGET;
    for (uint16_t index = 0U; index < KB7_SCREEN_MAX_WIDGETS; ++index) {
        widget_values[index] = 0;
    }
    if (store != NULL && store->header != NULL) {
        for (uint16_t index = 0U; index < store->header->widget_count; ++index) {
            const struct kb7_widget_record *widget = kb7_screen_widget(store, index);
            if (widget != NULL) widget_values[index] = widget->value;
        }
    }
}

void kb7_ui_set_store(const struct kb7_screen_store *store) {
    release_active_widget();
    screen_store = store;
    active_screen = store != NULL && store->header != NULL ? store->header->boot_screen : 0U;
    for (uint16_t index = 0U; index < KB7_SCREEN_MAX_WIDGETS; ++index) {
        widget_values[index] = 0;
    }
    if (store != NULL && store->header != NULL) {
        for (uint16_t index = 0U; index < store->header->widget_count; ++index) {
            const struct kb7_widget_record *const widget = kb7_screen_widget(store, index);
            if (widget != NULL) widget_values[index] = widget->value;
        }
    }
    kb7_ui_render();
}

void kb7_ui_render(void) {
    if (target == 0U) return;
    if (screen_store == NULL || screen_store->header == NULL) {
        rectangle(0, 0, KB7_DISPLAY_WIDTH, KB7_DISPLAY_HEIGHT, 0x0841U);
        rectangle(24, 24, 432, 112, 0x18e3U);
        text(52, 68, "OFFLINE CONTROL", 15U, 0xffffU);
        text(52, 96, "SAFE DEFAULT", 12U, 0x9e7fU);
        kb7_dsb();
        return;
    }
    const struct kb7_screen_record *screen = kb7_screen_find(screen_store, active_screen);
    if (screen == NULL) return;
    rectangle(0, 0, KB7_DISPLAY_WIDTH, KB7_DISPLAY_HEIGHT, screen->background_rgb565);
    for (uint16_t index = 0U; index < screen->widget_count; ++index) {
        const struct kb7_widget_record *widget =
            kb7_screen_widget(screen_store, (uint16_t)(screen->first_widget + index));
        if (widget != NULL) render_widget((uint16_t)(screen->first_widget + index), widget);
    }
    kb7_dsb();
}

static int16_t slider_value(const struct kb7_widget_record *widget, uint16_t x) {
    if (x <= (uint16_t)widget->x) return widget->minimum;
    const uint16_t right = (uint16_t)(widget->x + widget->width - 1);
    if (x >= right) return widget->maximum;
    const int32_t span = (int32_t)widget->maximum - widget->minimum;
    const int32_t position = (int32_t)x - widget->x;
    return (int16_t)(widget->minimum +
                     (span * position + (widget->width - 1) / 2) / (widget->width - 1));
}

static void release_active_widget(void) {
    if (active_widget == KB7_NO_ACTIVE_WIDGET) return;
    const struct kb7_widget_record *const widget =
        kb7_screen_widget(screen_store, active_widget);
    if (widget != NULL && handle_action != NULL) {
        handle_action(widget, widget_values[active_widget], KB7_UI_UP);
    }
    active_widget = KB7_NO_ACTIVE_WIDGET;
}

void kb7_ui_touch(uint16_t x, uint16_t y, enum kb7_ui_phase phase) {
    if (screen_store == NULL || screen_store->header == NULL) return;
    if (phase != KB7_UI_DOWN) {
        if (active_widget == KB7_NO_ACTIVE_WIDGET) return;
        const struct kb7_widget_record *widget = kb7_screen_widget(screen_store, active_widget);
        if (widget == NULL) {
            active_widget = KB7_NO_ACTIVE_WIDGET;
            return;
        }
        if (widget->type == KB7_WIDGET_SLIDER) {
            widget_values[active_widget] = slider_value(widget, x);
            kb7_ui_render();
        }
        if (handle_action != NULL) {
            handle_action(widget, widget_values[active_widget], phase);
        }
        if (phase == KB7_UI_UP) active_widget = KB7_NO_ACTIVE_WIDGET;
        return;
    }
    const struct kb7_screen_record *screen = kb7_screen_find(screen_store, active_screen);
    if (screen == NULL) return;
    for (uint16_t index = screen->widget_count; index != 0U; --index) {
        const struct kb7_widget_record *widget = kb7_screen_widget(
            screen_store, (uint16_t)(screen->first_widget + index - 1U));
        if (widget != NULL && x >= (uint16_t)widget->x && y >= (uint16_t)widget->y &&
            x < (uint16_t)(widget->x + widget->width) &&
            y < (uint16_t)(widget->y + widget->height)) {
            active_widget = (uint16_t)(screen->first_widget + index - 1U);
            if (widget->type == KB7_WIDGET_SLIDER) {
                widget_values[active_widget] = slider_value(widget, x);
                kb7_ui_render();
            } else if (widget->type == KB7_WIDGET_TOGGLE) {
                widget_values[active_widget] = widget_values[active_widget] == widget->maximum
                                                   ? widget->minimum : widget->maximum;
                kb7_ui_render();
            }
            if (widget->action == KB7_ACTION_NAVIGATE) {
                active_widget = KB7_NO_ACTIVE_WIDGET;
                (void)kb7_ui_navigate(widget->target_screen);
                return;
            }
            if (handle_action != NULL) {
                handle_action(widget, widget_values[active_widget], phase);
            }
            return;
        }
    }
}

bool kb7_ui_navigate(uint16_t screen_id) {
    if (screen_store == NULL || kb7_screen_find(screen_store, screen_id) == NULL) return false;
    release_active_widget();
    active_screen = screen_id;
    kb7_ui_render();
    return true;
}

uint16_t kb7_ui_active_screen(void) { return active_screen; }
