#include "kb7/drivers.h"

/*
 * The public tree does not claim a USB VID/PID and does not contain the
 * unvalidated controller bring-up sequence. Transport remains fail-closed.
 */

bool kb7_usb_init(void) {
    return false;
}

void kb7_usb_poll(void) {
}

int32_t kb7_usb_send(uint8_t endpoint, const void *data, uint16_t length) {
    (void)endpoint;
    (void)data;
    (void)length;
    return -2;
}

void kb7_usb_keyboard_report(const uint8_t bits[19], uint8_t modifiers) {
    (void)bits;
    (void)modifiers;
}

void kb7_usb_consumer_usage(uint16_t usage) {
    (void)usage;
}
