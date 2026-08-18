#include "kb7/drivers.h"
#include "kb7/action_bar.h"
#include "kb7/application.h"
#include "kb7/config.h"
#include "kb7/host_protocol.h"
#include "kb7/host_server.h"
#include "kb7/input.h"
#include "kb7/input_profiles.h"
#include "kb7/lighting.h"
#include "kb7/profile_blob.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"
#include "kb7/screen.h"
#include "kb7/storage.h"
#include "kb7/ui.h"
#include "kb7/usb_device.h"

#define KB7_FLASH_XIP_BASE UINT32_C(0x60000000)

_Static_assert(KB7_GAMEPAD_REPORT_ID == KB7_USB_GAMEPAD_REPORT_ID,
               "input and USB gamepad IDs differ");
_Static_assert(KB7_GAMEPAD_REPORT_BYTES == KB7_USB_GAMEPAD_REPORT_BYTES,
               "input and USB gamepad sizes differ");

static struct kb7_input_profile_bank input_profiles;
static struct kb7_input_state input_state;
static struct kb7_rgb rgb_colors[KB7_RGB_POSITION_COUNT];
static struct kb7_lighting_profile lighting_profiles[KB7_INPUT_PROFILE_SLOT_COUNT];
static uint8_t latest_travel[KB7_HALL_KEY_COUNT];
static struct kb7_profile_store profile_parse_workspace;
static struct kb7_screen_store screens;
static struct kb7_host_server host_server;
static uint16_t last_physical_consumer;
static struct kb7_gamepad_report last_gamepad;
static struct kb7_input_link_guard hall_link_guard;
static struct kb7_action_bar_state action_bar;
static uint16_t action_bar_sequence;

static struct kb7_input_profile *active_input_profile(void) {
    return kb7_input_profile_active(&input_profiles);
}

static struct kb7_lighting_profile *active_lighting_profile(void) {
    return input_profiles.active < KB7_INPUT_PROFILE_SLOT_COUNT
               ? &lighting_profiles[input_profiles.active] : NULL;
}

static void lighting_defaults(void) {
    const struct kb7_lighting_profile defaults = {
        true, KB7_LIGHTING_AURORA, 68U, 42U, KB7_LIGHTING_EAST,
        {0x42U, 0xefU, 0xffU}, {0x9dU, 0x5cU, 0xffU}, {0xb5U, 0xffU, 0xcbU},
    };
    for (uint8_t slot = 0U; slot < KB7_INPUT_PROFILE_SLOT_COUNT; ++slot) {
        lighting_profiles[slot] = defaults;
    }
}

static void render_lighting(uint32_t now) {
    struct kb7_lighting_profile *const profile = active_lighting_profile();
    if (profile == NULL) return;
    kb7_lighting_render(profile, now, latest_travel, rgb_colors);
    kb7_rgb_set_brightness(profile->brightness);
    kb7_rgb_show(rgb_colors);
}

static uint8_t ui_level_to_travel(uint32_t value) {
    if (value > 255U) value = 255U;
    uint8_t travel = (uint8_t)((value * KB7_HALL_TRAVEL_MAX + 127U) / 255U);
    return travel == 0U ? 1U : travel;
}

static void send_host_event(const struct kb7_widget_record *widget, int16_t value,
                            enum kb7_ui_phase phase) {
    struct kb7_host_report report;
    kb7_memset(&report, 0, sizeof(report));
    report.kind = KB7_HOST_EVENT;
    report.opcode = KB7_HOST_WIDGET_EVENT;
    report.flags = (uint8_t)phase;
    report.sequence = widget->id;
    report.offset = (uint16_t)value;
    report.total_length = kb7_ui_active_screen();
    kb7_host_report_finalize(&report);
    kb7_usb_vendor_telemetry(&report, sizeof(report));
}

static void send_action_bar_event(uint8_t key, bool pressed) {
    struct kb7_host_report report;
    kb7_memset(&report, 0, sizeof(report));
    report.kind = KB7_HOST_EVENT;
    report.opcode = KB7_HOST_ACTION_BAR_EVENT;
    report.flags = pressed ? 1U : 0U;
    report.sequence = action_bar_sequence++;
    report.offset = key;
    report.payload[0] = key;
    report.payload[1] = pressed ? 1U : 0U;
    kb7_host_report_finalize(&report);
    kb7_usb_vendor_telemetry(&report, sizeof(report));
}

static void process_action_bar(void) {
    uint8_t pressed;
    uint8_t released;
    kb7_action_bar_update(&action_bar, kb7_action_bar_sample(), &pressed, &released);
    for (uint8_t key = 0U; key < KB7_ACTION_BAR_KEY_COUNT; ++key) {
        const uint8_t mask = (uint8_t)KB7_BIT(key);
        if ((pressed & mask) != 0U) send_action_bar_event(key, true);
        if ((released & mask) != 0U) send_action_bar_event(key, false);
    }
}

static void action(const struct kb7_widget_record *widget, int16_t value,
                   enum kb7_ui_phase phase) {
    if (widget->action == KB7_ACTION_HID_KEY) {
        if (phase == KB7_UI_MOVE) return;
        kb7_usb_keyboard_action(widget->action_arg0, phase != KB7_UI_UP);
        return;
    }
    if (widget->action == KB7_ACTION_MEDIA_KEY) {
        if (phase == KB7_UI_MOVE) return;
        kb7_usb_consumer_action(widget->action_arg0, phase != KB7_UI_UP);
        return;
    }
    if (widget->action == KB7_ACTION_HOST_EVENT) {
        send_host_event(widget, value, phase);
        return;
    }
    if (phase == KB7_UI_UP ||
        (phase == KB7_UI_MOVE && widget->type != KB7_WIDGET_SLIDER)) return;
    switch (widget->action) {
    case KB7_ACTION_RGB_COLOR: {
        const struct kb7_rgb color = {
            (uint8_t)(widget->action_arg1 >> 16U),
            (uint8_t)(widget->action_arg1 >> 8U),
            (uint8_t)widget->action_arg1,
        };
        struct kb7_lighting_profile *const lighting = active_lighting_profile();
        if (lighting != NULL) {
            lighting->primary = color;
            lighting->effect = KB7_LIGHTING_STATIC;
        }
        if (KB7_ENABLE_RGB) render_lighting(kb7_runtime()->milliseconds());
        break;
    }
    case KB7_ACTION_RGB_EFFECT: {
        struct kb7_lighting_profile *const lighting = active_lighting_profile();
        if (lighting != NULL && widget->action_arg0 <= KB7_LIGHTING_HEATMAP) {
            lighting->effect = (uint8_t)widget->action_arg0;
            if (KB7_ENABLE_RGB) render_lighting(kb7_runtime()->milliseconds());
        }
        break;
    }
    case KB7_ACTION_BRIGHTNESS: {
        uint16_t percent = value < 0 ? 0U : (uint16_t)value;
        if (percent > 100U) percent = 100U;
        struct kb7_lighting_profile *const lighting = active_lighting_profile();
        if (lighting != NULL) lighting->brightness = (uint8_t)percent;
        if (KB7_ENABLE_RGB) kb7_rgb_set_brightness((uint8_t)percent);
        if (KB7_ENABLE_DISPLAY) {
            kb7_backlight_set((uint16_t)((percent * 1023U) / 100U));
        }
        break;
    }
    case KB7_ACTION_PROFILE:
        if (widget->action_arg0 < KB7_INPUT_PROFILE_SLOT_COUNT) {
            if (kb7_input_profile_bank_select(&input_profiles,
                                              (uint8_t)widget->action_arg0,
                                              &input_state) && KB7_ENABLE_RGB) {
                render_lighting(kb7_runtime()->milliseconds());
            }
        }
        break;
    case KB7_ACTION_ACTUATION: {
        struct kb7_input_profile *const profile = active_input_profile();
        if (profile == NULL) break;
        struct kb7_hall_config hall = profile->hall[0];
        hall.actuation = ui_level_to_travel(value < 0 ? 0U : (uint32_t)value);
        kb7_input_profile_set_global_hall(profile, &hall);
        kb7_input_reset(&input_state, profile);
        break;
    }
    case KB7_ACTION_RAPID_TRIGGER: {
        struct kb7_input_profile *const profile = active_input_profile();
        if (profile == NULL) break;
        struct kb7_hall_config hall = profile->hall[0];
        hall.rapid_trigger = value != 0;
        hall.rapid_press_delta = ui_level_to_travel(widget->action_arg0);
        hall.rapid_release_delta = ui_level_to_travel(widget->action_arg1);
        kb7_input_profile_set_global_hall(profile, &hall);
        kb7_input_reset(&input_state, profile);
        break;
    }
    default:
        break;
    }
}

static bool load_screens(void) {
    struct kb7_slot_choice choice = kb7_storage_select();
    for (uint8_t attempt = 0U; attempt < 2U && choice.valid; ++attempt) {
        const uint8_t *payload = (const uint8_t *)(uintptr_t)(
            KB7_FLASH_XIP_BASE + choice.offset + sizeof(struct kb7_slot_header));
        if (kb7_screen_parse(payload, choice.header.payload_length, &screens) ==
            KB7_SCREEN_VALID) {
            return true;
        }
        const uint32_t alternate = choice.offset == KB7_STORAGE_SCREEN_A
                                       ? KB7_STORAGE_SCREEN_B : KB7_STORAGE_SCREEN_A;
        choice = kb7_storage_read_slot(alternate);
    }
    return false;
}

static bool load_profiles(void) {
    struct kb7_slot_choice choice = kb7_storage_select_profiles();
    bool parsed = false;
    for (uint8_t attempt = 0U; attempt < 2U && choice.valid; ++attempt) {
        const void *const payload = (const void *)(uintptr_t)(
            KB7_FLASH_XIP_BASE + choice.offset + sizeof(struct kb7_slot_header));
        if (kb7_profile_parse(payload, choice.header.payload_length,
                              &profile_parse_workspace) == KB7_PROFILE_VALID) {
            parsed = true;
            break;
        }
        const uint32_t alternate = choice.offset == KB7_STORAGE_PROFILE_A
                                       ? KB7_STORAGE_PROFILE_B : KB7_STORAGE_PROFILE_A;
        choice = kb7_storage_read_slot(alternate);
    }
    if (!parsed) return false;
    input_profiles = profile_parse_workspace.input;
    for (uint8_t slot = 0U; slot < profile_parse_workspace.count; ++slot) {
        lighting_profiles[slot] = profile_parse_workspace.lighting[slot];
    }
    return true;
}

static void process_host_mailbox(void) {
    volatile struct kb7_shared_host_mailbox *const mailbox = kb7_host_mailbox();
    if (mailbox->state != KB7_HOST_MAILBOX_FULL ||
        kb7_usb_vendor_response_pending()) return;
    uint8_t report[KB7_SHARED_HOST_REPORT_BYTES];
    for (size_t index = 0U; index < sizeof(report); ++index) {
        report[index] = mailbox->report[index];
    }
    if (kb7_application_handle_host_report(report, sizeof(report))) {
        kb7_dmb();
        mailbox->state = KB7_HOST_MAILBOX_EMPTY;
        kb7_dmb();
    }
}

static void send_analog_compatibility(const uint8_t travel[KB7_HALL_KEY_COUNT]) {
    kb7_usb_analog_state(travel);
}

static void neutralize_hall_inputs(void) {
    kb7_input_reset(&input_state, active_input_profile());
    kb7_memset(latest_travel, 0, sizeof(latest_travel));
    last_physical_consumer = 0U;
    kb7_memset(&last_gamepad, 0, sizeof(last_gamepad));
    last_gamepad.report_id = KB7_GAMEPAD_REPORT_ID;
    last_gamepad.hat = 0x0fU;
    kb7_usb_physical_neutral();
    send_analog_compatibility(latest_travel);
}

static void process_hall(void) {
    uint8_t raw[KB7_HALL_KEY_COUNT];
    if (kb7_mcu2_read_normalized(raw) != KB7_MCU2_OK) {
        if (kb7_input_link_should_neutralize(&hall_link_guard, false)) {
            neutralize_hall_inputs();
        }
        return;
    }
    (void)kb7_input_link_should_neutralize(&hall_link_guard, true);
    struct kb7_input_profile *const profile = active_input_profile();
    if (profile == NULL) return;
    struct kb7_input_frame frame;
    kb7_input_process(&input_state, profile, raw, &frame);
    kb7_memcpy(latest_travel, frame.travel, sizeof(latest_travel));
    kb7_usb_keyboard_report(frame.keyboard_bits, frame.modifiers);
    if (frame.consumer_usage != last_physical_consumer) {
        kb7_usb_consumer_usage(frame.consumer_usage);
        last_physical_consumer = frame.consumer_usage;
    }
    if (kb7_memcmp(&frame.gamepad, &last_gamepad, sizeof(frame.gamepad)) != 0) {
        const int16_t axes[KB7_USB_GAMEPAD_AXIS_COUNT] = {
            frame.gamepad.left_x, frame.gamepad.left_y,
            frame.gamepad.right_x, frame.gamepad.right_y,
        };
        kb7_usb_gamepad_state(frame.gamepad.buttons, frame.gamepad.hat, axes,
                              frame.gamepad.left_trigger,
                              frame.gamepad.right_trigger);
        last_gamepad = frame.gamepad;
    }
    send_analog_compatibility(frame.travel);
}

static void apply_factory_defaults(void) {
    /* Release any touch-held host action before discarding its backing XIP
     * object, then switch the renderer to its built-in safe screen. */
    kb7_ui_set_store(NULL);
    kb7_memset(&screens, 0, sizeof(screens));
    kb7_input_profile_bank_default(&input_profiles);
    lighting_defaults();
    kb7_input_reset(&input_state, active_input_profile());
    kb7_memset(&hall_link_guard, 0, sizeof(hall_link_guard));
    kb7_memset(latest_travel, 0, sizeof(latest_travel));
    kb7_usb_physical_neutral();
    last_physical_consumer = 0U;
    kb7_memset(&last_gamepad, 0, sizeof(last_gamepad));
    last_gamepad.report_id = KB7_GAMEPAD_REPORT_ID;
    last_gamepad.hat = 0x0fU;
}

bool kb7_application_handle_host_report(const void *data, uint16_t length) {
    if (data == NULL || length != sizeof(struct kb7_host_report)) return false;
    struct kb7_host_report response;
    kb7_host_server_process(&host_server, (const struct kb7_host_report *)data, &response);
    if (kb7_host_server_take_storage_invalidation(&host_server)) {
        apply_factory_defaults();
    }
    return kb7_usb_vendor_response(&response, sizeof(response));
}

void kb7_application_main(void) {
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (api->magic != KB7_RUNTIME_MAGIC || api->abi_version != KB7_RUNTIME_ABI_VERSION ||
        api->size != sizeof(*api)) {
        for (;;) kb7_wfi();
    }
    if (KB7_ENABLE_ENCODER) kb7_encoder_init();
    const bool action_bar_ready =
        KB7_ENABLE_ACTION_BAR && KB7_ACTION_BAR_BOARD_PROFILE_VERIFIED;
    if (action_bar_ready) kb7_action_bar_init(&action_bar);
    kb7_host_server_init(&host_server);
    kb7_input_profile_bank_default(&input_profiles);
    lighting_defaults();
    (void)load_profiles();
    kb7_input_reset(&input_state, active_input_profile());
    kb7_memset(&last_gamepad, 0, sizeof(last_gamepad));
    kb7_memset(latest_travel, 0, sizeof(latest_travel));
    const bool rgb_ready = KB7_ENABLE_RGB && kb7_rgb_init();
    const bool mcu2_ready = KB7_ENABLE_MCU2 && kb7_mcu2_init();
    const bool screen_valid = load_screens();
    const bool dram_ready = (api->boot_flags & KB7_BOOT_DRAM_READY) != 0U;
    bool display_ready = false;
    if (KB7_ENABLE_DISPLAY && dram_ready) {
        kb7_lcdc_fill(KB7_FRAMEBUFFER_A, 0x0841U);
        kb7_panel_init();
        if (kb7_lcdc_init(KB7_FRAMEBUFFER_A)) {
            display_ready = true;
            kb7_backlight_init();
            kb7_backlight_set(180U);
            kb7_ui_init(KB7_FRAMEBUFFER_A, screen_valid ? &screens : NULL, action);
            kb7_ui_render();
            kb7_backlight_set(820U);
        }
    }
    const bool touch_ready = KB7_ENABLE_TOUCH && display_ready && kb7_touch_init();
    if (rgb_ready) {
        render_lighting(api->milliseconds());
    }

    uint32_t next_hall = 0U;
    uint32_t next_action_bar = 0U;
    uint32_t next_rgb = 0U;
    bool touch_down = false;
    uint16_t last_x = 0U;
    uint16_t last_y = 0U;
    for (;;) {
        api->usb_poll();
        kb7_usb_client_poll();
        process_host_mailbox();
        const uint32_t now = api->milliseconds();
        if (mcu2_ready && (int32_t)(now - next_hall) >= 0) {
            process_hall();
            next_hall = now + 5U;
        }
        if (action_bar_ready && (int32_t)(now - next_action_bar) >= 0) {
            process_action_bar();
            next_action_bar = now + 5U;
        }
        if (rgb_ready && (int32_t)(now - next_rgb) >= 0) {
            render_lighting(now);
            next_rgb = now + 20U;
        }
        const enum kb7_encoder_event encoder = KB7_ENABLE_ENCODER
                                                   ? kb7_encoder_poll() : KB7_ENCODER_NONE;
        if (encoder == KB7_ENCODER_CW) {
            kb7_usb_consumer_pulse(0x00e9U);
        }
        if (encoder == KB7_ENCODER_CCW) {
            kb7_usb_consumer_pulse(0x00eaU);
        }
        if (touch_ready && dram_ready) {
            struct kb7_touch_frame frame;
            if (kb7_touch_read(&frame)) {
                const bool down = frame.count != 0U;
                if (down) {
                    last_x = frame.points[0].x;
                    last_y = frame.points[0].y;
                    kb7_ui_touch(last_x, last_y, touch_down ? KB7_UI_MOVE : KB7_UI_DOWN);
                } else if (touch_down) {
                    kb7_ui_touch(last_x, last_y, KB7_UI_UP);
                }
                touch_down = down;
            } else if (touch_down) {
                /* A lost frame must not leave a touchscreen HID action held. */
                kb7_ui_touch(last_x, last_y, KB7_UI_UP);
                touch_down = false;
            }
        }
    }
}
