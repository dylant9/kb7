#ifndef KB7_USB_DEVICE_H
#define KB7_USB_DEVICE_H

#include "kb7/platform.h"
#include "kb7/reports.h"

/*
 * A public build has no USB identity assigned to it.  A board profile must
 * provide non-zero IDs and explicitly acknowledge the recovered controller
 * profile before kb7_usb_init() will touch USB MMIO or electrically attach.
 */
#ifndef KB7_USB_VENDOR_ID
#define KB7_USB_VENDOR_ID 0U
#endif
#ifndef KB7_USB_PRODUCT_ID
#define KB7_USB_PRODUCT_ID 0U
#endif
#ifndef KB7_USB_DEVICE_RELEASE
#define KB7_USB_DEVICE_RELEASE 0x0100U
#endif
#ifndef KB7_USB_BOARD_PROFILE_VERIFIED
#define KB7_USB_BOARD_PROFILE_VERIFIED 0
#endif
#ifndef KB7_USB_MAX_POWER_MA
#define KB7_USB_MAX_POWER_MA 100U
#endif
#ifndef KB7_USB_MANUFACTURER_STRING
#define KB7_USB_MANUFACTURER_STRING "Open Firmware Project"
#endif
#ifndef KB7_USB_PRODUCT_STRING
#define KB7_USB_PRODUCT_STRING "KB7 Compatible Keyboard"
#endif

#define KB7_USB_ENDPOINT_SIZE 64U
#define KB7_USB_HID_INTERFACE 0U
#define KB7_USB_DATA_ENDPOINT 2U
#define KB7_USB_DATA_IN_ADDRESS 0x82U
#define KB7_USB_DATA_OUT_ADDRESS 0x02U
#define KB7_USB_GAMEPAD_REPORT_ID 0x07U
#define KB7_USB_GAMEPAD_REPORT_BYTES 14U
#define KB7_USB_GAMEPAD_AXIS_COUNT 4U

enum kb7_usb_result {
    KB7_USB_OK = 0,
    KB7_USB_INVALID = -1,
    KB7_USB_UNAVAILABLE = -2,
    KB7_USB_BUSY = -3,
    KB7_USB_IO = -4,
    KB7_USB_STALL = -5,
    KB7_USB_NEED_OUT_DATA = 1,
};

enum kb7_usb_device_state {
    KB7_USB_DETACHED = 0,
    KB7_USB_DEFAULT,
    KB7_USB_ADDRESSED,
    KB7_USB_CONFIGURED,
    KB7_USB_SUSPENDED,
};

struct KB7_PACKED kb7_usb_setup_packet {
    uint8_t request_type;
    uint8_t request;
    uint16_t value;
    uint16_t index;
    uint16_t length;
};

struct kb7_usb_control_response {
    const uint8_t *data;
    uint16_t length;
    uint16_t expected_out_length;
};

struct KB7_PACKED kb7_usb_gamepad_report {
    uint8_t report_id;
    uint16_t buttons;
    uint8_t hat;
    int16_t axes[KB7_USB_GAMEPAD_AXIS_COUNT];
    uint8_t left_trigger;
    uint8_t right_trigger;
};

_Static_assert(sizeof(struct kb7_usb_setup_packet) == 8U,
               "USB SETUP packets are eight bytes");
_Static_assert(sizeof(struct kb7_usb_gamepad_report) == KB7_USB_GAMEPAD_REPORT_BYTES,
               "gamepad report and HID descriptor must agree");
_Static_assert(KB7_USB_GAMEPAD_REPORT_ID != KB7_REPORT_ID_KEYBOARD &&
               KB7_USB_GAMEPAD_REPORT_ID != KB7_REPORT_ID_CONSUMER &&
               KB7_USB_GAMEPAD_REPORT_ID != KB7_REPORT_ID_ANALOG &&
               KB7_USB_GAMEPAD_REPORT_ID != KB7_REPORT_ID_VENDOR,
               "gamepad report ID must be unique");
_Static_assert(KB7_USB_MAX_POWER_MA <= 510U,
               "USB 2.0 bMaxPower cannot encode more than 510 mA");
_Static_assert(KB7_USB_VENDOR_ID <= 0xffffU && KB7_USB_PRODUCT_ID <= 0xffffU &&
               KB7_USB_DEVICE_RELEASE <= 0xffffU,
               "USB descriptor identity fields are 16-bit values");

/* Pure control-request engine, also used by the live EP0 state machine. */
int32_t kb7_usb_control_request(const struct kb7_usb_setup_packet *setup,
                                const uint8_t *out_data, uint16_t out_length,
                                struct kb7_usb_control_response *response);

/* IRQ6 may call this directly; kb7_usb_poll() invokes the same dispatcher. */
void kb7_usb_irq_handler(void);

enum kb7_usb_device_state kb7_usb_state(void);
bool kb7_usb_configured(void);
uint8_t kb7_usb_keyboard_leds(void);

/* Complete standard gamepad report helper for the Core-1 client. */
void kb7_usb_gamepad_state(uint16_t buttons, uint8_t hat,
                           const int16_t axes[KB7_USB_GAMEPAD_AXIS_COUNT],
                           uint8_t left_trigger, uint8_t right_trigger);

/*
 * Core-1 report scheduler.  State reports are coalesced to the newest value
 * and retained until Core 0 accepts them.  Command responses are never
 * overwritten while pending; telemetry may be coalesced under back-pressure.
 */
void kb7_usb_client_poll(void);
void kb7_usb_physical_neutral(void);
void kb7_usb_analog_state(const uint8_t *travel);
bool kb7_usb_vendor_response(const void *report, uint16_t length);
bool kb7_usb_vendor_response_pending(void);
void kb7_usb_vendor_telemetry(const void *report, uint16_t length);

/* Vendor output is published to the shared Core-0/Core-1 host mailbox. */
void kb7_usb_vendor_output(const uint8_t *report, uint16_t length);
/* The LED hook remains weak so a board integration may drive indicator LEDs. */
void kb7_usb_keyboard_led_output(uint8_t leds);

#if defined(KB7_USB_TEST)
/* Deterministic host/MMIO-model hooks; never compiled into production builds. */
void kb7_usb_test_reset(void);
void kb7_usb_test_bus_reset(void);
void kb7_usb_test_set_configured(bool configured);
void kb7_usb_test_complete_in(uint8_t endpoint);
bool kb7_usb_test_begin_control(const struct kb7_usb_setup_packet *setup);
bool kb7_usb_test_complete_out(uint8_t endpoint, const void *data, uint16_t length);
void kb7_usb_test_global_events(uint32_t events);
bool kb7_usb_test_apply_halt(uint8_t address, bool set);
uint8_t kb7_usb_test_queue_depth(uint8_t endpoint);
uint16_t kb7_usb_test_active_length(uint8_t endpoint);
const uint8_t *kb7_usb_test_active_data(uint8_t endpoint);
bool kb7_usb_test_out_active(uint8_t endpoint);
const uint8_t *kb7_usb_device_descriptor_data(uint16_t *length);
const uint8_t *kb7_usb_configuration_descriptor_data(uint16_t *length);
const uint8_t *kb7_usb_report_descriptor_data(uint16_t *length);
#endif

#endif
