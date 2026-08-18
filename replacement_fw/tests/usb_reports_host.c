#define _GNU_SOURCE
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "kb7/drivers.h"
#include "kb7/runtime.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

static uint8_t last_report[KB7_ANALOG_REPORT_BYTES];
static uint16_t last_length;
static bool saw_consumer_pulse;

static int32_t capture(uint8_t endpoint, const void *data, uint16_t length) {
    if (endpoint != 2U || length > sizeof(last_report)) return -1;
    memcpy(last_report, data, length);
    last_length = length;
    if (length == KB7_CONSUMER_REPORT_BYTES && last_report[0] == KB7_REPORT_ID_CONSUMER &&
        last_report[1] == 0xe9U && last_report[2] == 0U) saw_consumer_pulse = true;
    return 0;
}

int main(void) {
    void *mapping = mmap((void *)(uintptr_t)KB7_SHARED_API_ADDRESS, 4096U,
                         PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (mapping == MAP_FAILED) return 77;
    volatile struct kb7_runtime_api *api = kb7_runtime();
    memset((void *)api, 0, sizeof(*api));
    api->magic = KB7_RUNTIME_MAGIC;
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

    kb7_usb_consumer_action(0x00cdU, true);
    kb7_usb_consumer_pulse(0x00e9U);
    if (last_length != KB7_CONSUMER_REPORT_BYTES ||
        last_report[0] != KB7_REPORT_ID_CONSUMER || last_report[1] != 0xcdU ||
        !saw_consumer_pulse) return 7;
    kb7_usb_consumer_action(0x00cdU, false);
    if (last_report[1] != 0U || last_report[2] != 0U) return 8;
    return 0;
}
