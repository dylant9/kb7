#include "kb7/regs.h"
#include "kb7/ui.h"

struct KB7_PACKED test_blob {
    struct kb7_screen_header header;
    struct kb7_screen_record screens[2];
    struct kb7_widget_record widgets[3];
};

static uint16_t framebuffer[KB7_FRAMEBUFFER_STRIDE_PIXELS * KB7_DISPLAY_HEIGHT];
static enum kb7_ui_phase phases[16];
static int16_t values[16];
static uint8_t actions[16];
static uint8_t event_count;

static void action(const struct kb7_widget_record *widget, int16_t value,
                   enum kb7_ui_phase phase) {
    if (event_count < 16U) {
        phases[event_count] = phase;
        values[event_count] = value;
        actions[event_count] = widget->action;
        ++event_count;
    }
}

int main(void) {
    struct test_blob blob = {0};
    blob.header.screen_count = 2U;
    blob.header.boot_screen = 7U;
    blob.header.widget_count = 3U;
    blob.header.screens_offset = sizeof(blob.header);
    blob.header.widgets_offset = sizeof(blob.header) + sizeof(blob.screens);
    blob.screens[0].id = 7U;
    blob.screens[0].widget_count = 3U;
    blob.screens[1].id = 8U;
    blob.screens[1].first_widget = 3U;

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

    blob.widgets[2].id = 3U;
    blob.widgets[2].type = KB7_WIDGET_BUTTON;
    blob.widgets[2].x = 10;
    blob.widgets[2].y = 70;
    blob.widgets[2].width = 30;
    blob.widgets[2].height = 20;
    blob.widgets[2].action = KB7_ACTION_HID_KEY;
    blob.widgets[2].action_arg0 = 4U;

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
    kb7_ui_touch(15U, 75U, KB7_UI_DOWN);
    if (event_count != 6U || actions[5] != KB7_ACTION_HID_KEY ||
        phases[5] != KB7_UI_DOWN) return 7;
    if (!kb7_ui_navigate(8U) || event_count != 7U ||
        actions[6] != KB7_ACTION_HID_KEY || phases[6] != KB7_UI_UP) return 8;
    kb7_ui_touch(15U, 75U, KB7_UI_UP);
    if (event_count != 7U) return 9;
    kb7_ui_set_store(&store);
    kb7_ui_touch(15U, 75U, KB7_UI_DOWN);
    if (event_count != 8U || phases[7] != KB7_UI_DOWN) return 10;
    kb7_ui_set_store(NULL);
    if (event_count != 9U || phases[8] != KB7_UI_UP) return 11;
    kb7_ui_touch(15U, 75U, KB7_UI_UP);
    if (event_count != 9U) return 12;
    return 0;
}
