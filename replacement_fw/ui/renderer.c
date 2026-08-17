#include "kb7/regs.h"
#include "kb7/ui.h"

static uintptr_t target;
static const struct kb7_screen_store *screen_store;
static kb7_action_handler_t handle_action;
static uint16_t active_screen;

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
    for (uint16_t character = 0U; character < length; ++character) {
        for (uint8_t column = 0U; column < 5U; ++column) {
            const uint8_t bits = glyph_column(value[character], column);
            for (uint8_t row = 0U; row < 7U; ++row) {
                if ((bits & KB7_BIT(row)) != 0U) pixel((int16_t)(x + column), (int16_t)(y + row), color);
            }
        }
        x = (int16_t)(x + 7);
    }
}

static void render_widget(const struct kb7_widget_record *widget) {
    rectangle(widget->x, widget->y, widget->width, widget->height, widget->background_rgb565);
    if (widget->type == KB7_WIDGET_BUTTON || widget->type == KB7_WIDGET_TOGGLE) {
        rectangle((int16_t)(widget->x + 2), (int16_t)(widget->y + 2),
                  (int16_t)(widget->width - 4), 2, widget->foreground_rgb565);
    } else if (widget->type == KB7_WIDGET_SLIDER || widget->type == KB7_WIDGET_GAUGE) {
        int32_t span = (int32_t)widget->maximum - widget->minimum;
        int32_t value = (int32_t)widget->value - widget->minimum;
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
}

void kb7_ui_render(void) {
    if (target == 0U) return;
    if (screen_store == NULL || screen_store->header == NULL) {
        rectangle(0, 0, KB7_DISPLAY_WIDTH, KB7_DISPLAY_HEIGHT, 0x0841U);
        rectangle(24, 24, 432, 112, 0x18e3U);
        text(52, 68, "KB7 CUSTOM", 10U, 0xffffU);
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
        if (widget != NULL) render_widget(widget);
    }
    kb7_dsb();
}

void kb7_ui_touch(uint16_t x, uint16_t y, bool pressed) {
    if (!pressed || screen_store == NULL || screen_store->header == NULL) return;
    const struct kb7_screen_record *screen = kb7_screen_find(screen_store, active_screen);
    if (screen == NULL) return;
    for (uint16_t index = screen->widget_count; index != 0U; --index) {
        const struct kb7_widget_record *widget = kb7_screen_widget(
            screen_store, (uint16_t)(screen->first_widget + index - 1U));
        if (widget != NULL && x >= (uint16_t)widget->x && y >= (uint16_t)widget->y &&
            x < (uint16_t)(widget->x + widget->width) &&
            y < (uint16_t)(widget->y + widget->height)) {
            if (widget->action == KB7_ACTION_NAVIGATE) kb7_ui_navigate(widget->target_screen);
            if (handle_action != NULL) handle_action(widget, widget->value);
            return;
        }
    }
}

void kb7_ui_navigate(uint16_t screen_id) {
    if (kb7_screen_find(screen_store, screen_id) != NULL) {
        active_screen = screen_id;
        kb7_ui_render();
    }
}

uint16_t kb7_ui_active_screen(void) { return active_screen; }
