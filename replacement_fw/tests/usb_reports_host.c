#define _GNU_SOURCE
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "kb7/drivers.h"
#include "kb7/runtime.h"
#include "kb7/usb_device.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

static uint8_t last_report[KB7_ANALOG_REPORT_BYTES];
static uint16_t last_length;
static bool saw_consumer_pulse;
static int32_t forced_result;
static int32_t successful_budget = -1;
static bool model_queue_capacity;
static uint8_t queue_depth;
static uint8_t accepted[64][KB7_USB_ENDPOINT_SIZE];
static uint16_t accepted_length[64];
static uint8_t accepted_count;

static int32_t capture(uint8_t endpoint, const void *data, uint16_t length) {
    if (endpoint != 2U || length > sizeof(last_report)) return -1;
    if (forced_result != KB7_USB_OK) return forced_result;
    if (successful_budget == 0) return KB7_USB_BUSY;
    if (model_queue_capacity && queue_depth >= 8U) return KB7_USB_BUSY;
    if (successful_budget > 0) --successful_budget;
    if (model_queue_capacity) ++queue_depth;
    memcpy(last_report, data, length);
    last_length = length;
    if (accepted_count < 64U) {
        memcpy(accepted[accepted_count], data, length);
        accepted_length[accepted_count] = length;
        ++accepted_count;
    }
    if (length == KB7_CONSUMER_REPORT_BYTES && last_report[0] == KB7_REPORT_ID_CONSUMER &&
        last_report[1] == 0xe9U && last_report[2] == 0U) saw_consumer_pulse = true;
    return 0;
}

static void clear_accepted(void) {
    memset(accepted, 0, sizeof(accepted));
    memset(accepted_length, 0, sizeof(accepted_length));
    accepted_count = 0U;
    last_length = 0U;
}

static bool saw_report(uint8_t id, uint16_t length, uint8_t byte, uint8_t value) {
    for (uint8_t index = 0U; index < accepted_count; ++index) {
        if (accepted_length[index] == length && accepted[index][0] == id &&
            accepted[index][byte] == value) return true;
    }
    return false;
}

int main(void) {
    void *mapping = mmap((void *)(uintptr_t)KB7_SHARED_API_ADDRESS, 4096U,
                         PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (mapping == MAP_FAILED) return 77;
    volatile struct kb7_runtime_api *api = kb7_runtime();
    memset((void *)api, 0, sizeof(*api));
    api->magic = KB7_RUNTIME_MAGIC;
    api->abi_version = KB7_RUNTIME_ABI_VERSION;
    api->size = sizeof(*api);
    api->usb_send = capture;

    uint8_t physical[19] = {0};
    physical[4U >> 3U] = (uint8_t)KB7_BIT(4U & 7U);
    kb7_usb_keyboard_report(physical, 1U);
    if (last_length != KB7_KEYBOARD_REPORT_BYTES ||
        last_report[0] != KB7_REPORT_ID_KEYBOARD || last_report[1] != 1U ||
        (last_report[2] & KB7_BIT(4U)) == 0U) return 1;

    kb7_usb_keyboard_action(5U, true);
    if ((last_report[2] & (KB7_BIT(4U) | KB7_BIT(5U))) !=
        (KB7_BIT(4U) | KB7_BIT(5U))) return 2;
    memset(physical, 0, sizeof(physical));
    kb7_usb_keyboard_report(physical, 0U);
    if ((last_report[2] & KB7_BIT(5U)) == 0U ||
        (last_report[2] & KB7_BIT(4U)) != 0U) return 3;
    kb7_usb_keyboard_action(5U, false);
    if (last_report[2] != 0U) return 4;

    kb7_usb_keyboard_action(0xe1U, true);
    if (last_report[1] != 2U) return 5;
    kb7_usb_keyboard_action(0xe1U, false);
    if (last_report[1] != 0U) return 6;

    kb7_usb_consumer_usage(0x00b5U);
    kb7_usb_consumer_action(0x00cdU, true);
    kb7_usb_consumer_pulse(0x00e9U);
    if (last_length != KB7_CONSUMER_REPORT_BYTES ||
        last_report[0] != KB7_REPORT_ID_CONSUMER || last_report[1] != 0xcdU ||
        !saw_consumer_pulse) return 7;
    kb7_usb_consumer_action(0x00cdU, false);
    if (last_report[1] != 0xb5U || last_report[2] != 0U) return 8;
    kb7_usb_consumer_action(0x00cdU, true);
    kb7_usb_consumer_usage(0U);
    if (last_report[1] != 0xcdU || last_report[2] != 0U) return 11;
    kb7_usb_consumer_action(0x00cdU, false);
    if (last_report[1] != 0U || last_report[2] != 0U) return 12;

    const int16_t axes[KB7_USB_GAMEPAD_AXIS_COUNT] = {
        -32767, -1234, 0, 1234
    };
    kb7_usb_gamepad_state(UINT16_C(0x8005), 2U, axes, 17U, 99U);
    if (last_length != KB7_USB_GAMEPAD_REPORT_BYTES ||
        last_report[0] != KB7_USB_GAMEPAD_REPORT_ID ||
        last_report[1] != 0x05U || last_report[2] != 0x80U ||
        last_report[3] != 2U || last_report[4] != 0x01U ||
        last_report[5] != 0x80U || last_report[12] != 17U ||
        last_report[13] != 99U) return 9;

    last_length = 0U;
    kb7_usb_gamepad_state(0U, 0U, NULL, 0U, 0U);
    if (last_length != 0U) return 10;

    /* A full Core-0 queue must retain and coalesce every control's latest state. */
    clear_accepted();
    model_queue_capacity = true;
    queue_depth = 8U;
    uint8_t telemetry[KB7_USB_ENDPOINT_SIZE] = {KB7_REPORT_ID_VENDOR, 0xa1U};
    kb7_usb_vendor_telemetry(telemetry, sizeof(telemetry));
    uint8_t travel[KB7_HALL_KEY_COUNT] = {0};
    travel[0] = 0x33U;
    kb7_usb_analog_state(travel);

    memset(physical, 0, sizeof(physical));
    physical[4U >> 3U] = (uint8_t)KB7_BIT(4U & 7U);
    kb7_usb_keyboard_report(physical, 0U);
    memset(physical, 0, sizeof(physical));
    kb7_usb_keyboard_report(physical, 0U);
    kb7_usb_consumer_action(0x00cdU, true);
    kb7_usb_consumer_action(0x00cdU, false);
    const int16_t active_axes[KB7_USB_GAMEPAD_AXIS_COUNT] = {123, -456, 789, -1000};
    const int16_t neutral_axes[KB7_USB_GAMEPAD_AXIS_COUNT] = {0, 0, 0, 0};
    kb7_usb_gamepad_state(1U, 2U, active_axes, 10U, 20U);
    kb7_usb_gamepad_state(0U, 0x0fU, neutral_axes, 0U, 0U);

    uint8_t response[KB7_USB_ENDPOINT_SIZE] = {KB7_REPORT_ID_VENDOR, 0x55U};
    uint8_t other_response[KB7_USB_ENDPOINT_SIZE] = {KB7_REPORT_ID_VENDOR, 0x56U};
    if (!kb7_usb_vendor_response(response, sizeof(response)) ||
        !kb7_usb_vendor_response_pending() ||
        kb7_usb_vendor_response(other_response, sizeof(other_response))) return 13;
    if (accepted_count != 0U) return 14;

    queue_depth = 7U;
    kb7_usb_client_poll();
    if (accepted_count != 1U || accepted[0][0] == KB7_REPORT_ID_ANALOG ||
        (accepted[0][0] == KB7_REPORT_ID_VENDOR && accepted[0][1] == 0xa1U)) return 15;
    queue_depth = 0U;
    for (uint8_t tries = 0U; tries < 20U; ++tries) {
        if (queue_depth != 0U) --queue_depth;
        kb7_usb_client_poll();
    }
    if (kb7_usb_vendor_response_pending() ||
        !saw_report(KB7_REPORT_ID_VENDOR, KB7_USB_ENDPOINT_SIZE, 1U, 0x55U) ||
        !saw_report(KB7_REPORT_ID_KEYBOARD, KB7_KEYBOARD_REPORT_BYTES, 2U, 0U) ||
        !saw_report(KB7_REPORT_ID_CONSUMER, KB7_CONSUMER_REPORT_BYTES, 1U, 0U) ||
        !saw_report(KB7_USB_GAMEPAD_REPORT_ID, KB7_USB_GAMEPAD_REPORT_BYTES, 1U, 0U) ||
        !saw_report(KB7_REPORT_ID_ANALOG, KB7_ANALOG_REPORT_BYTES, 4U, 0x33U)) return 16;

    /* Once accepted, an identical retried command still gets another response. */
    const uint8_t before_retry = accepted_count;
    model_queue_capacity = false;
    if (!kb7_usb_vendor_response(response, sizeof(response)) ||
        accepted_count != (uint8_t)(before_retry + 1U)) return 17;

    /* A consumer pulse accepted just before BUSY must retain its release. */
    clear_accepted();
    successful_budget = 1;
    kb7_usb_consumer_pulse(0x00e9U);
    if (accepted_count != 1U || accepted[0][0] != KB7_REPORT_ID_CONSUMER ||
        accepted[0][1] != 0xe9U) return 18;
    successful_budget = -1;
    kb7_usb_client_poll();
    if (accepted_count != 2U || accepted[1][0] != KB7_REPORT_ID_CONSUMER ||
        accepted[1][1] != 0U || accepted[1][2] != 0U) return 19;

    /* Low-priority telemetry cannot take the only newly available queue slot. */
    clear_accepted();
    model_queue_capacity = true;
    queue_depth = 8U;
    telemetry[1] = 0xa2U;
    kb7_usb_vendor_telemetry(telemetry, sizeof(telemetry));
    physical[4U >> 3U] = (uint8_t)KB7_BIT(4U & 7U);
    kb7_usb_keyboard_report(physical, 0U);
    memset(physical, 0, sizeof(physical));
    kb7_usb_keyboard_report(physical, 0U);
    queue_depth = 7U;
    kb7_usb_client_poll();
    if (accepted_count != 1U || accepted[0][0] != KB7_REPORT_ID_KEYBOARD ||
        accepted[0][2] != 0U) return 20;

    /* A Core-0 data-queue reset replays held state without requiring a change. */
    model_queue_capacity = false;
    memset(physical, 0, sizeof(physical));
    physical[4U >> 3U] = (uint8_t)KB7_BIT(4U & 7U);
    kb7_usb_keyboard_report(physical, 0U);
    clear_accepted();
    ++kb7_shared()->usb_events;
    for (uint8_t tries = 0U; tries < 8U; ++tries) kb7_usb_client_poll();
    if (!saw_report(KB7_REPORT_ID_KEYBOARD, KB7_KEYBOARD_REPORT_BYTES, 2U,
                    (uint8_t)KB7_BIT(4U & 7U))) return 21;

    /* Controller I/O failure has the same retain-and-retry semantics as BUSY. */
    clear_accepted();
    forced_result = KB7_USB_IO;
    memset(physical, 0, sizeof(physical));
    kb7_usb_keyboard_report(physical, 0U);
    if (accepted_count != 0U) return 22;
    forced_result = KB7_USB_OK;
    kb7_usb_client_poll();
    if (accepted_count != 1U || accepted[0][0] != KB7_REPORT_ID_KEYBOARD ||
        accepted[0][2] != 0U) return 23;

    /* Persistent Hall-link loss neutralizes only physical sources; an active
     * touchscreen action remains held and the gamepad converges to neutral. */
    physical[4U >> 3U] = (uint8_t)KB7_BIT(4U & 7U);
    kb7_usb_keyboard_report(physical, 1U);
    kb7_usb_keyboard_action(5U, true);
    kb7_usb_consumer_usage(0x00b5U);
    kb7_usb_consumer_action(0x00cdU, true);
    kb7_usb_gamepad_state(UINT16_C(0x8005), 2U, axes, 17U, 99U);
    clear_accepted();
    kb7_usb_physical_neutral();
    for (uint8_t tries = 0U; tries < 8U; ++tries) kb7_usb_client_poll();
    if (!saw_report(KB7_REPORT_ID_KEYBOARD, KB7_KEYBOARD_REPORT_BYTES, 1U, 0U))
        return 24;
    if (!saw_report(KB7_REPORT_ID_KEYBOARD, KB7_KEYBOARD_REPORT_BYTES, 2U,
                    (uint8_t)KB7_BIT(5U & 7U))) return 25;
    if (!saw_report(KB7_USB_GAMEPAD_REPORT_ID, KB7_USB_GAMEPAD_REPORT_BYTES, 3U, 0x0fU))
        return 26;
    if (!saw_report(KB7_USB_GAMEPAD_REPORT_ID, KB7_USB_GAMEPAD_REPORT_BYTES, 4U, 0U))
        return 27;
    if (!saw_report(KB7_USB_GAMEPAD_REPORT_ID, KB7_USB_GAMEPAD_REPORT_BYTES, 12U, 0U))
        return 28;
    kb7_usb_consumer_action(0x00cdU, false);
    if (!saw_report(KB7_REPORT_ID_CONSUMER, KB7_CONSUMER_REPORT_BYTES, 1U, 0U))
        return 29;
    kb7_usb_keyboard_action(5U, false);
    return 0;
}
