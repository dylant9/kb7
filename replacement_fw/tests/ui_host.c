#include "kb7/regs.h"
#include "kb7/ui.h"

struct KB7_PACKED test_blob {
    struct kb7_screen_header header;
    struct kb7_screen_record screen;
    struct kb7_widget_record widgets[2];
};

static uint16_t framebuffer[KB7_FRAMEBUFFER_STRIDE_PIXELS * KB7_DISPLAY_HEIGHT];
static enum kb7_ui_phase phases[8];
static int16_t values[8];
static uint8_t actions[8];
static uint8_t event_count;

static void action(const struct kb7_widget_record *widget, int16_t value,
                   enum kb7_ui_phase phase) {
    if (event_count < 8U) {
        phases[event_count] = phase;
        values[event_count] = value;
        actions[event_count] = widget->action;
        ++event_count;
    }
}

int main(void) {
    struct test_blob blob = {0};
    blob.header.screen_count = 1U;
    blob.header.boot_screen = 7U;
    blob.header.widget_count = 2U;
    blob.header.screens_offset = sizeof(blob.header);
    blob.header.widgets_offset = sizeof(blob.header) + sizeof(blob.screen);
    blob.screen.id = 7U;
    blob.screen.widget_count = 2U;

    blob.widgets[0].id = 1U;
    blob.widgets[0].type = KB7_WIDGET_SLIDER;
    blob.widgets[0].x = 10;
    blob.widgets[0].y = 10;
    blob.widgets[0].width = 101;
    blob.widgets[0].height = 20;
    blob.widgets[0].minimum = 0;
    blob.widgets[0].maximum = 100;
    blob.widgets[0].value = 50;
    blob.widgets[0].action = KB7_ACTION_BRIGHTNESS;

    blob.widgets[1].id = 2U;
    blob.widgets[1].type = KB7_WIDGET_TOGGLE;
    blob.widgets[1].x = 10;
    blob.widgets[1].y = 40;
    blob.widgets[1].width = 30;
    blob.widgets[1].height = 20;
    blob.widgets[1].minimum = 0;
    blob.widgets[1].maximum = 1;
    blob.widgets[1].value = 0;
    blob.widgets[1].action = KB7_ACTION_RAPID_TRIGGER;

    const struct kb7_screen_store store = {
        (const uint8_t *)&blob, sizeof(blob), &blob.header
    };
    kb7_ui_init((uintptr_t)framebuffer, &store, action);
    kb7_ui_touch(10U, 15U, KB7_UI_DOWN);
    kb7_ui_touch(110U, 15U, KB7_UI_MOVE);
    kb7_ui_touch(60U, 15U, KB7_UI_UP);
    kb7_ui_touch(15U, 45U, KB7_UI_DOWN);
    kb7_ui_touch(15U, 45U, KB7_UI_UP);

    if (event_count != 5U) return 1;
    if (phases[0] != KB7_UI_DOWN || values[0] != 0) return 2;
    if (phases[1] != KB7_UI_MOVE || values[1] != 100) return 3;
    if (phases[2] != KB7_UI_UP || values[2] != 50) return 4;
    if (actions[3] != KB7_ACTION_RAPID_TRIGGER || phases[3] != KB7_UI_DOWN ||
        values[3] != 1) return 5;
    if (phases[4] != KB7_UI_UP || values[4] != 1) return 6;
    return 0;
}
