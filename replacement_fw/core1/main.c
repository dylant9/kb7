#include "kb7/drivers.h"
#include "kb7/host_protocol.h"
#include "kb7/host_server.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"
#include "kb7/screen.h"
#include "kb7/storage.h"
#include "kb7/ui.h"

#define KB7_FLASH_XIP_BASE UINT32_C(0x60000000)

static struct kb7_hall_config hall_config = {128U, 12U, 12U, true};
static struct kb7_hall_state hall_state[KB7_HALL_KEY_COUNT];
static struct kb7_rgb rgb_colors[KB7_RGB_POSITION_COUNT];
static struct kb7_screen_store screens;
static uint8_t active_profile;
static struct kb7_host_server host_server;

static void send_host_event(const struct kb7_widget_record *widget, int16_t value) {
    struct kb7_host_report report;
    kb7_memset(&report, 0, sizeof(report));
    report.kind = KB7_HOST_EVENT;
    report.opcode = KB7_HOST_WIDGET_EVENT;
    report.sequence = widget->id;
    report.offset = (uint16_t)value;
    report.total_length = kb7_ui_active_screen();
    kb7_host_report_finalize(&report);
    (void)kb7_runtime()->usb_send(2U, &report, sizeof(report));
}

static void action(const struct kb7_widget_record *widget, int16_t value) {
    switch (widget->action) {
    case KB7_ACTION_RGB_COLOR: {
        const struct kb7_rgb color = {
            (uint8_t)(widget->action_arg1 >> 16U),
            (uint8_t)(widget->action_arg1 >> 8U),
            (uint8_t)widget->action_arg1,
        };
        for (size_t index = 0U; index < KB7_RGB_POSITION_COUNT; ++index) rgb_colors[index] = color;
        kb7_rgb_show(rgb_colors);
        break;
    }
    case KB7_ACTION_BRIGHTNESS: {
        uint16_t percent = value < 0 ? 0U : (uint16_t)value;
        if (percent > 100U) percent = 100U;
        kb7_rgb_set_brightness((uint8_t)percent);
        kb7_backlight_set((uint16_t)((percent * 1023U) / 100U));
        break;
    }
    case KB7_ACTION_PROFILE:
        active_profile = (uint8_t)widget->action_arg0;
        break;
    case KB7_ACTION_ACTUATION:
        hall_config.actuation = (uint8_t)value;
        break;
    case KB7_ACTION_RAPID_TRIGGER:
        hall_config.rapid_trigger = value != 0;
        hall_config.rapid_press_delta = (uint8_t)widget->action_arg0;
        hall_config.rapid_release_delta = (uint8_t)widget->action_arg1;
        break;
    case KB7_ACTION_HID_KEY: {
        uint8_t keys[19] = {0};
        const uint8_t usage = (uint8_t)widget->action_arg0;
        if (usage < 152U) keys[usage >> 3U] = (uint8_t)KB7_BIT(usage & 7U);
        kb7_usb_keyboard_report(keys, 0U);
        break;
    }
    case KB7_ACTION_MEDIA_KEY:
        kb7_usb_consumer_usage(widget->action_arg0);
        break;
    case KB7_ACTION_HOST_EVENT:
        send_host_event(widget, value);
        break;
    default:
        break;
    }
    (void)active_profile;
}

static bool load_screens(void) {
    const struct kb7_slot_choice choice = kb7_storage_select();
    if (!choice.valid) return false;
    const uint8_t *payload = (const uint8_t *)(uintptr_t)(
        KB7_FLASH_XIP_BASE + choice.offset + sizeof(struct kb7_slot_header));
    if (kb7_crc32(payload, choice.header.payload_length) != choice.header.payload_crc32) return false;
    return kb7_screen_parse(payload, choice.header.payload_length, &screens) == KB7_SCREEN_VALID;
}

static void send_analog_compatibility(const uint8_t values[KB7_HALL_KEY_COUNT]) {
    for (uint8_t page = 0U; page < 2U; ++page) {
        uint8_t report[64] = {0};
        const uint8_t start = (uint8_t)(page * 60U);
        const uint8_t count = page == 0U ? 60U : 22U;
        report[0] = 0x03U;
        report[1] = 0xfaU;
        report[2] = page;
        report[3] = count;
        kb7_memcpy(&report[4], &values[start], count);
        (void)kb7_runtime()->usb_send(2U, report, sizeof(report));
    }
}

static void process_hall(void) {
    uint8_t values[KB7_HALL_KEY_COUNT];
    if (kb7_mcu2_read_normalized(values) != KB7_MCU2_OK) return;
    uint8_t keys[19] = {0};
    for (size_t key = 0U; key < KB7_HALL_KEY_COUNT; ++key) {
        if (kb7_hall_update(&hall_state[key], values[key], &hall_config)) {
            keys[key >> 3U] |= (uint8_t)KB7_BIT(key & 7U);
        }
    }
    kb7_usb_keyboard_report(keys, 0U);
    send_analog_compatibility(values);
}

void kb7_application_main(void) {
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (api->magic != KB7_RUNTIME_MAGIC || api->abi_version != KB7_RUNTIME_ABI_VERSION ||
        api->size != sizeof(*api)) {
        for (;;) kb7_wfi();
    }
    kb7_backlight_init();
    kb7_backlight_set(180U);
    kb7_encoder_init();
    kb7_host_server_init(&host_server);
    kb7_hall_reset(hall_state);
    const bool rgb_ready = kb7_rgb_init();
    const bool touch_ready = kb7_touch_init();
    const bool mcu2_ready = kb7_mcu2_init();
    const bool screen_valid = load_screens();
    const bool dram_ready = (api->boot_flags & KB7_BOOT_DRAM_READY) != 0U;
    if (dram_ready) {
        kb7_lcdc_fill(KB7_FRAMEBUFFER_A, 0x0841U);
        kb7_panel_init();
        if (kb7_lcdc_init(KB7_FRAMEBUFFER_A)) {
            kb7_ui_init(KB7_FRAMEBUFFER_A, screen_valid ? &screens : NULL, action);
            kb7_ui_render();
            kb7_backlight_set(820U);
        }
    }
    if (rgb_ready) {
        for (size_t index = 0U; index < KB7_RGB_POSITION_COUNT; ++index) {
            rgb_colors[index] = (struct kb7_rgb){18U, 35U, 74U};
        }
        kb7_rgb_show(rgb_colors);
    }

    uint32_t next_hall = 0U;
    bool touch_down = false;
    for (;;) {
        api->usb_poll();
        const uint32_t now = api->milliseconds();
        if (mcu2_ready && (int32_t)(now - next_hall) >= 0) {
            process_hall();
            next_hall = now + 5U;
        }
        const enum kb7_encoder_event encoder = kb7_encoder_poll();
        if (encoder == KB7_ENCODER_CW) kb7_usb_consumer_usage(0x00e9U);
        if (encoder == KB7_ENCODER_CCW) kb7_usb_consumer_usage(0x00eaU);
        if (touch_ready && dram_ready) {
            struct kb7_touch_frame frame;
            if (kb7_touch_read(&frame)) {
                const bool down = frame.count != 0U;
                if (down && !touch_down) kb7_ui_touch(frame.points[0].x, frame.points[0].y, true);
                touch_down = down;
            }
        }
    }
}
