#include "kb7/drivers.h"
#include "kb7/runtime.h"
#include "kb7/usb_device.h"

static uint8_t physical_bits[19];
static uint8_t physical_modifiers;
static uint8_t action_bits[19];
static uint8_t action_modifiers;
static uint16_t physical_consumer_usage;
static uint16_t action_consumer_usage;

struct pending_report {
    uint8_t data[KB7_USB_ENDPOINT_SIZE];
    uint16_t length;
    bool valid;
    bool dirty;
};

static struct pending_report keyboard_report;
static struct pending_report consumer_report;
static struct pending_report gamepad_report;
static struct pending_report host_response;
static struct pending_report vendor_telemetry;
static struct pending_report analog_report[2];
static uint16_t consumer_pulse_usage;
static uint16_t next_consumer_pulse_usage;
static bool consumer_pulse_pending;
static bool consumer_release_pending;
static bool next_consumer_pulse_pending;
static uint8_t high_priority_cursor;
static uint8_t telemetry_cursor;
static uint32_t usb_queue_epoch;
static bool usb_queue_epoch_seen;

static int32_t send_report(const void *report, uint16_t length) {
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (report == NULL || api->magic != KB7_RUNTIME_MAGIC ||
        api->abi_version != KB7_RUNTIME_ABI_VERSION || api->size != sizeof(*api) ||
        api->usb_send == NULL) return KB7_USB_UNAVAILABLE;
    return api->usb_send(KB7_USB_DATA_ENDPOINT, report, length);
}

static bool stage_latest(struct pending_report *pending, const void *report,
                         uint16_t length) {
    if (pending == NULL || report == NULL || length == 0U ||
        length > sizeof(pending->data)) return false;
    if (pending->valid && pending->length == length &&
        kb7_memcmp(pending->data, report, length) == 0) return true;
    kb7_memcpy(pending->data, report, length);
    pending->length = length;
    pending->valid = true;
    pending->dirty = true;
    return true;
}

static bool flush_latest(struct pending_report *pending) {
    if (pending == NULL || !pending->valid || !pending->dirty) return false;
    if (send_report(pending->data, pending->length) != KB7_USB_OK) return false;
    pending->dirty = false;
    return true;
}

static void send_keyboard(void) {
    uint8_t report[KB7_KEYBOARD_REPORT_BYTES];
    report[0] = KB7_REPORT_ID_KEYBOARD;
    report[1] = physical_modifiers | action_modifiers;
    for (size_t index = 0U; index < sizeof(physical_bits); ++index) {
        report[index + 2U] = physical_bits[index] | action_bits[index];
    }
    (void)stage_latest(&keyboard_report, report, sizeof(report));
    kb7_usb_client_poll();
}

void kb7_usb_keyboard_report(const uint8_t bits[19], uint8_t modifiers) {
    if (bits == NULL) return;
    kb7_memcpy(physical_bits, bits, sizeof(physical_bits));
    physical_modifiers = modifiers;
    send_keyboard();
}

void kb7_usb_keyboard_action(uint16_t usage, bool pressed) {
    if (usage >= 0xe0U && usage <= 0xe7U) {
        const uint8_t mask = (uint8_t)KB7_BIT(usage - 0xe0U);
        if (pressed) action_modifiers |= mask;
        else action_modifiers &= (uint8_t)~mask;
    } else if (usage < KB7_KEYBOARD_USAGE_BITS) {
        const uint8_t mask = (uint8_t)KB7_BIT(usage & 7U);
        if (pressed) action_bits[usage >> 3U] |= mask;
        else action_bits[usage >> 3U] &= (uint8_t)~mask;
    } else {
        return;
    }
    send_keyboard();
}

static void stage_consumer(uint16_t usage) {
    const uint8_t report[KB7_CONSUMER_REPORT_BYTES] = {
        KB7_REPORT_ID_CONSUMER, (uint8_t)usage, (uint8_t)(usage >> 8U)
    };
    (void)stage_latest(&consumer_report, report, sizeof(report));
}

static void send_merged_consumer(void) {
    /* UI actions take priority while held; physical state resumes on release. */
    stage_consumer(action_consumer_usage != 0U ?
                   action_consumer_usage : physical_consumer_usage);
    kb7_usb_client_poll();
}

void kb7_usb_consumer_usage(uint16_t usage) {
    physical_consumer_usage = usage;
    send_merged_consumer();
}

void kb7_usb_consumer_action(uint16_t usage, bool pressed) {
    action_consumer_usage = pressed ? usage : 0U;
    send_merged_consumer();
}

void kb7_usb_consumer_pulse(uint16_t usage) {
    stage_consumer(action_consumer_usage != 0U ?
                   action_consumer_usage : physical_consumer_usage);
    if (!consumer_pulse_pending && !consumer_release_pending) {
        consumer_pulse_usage = usage;
        consumer_pulse_pending = true;
    } else {
        /* Preserve the mandatory release; coalesce repeated encoder pulses. */
        next_consumer_pulse_usage = usage;
        next_consumer_pulse_pending = true;
    }
    kb7_usb_client_poll();
    kb7_usb_client_poll();
}

void kb7_usb_gamepad_state(uint16_t buttons, uint8_t hat,
                           const int16_t axes[KB7_USB_GAMEPAD_AXIS_COUNT],
                           uint8_t left_trigger, uint8_t right_trigger) {
    if (axes == NULL) return;
    uint8_t report[KB7_USB_GAMEPAD_REPORT_BYTES] = {0};
    report[0] = KB7_USB_GAMEPAD_REPORT_ID;
    report[1] = (uint8_t)buttons;
    report[2] = (uint8_t)(buttons >> 8U);
    report[3] = hat <= 7U ? hat : 0x0fU;
    for (size_t index = 0U; index < KB7_USB_GAMEPAD_AXIS_COUNT; ++index) {
        const uint16_t value = (uint16_t)axes[index];
        report[4U + index * 2U] = (uint8_t)value;
        report[5U + index * 2U] = (uint8_t)(value >> 8U);
    }
    report[12] = left_trigger;
    report[13] = right_trigger;
    (void)stage_latest(&gamepad_report, report, sizeof(report));
    kb7_usb_client_poll();
}

void kb7_usb_physical_neutral(void) {
    static const int16_t axes[KB7_USB_GAMEPAD_AXIS_COUNT] = {0, 0, 0, 0};
    kb7_memset(physical_bits, 0, sizeof(physical_bits));
    physical_modifiers = 0U;
    send_keyboard();
    physical_consumer_usage = 0U;
    send_merged_consumer();
    kb7_usb_gamepad_state(0U, 0x0fU, axes, 0U, 0U);
}

void kb7_usb_analog_state(const uint8_t *travel) {
    if (travel == NULL) return;
    for (uint8_t page = 0U; page < 2U; ++page) {
        uint8_t report[KB7_ANALOG_REPORT_BYTES] = {0};
        const uint8_t start = (uint8_t)(page * KB7_ANALOG_VALUES_PER_PAGE);
        const uint8_t count = page == 0U ? KB7_ANALOG_VALUES_PER_PAGE
                                         : KB7_HALL_KEY_COUNT - KB7_ANALOG_VALUES_PER_PAGE;
        report[0] = KB7_REPORT_ID_ANALOG;
        report[1] = 0xfaU;
        report[2] = page;
        report[3] = count;
        kb7_memcpy(&report[4], &travel[start], count);
        (void)stage_latest(&analog_report[page], report, sizeof(report));
    }
    kb7_usb_client_poll();
}

bool kb7_usb_vendor_response(const void *report, uint16_t length) {
    if (report == NULL || length != KB7_USB_ENDPOINT_SIZE ||
        ((const uint8_t *)report)[0] != KB7_REPORT_ID_VENDOR) return false;
    if (host_response.dirty) {
        return host_response.length == length &&
               kb7_memcmp(host_response.data, report, length) == 0;
    }
    if (!stage_latest(&host_response, report, length)) return false;
    /* A host retry of an identical command still requires a fresh response. */
    host_response.dirty = true;
    kb7_usb_client_poll();
    return true;
}

bool kb7_usb_vendor_response_pending(void) {
    return host_response.dirty;
}

void kb7_usb_vendor_telemetry(const void *report, uint16_t length) {
    if (report == NULL || length != KB7_USB_ENDPOINT_SIZE ||
        ((const uint8_t *)report)[0] != KB7_REPORT_ID_VENDOR) return;
    (void)stage_latest(&vendor_telemetry, report, length);
    kb7_usb_client_poll();
}

static bool consumer_pending(void) {
    return consumer_pulse_pending || consumer_release_pending || consumer_report.dirty;
}

static bool flush_consumer(void) {
    if (consumer_pulse_pending) {
        const uint8_t report[KB7_CONSUMER_REPORT_BYTES] = {
            KB7_REPORT_ID_CONSUMER, (uint8_t)consumer_pulse_usage,
            (uint8_t)(consumer_pulse_usage >> 8U)
        };
        if (send_report(report, sizeof(report)) != KB7_USB_OK) return false;
        consumer_pulse_pending = false;
        consumer_release_pending = true;
        consumer_report.dirty = true;
        return true;
    }
    if (!consumer_release_pending && !consumer_report.dirty) return false;
    if (!flush_latest(&consumer_report)) return false;
    consumer_release_pending = false;
    if (next_consumer_pulse_pending) {
        consumer_pulse_usage = next_consumer_pulse_usage;
        consumer_pulse_pending = true;
        next_consumer_pulse_pending = false;
    }
    return true;
}

static bool high_priority_pending(uint8_t index) {
    switch (index) {
    case 0U: return host_response.dirty;
    case 1U: return keyboard_report.dirty;
    case 2U: return consumer_pending();
    case 3U: return gamepad_report.dirty;
    default: return false;
    }
}

static bool flush_high_priority(uint8_t index) {
    switch (index) {
    case 0U: return flush_latest(&host_response);
    case 1U: return flush_latest(&keyboard_report);
    case 2U: return flush_consumer();
    case 3U: return flush_latest(&gamepad_report);
    default: return false;
    }
}

static void observe_usb_queue_epoch(void) {
    const uint32_t epoch = kb7_shared()->usb_events;
    if (!usb_queue_epoch_seen) {
        usb_queue_epoch = epoch;
        usb_queue_epoch_seen = true;
        return;
    }
    if (epoch == usb_queue_epoch) return;
    usb_queue_epoch = epoch;

    /* Core 0 discarded accepted-but-not-yet-transmitted state reports. */
    if (keyboard_report.valid) keyboard_report.dirty = true;
    if (consumer_report.valid) consumer_report.dirty = true;
    if (gamepad_report.valid) gamepad_report.dirty = true;
    if (analog_report[0].valid) analog_report[0].dirty = true;
    if (analog_report[1].valid) analog_report[1].dirty = true;
}

void kb7_usb_client_poll(void) {
    /*
     * One accepted packet per call bounds queue growth.  Round-robin among
     * command responses and HID controls prevents a noisy axis or key source
     * from starving a release.  A BUSY/UNAVAILABLE result retains the packet.
     */
    observe_usb_queue_epoch();
    for (uint8_t offset = 0U; offset < 4U; ++offset) {
        const uint8_t index = (uint8_t)((high_priority_cursor + offset) & 3U);
        if (!high_priority_pending(index)) continue;
        if (flush_high_priority(index)) {
            high_priority_cursor = (uint8_t)((index + 1U) & 3U);
        }
        return;
    }

    /* Telemetry is latest-value/coalesced and never precedes pending controls. */
    for (uint8_t offset = 0U; offset < 3U; ++offset) {
        const uint8_t index = (uint8_t)((telemetry_cursor + offset) % 3U);
        struct pending_report *pending = index == 0U ? &vendor_telemetry
                                         : &analog_report[index - 1U];
        if (!pending->dirty) continue;
        if (flush_latest(pending)) telemetry_cursor = (uint8_t)((index + 1U) % 3U);
        return;
    }
}
