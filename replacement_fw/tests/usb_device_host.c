#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "kb7/drivers.h"
#include "kb7/regs.h"
#include "kb7/usb_device.h"

#define ARRAY_LEN(a) (sizeof(a) / sizeof((a)[0]))

struct mmio_write { uintptr_t address; uint32_t value; };
static struct mmio_write writes[128];
static size_t write_count;
static uint32_t aux_control;
static uint32_t usb_configuration;
static uint8_t vendor_output[KB7_USB_ENDPOINT_SIZE];
static uint16_t vendor_output_length;
static uint8_t keyboard_leds;

uint32_t kb7_usb_test_mmio_read(uintptr_t address) {
    if (address == SNC_USB_BASE + UINT32_C(0x1f8)) return aux_control;
    if (address == SNC_USB_BASE + SNC_USB_CONFIGURATION) return usb_configuration;
    if (address == SNC_USB_BASE + SNC_USB_TRANSACTION_STATUS) return KB7_BIT(8);
    return 0U;
}

void kb7_usb_test_mmio_write(uintptr_t address, uint32_t value) {
    if (write_count < ARRAY_LEN(writes)) {
        writes[write_count].address = address;
        writes[write_count].value = value;
        ++write_count;
    }
    if (address == SNC_USB_BASE + UINT32_C(0x1f8)) aux_control = value;
}

void kb7_usb_vendor_output(const uint8_t *report, uint16_t length) {
    if (report == NULL || length > sizeof(vendor_output)) return;
    memcpy(vendor_output, report, length);
    vendor_output_length = length;
}

void kb7_usb_keyboard_led_output(uint8_t leds) {
    keyboard_leds = leds;
}

static struct kb7_usb_setup_packet setup(uint8_t type, uint8_t request,
                                         uint16_t value, uint16_t index,
                                         uint16_t length) {
    const struct kb7_usb_setup_packet result = {type, request, value, index, length};
    return result;
}

static int request(const struct kb7_usb_setup_packet *packet,
                   const uint8_t *out, uint16_t out_length,
                   struct kb7_usb_control_response *response) {
    return kb7_usb_control_request(packet, out, out_length, response);
}

struct report_bits {
    uint32_t input[256];
    uint32_t output[256];
};

static bool parse_report_descriptor(const uint8_t *descriptor, uint16_t length,
                                    struct report_bits *bits) {
    uint32_t report_size = 0U;
    uint32_t report_count = 0U;
    uint8_t report_id = 0U;
    memset(bits, 0, sizeof(*bits));
    for (uint16_t offset = 0U; offset < length;) {
        const uint8_t prefix = descriptor[offset++];
        if (prefix == 0xfeU) return false;
        uint8_t data_bytes = prefix & 3U;
        if (data_bytes == 3U) data_bytes = 4U;
        if ((uint16_t)(length - offset) < data_bytes) return false;
        uint32_t value = 0U;
        for (uint8_t index = 0U; index < data_bytes; ++index)
            value |= (uint32_t)descriptor[offset + index] << (index * 8U);
        offset = (uint16_t)(offset + data_bytes);
        const uint8_t type = (prefix >> 2U) & 3U;
        const uint8_t tag = prefix >> 4U;
        if (type == 1U && tag == 7U) report_size = value;
        if (type == 1U && tag == 8U) report_id = (uint8_t)value;
        if (type == 1U && tag == 9U) report_count = value;
        if (type == 0U && tag == 8U) bits->input[report_id] += report_size * report_count;
        if (type == 0U && tag == 9U) bits->output[report_id] += report_size * report_count;
    }
    return true;
}

static int descriptors_and_enumeration(void) {
    struct kb7_usb_control_response response;
    struct kb7_usb_setup_packet packet = setup(0x80U, 6U, 0x0100U, 0U, 8U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK || response.length != 8U ||
        response.data == NULL || response.data[0] != 18U || response.data[1] != 1U)
        return 1;

    packet.length = 64U;
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK || response.length != 18U ||
        response.data[8] != 0xfeU || response.data[9] != 0xcaU ||
        response.data[10] != 0x01U || response.data[11] != 0x40U) return 2;

    packet = setup(0x80U, 6U, 0x0200U, 0U, 255U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK || response.length != 41U ||
        response.data[2] != 41U || response.data[4] != 1U ||
        response.data[29] != 0x82U || response.data[36] != 0x02U) return 3;

    packet = setup(0x81U, 6U, 0x2100U, 0U, 9U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK || response.length != 9U ||
        response.data[1] != 0x21U) return 4;

    packet = setup(0x81U, 6U, 0x2200U, 0U, 1024U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK || response.length < 100U)
        return 5;
    struct report_bits bits;
    if (!parse_report_descriptor(response.data, response.length, &bits) ||
        bits.input[KB7_REPORT_ID_KEYBOARD] != 160U ||
        bits.output[KB7_REPORT_ID_KEYBOARD] != 8U ||
        bits.input[KB7_REPORT_ID_CONSUMER] != 16U ||
        bits.input[KB7_REPORT_ID_ANALOG] != 504U ||
        bits.input[KB7_USB_GAMEPAD_REPORT_ID] != 104U ||
        bits.input[KB7_REPORT_ID_VENDOR] != 504U ||
        bits.output[KB7_REPORT_ID_VENDOR] != 504U) return 6;

    packet = setup(0x80U, 6U, 0x0300U, 0U, 64U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK || response.length != 4U ||
        response.data[2] != 0x09U || response.data[3] != 0x04U) return 7;
    packet.index = 0x0409U;
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 8;
    packet = setup(0x80U, 6U, 0x0301U, 0x0409U, 64U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK ||
        response.data[1] != 3U || response.length < 10U) return 9;
    packet.value = 0x0309U;
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 10;

    packet = setup(0x82U, 6U, 0x0100U, 0U, 18U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 11;
    packet = setup(0x80U, 6U, 0x2200U, 0U, 255U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 12;

    /* The configuration does not advertise remote wakeup, so feature 1 stalls. */
    packet = setup(0x00U, 3U, 1U, 0U, 0U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 13;

    packet = setup(0x00U, 5U, 128U, 0U, 0U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 14;
    packet.value = 42U;
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK) return 15;

    packet = setup(0x00U, 9U, 1U, 0U, 0U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK ||
        kb7_usb_state() != KB7_USB_CONFIGURED) return 16;
    packet = setup(0x80U, 8U, 0U, 0U, 1U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK ||
        response.length != 1U || response.data[0] != 1U) return 17;
    packet = setup(0x01U, 11U, 1U, 0U, 0U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 18;
    packet.value = 0U;
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK) return 19;
    return 0;
}

static int hid_control_and_malformed_input(void) {
    struct kb7_usb_control_response response;
    struct kb7_usb_setup_packet packet = setup(
        0x21U, 0x0aU, (uint16_t)((33U << 8U) | KB7_REPORT_ID_KEYBOARD), 0U, 0U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK) return 1;
    packet = setup(0xa1U, 0x02U, KB7_REPORT_ID_KEYBOARD, 0U, 1U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK || response.data[0] != 33U)
        return 2;
    packet.value = 0x77U;
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 3;

    packet = setup(0x21U, 0x0bU, 0U, 0U, 0U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK) return 4;
    packet = setup(0xa1U, 0x03U, 0U, 0U, 1U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK || response.data[0] != 0U)
        return 5;
    packet = setup(0x21U, 0x0bU, 2U, 0U, 0U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 6;

    packet = setup(0x21U, 0x09U, 0x025cU, 0U, KB7_USB_ENDPOINT_SIZE);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_NEED_OUT_DATA ||
        response.expected_out_length != KB7_USB_ENDPOINT_SIZE) return 7;
    uint8_t vendor[KB7_USB_ENDPOINT_SIZE] = {0};
    vendor[0] = KB7_REPORT_ID_VENDOR;
    vendor[3] = 0xa5U;
    if (request(&packet, vendor, sizeof(vendor), &response) != KB7_USB_OK ||
        vendor_output_length != sizeof(vendor) || vendor_output[3] != 0xa5U) return 8;
    vendor[0] = 0U;
    if (request(&packet, vendor, sizeof(vendor), &response) != KB7_USB_STALL) return 9;
    if (request(&packet, vendor, sizeof(vendor) - 1U, &response) != KB7_USB_STALL)
        return 10;

    packet = setup(0x21U, 0x09U, 0x0204U, 0U, 2U);
    const uint8_t leds[2] = {KB7_REPORT_ID_KEYBOARD, 0xffU};
    if (request(&packet, NULL, 0U, &response) != KB7_USB_NEED_OUT_DATA ||
        request(&packet, leds, sizeof(leds), &response) != KB7_USB_OK ||
        keyboard_leds != 0x1fU || kb7_usb_keyboard_leds() != 0x1fU) return 11;

    packet = setup(0xa1U, 0x01U, 0x0104U, 0U, 255U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK ||
        response.length != KB7_KEYBOARD_REPORT_BYTES ||
        response.data[0] != KB7_REPORT_ID_KEYBOARD) return 12;
    packet.value = 0x0304U;
    if (request(&packet, NULL, 0U, &response) != KB7_USB_STALL) return 13;

    if (kb7_usb_control_request(NULL, NULL, 0U, &response) != KB7_USB_INVALID ||
        kb7_usb_control_request(&packet, NULL, 1U, &response) != KB7_USB_INVALID ||
        kb7_usb_control_request(&packet, NULL, 0U, NULL) != KB7_USB_INVALID) return 14;
    return 0;
}

static int queue_lifecycle(void) {
    kb7_usb_test_reset();
    kb7_usb_test_set_configured(true);
    uint8_t keyboard[KB7_KEYBOARD_REPORT_BYTES] = {KB7_REPORT_ID_KEYBOARD};
    keyboard[2] = 0x10U;
    uint8_t consumer[KB7_CONSUMER_REPORT_BYTES] = {KB7_REPORT_ID_CONSUMER, 0xe9U, 0U};
    if (kb7_usb_send(2U, keyboard, sizeof(keyboard)) != KB7_USB_OK ||
        kb7_usb_test_queue_depth(2U) != 1U ||
        kb7_usb_test_active_length(2U) != sizeof(keyboard) ||
        memcmp(kb7_usb_test_active_data(2U), keyboard, sizeof(keyboard)) != 0) return 1;
    keyboard[2] = 0U; /* Queue owns its copy. */
    if (kb7_usb_test_active_data(2U)[2] != 0x10U) return 2;
    if (kb7_usb_send(2U, consumer, sizeof(consumer)) != KB7_USB_OK ||
        kb7_usb_test_queue_depth(2U) != 2U) return 3;
    for (uint8_t queued = 2U; queued < 8U; ++queued) {
        if (kb7_usb_send(2U, consumer, sizeof(consumer)) != KB7_USB_OK) return 4;
    }
    if (kb7_usb_test_queue_depth(2U) != 8U ||
        kb7_usb_send(2U, consumer, sizeof(consumer)) != KB7_USB_BUSY) return 5;
    kb7_usb_test_complete_in(2U);
    if (kb7_usb_test_queue_depth(2U) != 7U ||
        kb7_usb_test_active_data(2U)[0] != KB7_REPORT_ID_CONSUMER) return 6;
    for (uint8_t queued = 7U; queued != 0U; --queued) kb7_usb_test_complete_in(2U);
    if (kb7_usb_test_queue_depth(2U) != 0U) return 7;

    uint8_t bad[8] = {0x7fU};
    if (kb7_usb_send(2U, bad, sizeof(bad)) != KB7_USB_INVALID ||
        kb7_usb_send(2U, keyboard, sizeof(keyboard) - 1U) != KB7_USB_INVALID ||
        kb7_usb_send(1U, keyboard, sizeof(keyboard)) != KB7_USB_UNAVAILABLE ||
        kb7_usb_send(2U, NULL, sizeof(keyboard)) != KB7_USB_INVALID) return 8;

    struct kb7_usb_control_response response;
    struct kb7_usb_setup_packet packet = setup(0x02U, 3U, 0U, 0x82U, 0U);
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK ||
        kb7_usb_send(2U, consumer, sizeof(consumer)) != KB7_USB_UNAVAILABLE) return 9;
    packet.request = 1U;
    if (request(&packet, NULL, 0U, &response) != KB7_USB_OK ||
        kb7_usb_send(2U, consumer, sizeof(consumer)) != KB7_USB_OK) return 10;

    kb7_usb_test_bus_reset();
    if (kb7_usb_state() != KB7_USB_DEFAULT || kb7_usb_configured() ||
        kb7_usb_test_queue_depth(2U) != 0U) return 11;
    return 0;
}

static int interrupt_out_validation(void) {
    kb7_usb_test_reset();
    kb7_usb_test_set_configured(true);

    uint8_t report[KB7_USB_ENDPOINT_SIZE] = {0};
    report[0] = KB7_REPORT_ID_VENDOR;
    report[7] = 0xa6U;
    vendor_output_length = 0U;
    if (!kb7_usb_test_complete_out(KB7_USB_DATA_ENDPOINT, report,
                                   KB7_USB_ENDPOINT_SIZE - 1U) ||
        vendor_output_length != 0U ||
        !kb7_usb_test_out_active(KB7_USB_DATA_ENDPOINT)) return 1;
    report[0] = 0x7fU;
    if (!kb7_usb_test_complete_out(KB7_USB_DATA_ENDPOINT, report, sizeof(report)) ||
        vendor_output_length != 0U ||
        !kb7_usb_test_out_active(KB7_USB_DATA_ENDPOINT)) return 2;
    report[0] = KB7_REPORT_ID_VENDOR;
    if (!kb7_usb_test_complete_out(KB7_USB_DATA_ENDPOINT, report, sizeof(report)) ||
        vendor_output_length != sizeof(report) || vendor_output[7] != 0xa6U ||
        !kb7_usb_test_out_active(KB7_USB_DATA_ENDPOINT)) return 3;
    return 0;
}

static int ep0_short_packet_termination(void) {
    kb7_usb_test_reset();
    const struct kb7_usb_setup_packet zero_length_in = setup(0x80U, 6U, 0x0100U, 0U, 0U);
    if (!kb7_usb_test_begin_control(&zero_length_in) ||
        kb7_usb_test_queue_depth(0U) != 0U || !kb7_usb_test_out_active(0U)) return 1;
    const struct kb7_usb_setup_packet packet = setup(
        0xa1U, 0x01U, 0x015cU, 0U, KB7_USB_ENDPOINT_SIZE + 1U);
    if (!kb7_usb_test_begin_control(&packet) ||
        kb7_usb_test_queue_depth(0U) != 1U ||
        kb7_usb_test_active_length(0U) != KB7_USB_ENDPOINT_SIZE) return 2;
    kb7_usb_test_complete_in(0U);
    if (kb7_usb_test_queue_depth(0U) != 1U ||
        kb7_usb_test_active_length(0U) != 0U) return 3;
    kb7_usb_test_complete_in(0U);
    if (kb7_usb_test_queue_depth(0U) != 0U || !kb7_usb_test_out_active(0U)) return 4;

    const struct kb7_usb_setup_packet set_configuration = setup(0x00U, 9U, 1U, 0U, 0U);
    if (!kb7_usb_test_begin_control(&set_configuration) ||
        kb7_usb_test_queue_depth(0U) != 1U ||
        kb7_usb_test_active_length(0U) != 0U) return 5;
    kb7_usb_test_complete_in(0U);
    if (kb7_usb_test_queue_depth(0U) != 0U || !kb7_usb_test_out_active(0U)) return 6;
    return 0;
}

static int global_event_lifecycle(void) {
    kb7_usb_test_reset();
    kb7_usb_test_set_configured(true);
    usb_configuration = 4U << 4U;
    kb7_usb_test_global_events(KB7_BIT(18));
    if (kb7_usb_state() != KB7_USB_SUSPENDED) return 1;
    kb7_usb_test_global_events(KB7_BIT(17));
    if (kb7_usb_state() != KB7_USB_CONFIGURED) return 2;
    kb7_usb_test_global_events(KB7_BIT(21));
    if (kb7_usb_state() != KB7_USB_DETACHED) return 3;
    kb7_usb_test_global_events(KB7_BIT(20));
    if (kb7_usb_state() != KB7_USB_DEFAULT) return 4;
    kb7_usb_test_set_configured(true);
    kb7_usb_test_global_events(KB7_BIT(16));
    if (kb7_usb_state() != KB7_USB_DEFAULT || kb7_usb_configured()) return 5;
    return 0;
}

static int endpoint_halt_commands(void) {
    kb7_usb_test_reset();
    write_count = 0U;
    if (!kb7_usb_test_apply_halt(KB7_USB_DATA_IN_ADDRESS, true) || write_count != 2U ||
        writes[0].address != SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT ||
        writes[0].value != KB7_USB_DATA_IN_ADDRESS ||
        writes[1].address != SNC_USB_BASE + UINT32_C(0x28) ||
        writes[1].value != KB7_BIT(1)) return 1;
    write_count = 0U;
    if (!kb7_usb_test_apply_halt(KB7_USB_DATA_IN_ADDRESS, false) || write_count != 5U ||
        writes[2].address != SNC_USB_BASE + UINT32_C(0x28) ||
        writes[2].value != KB7_BIT(0) ||
        writes[3].address != SNC_USB_BASE + UINT32_C(0x28) ||
        writes[3].value != KB7_BIT(2)) return 2;
    return 0;
}

static int controller_initialization(void) {
    memset(writes, 0, sizeof(writes));
    write_count = 0U;
    aux_control = 0U;
    if (!kb7_usb_init() || write_count < 16U) return 1;
    const struct mmio_write expected[] = {
        {SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, 0x00000020U},
        {SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, 0x00020000U},
        {SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, 0x00080000U},
        {SNC_USB_BASE + SNC_USB_GLOBAL_ACK, 0xffffffffU},
        {SNC_USB_BASE + SNC_USB_GLOBAL_EVENT_ENABLE, 0x07370800U},
        {SNC_USB_BASE + SNC_USB_GLOBAL_CONFIG, 0x00010001U},
        {SNC_USB_BASE + 0x1f8U, 0x0000ffffU},
        {SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, 0x00004200U},
        {SNC_SYS1_BASE + SNC_SYS1_USB_CONTROL, 0x28U},
    };
    for (size_t index = 0U; index < ARRAY_LEN(expected); ++index) {
        if (writes[index].address != expected[index].address ||
            writes[index].value != expected[index].value) return (int)(2U + index);
    }
    bool saw_ep0_out = false;
    bool saw_ep0_in = false;
    for (size_t index = 0U; index + 2U < write_count; ++index) {
        if (writes[index].address != SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT) continue;
        if (writes[index].value == 0U && writes[index + 1U].value == 0x00400001U)
            saw_ep0_out = true;
        if (writes[index].value == 0x80U && writes[index + 1U].value == 0x00400001U)
            saw_ep0_in = true;
    }
    if (!saw_ep0_out || !saw_ep0_in) return 20;
    return 0;
}

int main(void) {
    kb7_usb_test_reset();
    int result = descriptors_and_enumeration();
    if (result != 0) return 10 + result;
    result = hid_control_and_malformed_input();
    if (result != 0) return 40 + result;
    result = queue_lifecycle();
    if (result != 0) return 70 + result;
    result = interrupt_out_validation();
    if (result != 0) return 85 + result;
    result = ep0_short_packet_termination();
    if (result != 0) return 90 + result;
    result = global_event_lifecycle();
    if (result != 0) return 95 + result;
    result = endpoint_halt_commands();
    if (result != 0) return 98 + result;
    result = controller_initialization();
    if (result != 0) return 100 + result;
    return 0;
}
