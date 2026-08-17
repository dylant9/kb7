#include "kb7/drivers.h"
#include "kb7/runtime.h"

void kb7_usb_keyboard_report(const uint8_t bits[19], uint8_t modifiers) {
    uint8_t report[21];
    report[0] = 0x04U;
    report[1] = modifiers;
    kb7_memcpy(&report[2], bits, 19U);
    (void)kb7_runtime()->usb_send(2U, report, sizeof(report));
}

void kb7_usb_consumer_usage(uint16_t usage) {
    const uint8_t report[3] = {0x03U, (uint8_t)usage, (uint8_t)(usage >> 8U)};
    (void)kb7_runtime()->usb_send(2U, report, sizeof(report));
}
