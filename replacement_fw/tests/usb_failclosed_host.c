#include <stdint.h>

#include "kb7/drivers.h"
#include "kb7/usb_device.h"

static uint32_t mmio_accesses;

uint32_t kb7_usb_test_mmio_read(uintptr_t address) {
    (void)address;
    ++mmio_accesses;
    return 0U;
}

void kb7_usb_test_mmio_write(uintptr_t address, uint32_t value) {
    (void)address;
    (void)value;
    ++mmio_accesses;
}

int main(void) {
    if (KB7_USB_VENDOR_ID != 0U || KB7_USB_PRODUCT_ID != 0U ||
        KB7_USB_BOARD_PROFILE_VERIFIED != 0) return 1;
    if (kb7_usb_init()) return 2;
    if (mmio_accesses != 0U || kb7_usb_state() != KB7_USB_DETACHED ||
        kb7_usb_configured()) return 3;
    const uint8_t report[KB7_CONSUMER_REPORT_BYTES] = {KB7_REPORT_ID_CONSUMER, 0U, 0U};
    if (kb7_usb_send(KB7_USB_DATA_ENDPOINT, report, sizeof(report)) !=
        KB7_USB_UNAVAILABLE) return 4;
    return 0;
}
