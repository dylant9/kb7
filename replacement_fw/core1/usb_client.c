#include "kb7/drivers.h"
#include "kb7/runtime.h"

static uint8_t physical_bits[19];
static uint8_t physical_modifiers;
static uint8_t action_bits[19];
static uint8_t action_modifiers;
static uint16_t action_consumer_usage;

static void send_keyboard(void) {
    uint8_t report[KB7_KEYBOARD_REPORT_BYTES];
    report[0] = KB7_REPORT_ID_KEYBOARD;
    report[1] = physical_modifiers | action_modifiers;
    for (size_t index = 0U; index < sizeof(physical_bits); ++index) {
        report[index + 2U] = physical_bits[index] | action_bits[index];
    }
    (void)kb7_runtime()->usb_send(2U, report, sizeof(report));
}

void kb7_usb_keyboard_report(const uint8_t bits[19], uint8_t modifiers) {
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

void kb7_usb_consumer_usage(uint16_t usage) {
    const uint8_t report[KB7_CONSUMER_REPORT_BYTES] = {
        KB7_REPORT_ID_CONSUMER, (uint8_t)usage, (uint8_t)(usage >> 8U)
    };
    (void)kb7_runtime()->usb_send(2U, report, sizeof(report));
}

void kb7_usb_consumer_action(uint16_t usage, bool pressed) {
    action_consumer_usage = pressed ? usage : 0U;
    kb7_usb_consumer_usage(action_consumer_usage);
}

void kb7_usb_consumer_pulse(uint16_t usage) {
    kb7_usb_consumer_usage(usage);
    kb7_usb_consumer_usage(action_consumer_usage);
}
