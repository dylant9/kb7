#include "kb7/drivers.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"
#include "kb7/usb_device.h"

/* Standard requests and descriptor types from USB 2.0 chapter 9. */
#define USB_REQ_GET_STATUS 0x00U
#define USB_REQ_CLEAR_FEATURE 0x01U
#define USB_REQ_SET_FEATURE 0x03U
#define USB_REQ_SET_ADDRESS 0x05U
#define USB_REQ_GET_DESCRIPTOR 0x06U
#define USB_REQ_GET_CONFIGURATION 0x08U
#define USB_REQ_SET_CONFIGURATION 0x09U
#define USB_REQ_GET_INTERFACE 0x0aU
#define USB_REQ_SET_INTERFACE 0x0bU

#define USB_DESC_DEVICE 0x01U
#define USB_DESC_CONFIGURATION 0x02U
#define USB_DESC_STRING 0x03U
#define USB_DESC_HID 0x21U
#define USB_DESC_REPORT 0x22U

#define USB_HID_GET_REPORT 0x01U
#define USB_HID_GET_IDLE 0x02U
#define USB_HID_GET_PROTOCOL 0x03U
#define USB_HID_SET_REPORT 0x09U
#define USB_HID_SET_IDLE 0x0aU
#define USB_HID_SET_PROTOCOL 0x0bU

#define USB_DIRECTION_IN 0x80U
#define USB_TYPE_MASK 0x60U
#define USB_TYPE_STANDARD 0x00U
#define USB_TYPE_CLASS 0x20U
#define USB_RECIPIENT_MASK 0x1fU
#define USB_RECIPIENT_DEVICE 0x00U
#define USB_RECIPIENT_INTERFACE 0x01U
#define USB_RECIPIENT_ENDPOINT 0x02U

#define USB_FEATURE_ENDPOINT_HALT 0U
#define USB_CONTROLLER_ENDPOINT_CONTROL UINT32_C(0x20)
#define USB_CONTROLLER_ENDPOINT_STATE UINT32_C(0x28)
#define USB_CONTROLLER_ENDPOINT_START UINT32_C(0x38)
#define USB_CONTROLLER_AUX_CONTROL UINT32_C(0x1f8)
#define USB_CONTROLLER_EP0_SETUP KB7_BIT(31)
#define USB_CONTROLLER_EP_EVENT_A KB7_BIT(3)
#define USB_CONTROLLER_EP_EVENT_B KB7_BIT(2)
#define USB_CONTROLLER_EP_IN_COMPLETE KB7_BIT(4)
#define USB_CONTROLLER_EP_ERROR KB7_BIT(7)

#define USB_EVENT_RESET KB7_BIT(16)
#define USB_EVENT_RESUME KB7_BIT(17)
#define USB_EVENT_STATE_CHANGE KB7_BIT(18)
#define USB_EVENT_CONNECT KB7_BIT(20)
#define USB_EVENT_DISCONNECT KB7_BIT(21)
#define USB_TRANSACTION_READY KB7_BIT(8)

#define USB_ENDPOINT_QUEUE_DEPTH 8U
#define USB_ENDPOINT_COUNT 5U
#define USB_DMA_VALID KB7_BIT(28)
#define USB_DMA_LENGTH_MASK UINT32_C(0x0001ffff)
#define USB_DMA_DATA_CONTROL UINT32_C(0x424)
#define USB_DMA_END_CONTROL UINT32_C(0x1812)
#define USB_CONTROLLER_TIMEOUT UINT32_C(100000)

struct KB7_PACKED usb_device_descriptor {
    uint8_t length;
    uint8_t type;
    uint16_t usb_release;
    uint8_t device_class;
    uint8_t device_subclass;
    uint8_t device_protocol;
    uint8_t endpoint0_size;
    uint16_t vendor;
    uint16_t product;
    uint16_t device_release;
    uint8_t manufacturer;
    uint8_t product_string;
    uint8_t serial;
    uint8_t configurations;
};

struct usb_dma_descriptor {
    uint32_t buffer;
    uint32_t length;
    uint32_t control;
};

struct usb_in_endpoint {
    uint8_t data[USB_ENDPOINT_QUEUE_DEPTH][KB7_USB_ENDPOINT_SIZE];
    uint16_t length[USB_ENDPOINT_QUEUE_DEPTH];
    uint8_t head;
    uint8_t tail;
    uint8_t count;
    bool active;
    struct usb_dma_descriptor dma[2] __attribute__((aligned(16)));
};

struct usb_out_endpoint {
    uint8_t data[KB7_USB_ENDPOINT_SIZE];
    uint16_t requested;
    uint16_t completed;
    bool active;
    struct usb_dma_descriptor dma[2] __attribute__((aligned(16)));
};

struct usb_ep0_transfer {
    const uint8_t *next;
    uint16_t remaining;
    uint16_t requested;
    struct kb7_usb_setup_packet pending_setup;
    uint16_t pending_out;
    uint8_t pending_address;
    bool address_pending;
    bool data_in;
    bool needs_zlp;
    bool status_in;
};

__attribute__((used, section(".rodata.usb_descriptors")))
static const struct usb_device_descriptor device_descriptor = {
    18U, USB_DESC_DEVICE, 0x0200U, 0U, 0U, 0U, KB7_USB_ENDPOINT_SIZE,
    (uint16_t)KB7_USB_VENDOR_ID, (uint16_t)KB7_USB_PRODUCT_ID,
    (uint16_t)KB7_USB_DEVICE_RELEASE, 1U, 2U, 0U, 1U,
};

/*
 * Four project-owned report contracts share one HID interface:
 *   04: keyboard, 21 bytes on wire (modifiers + 152 usage bits)
 *   05: consumer usage, 3 bytes on wire
 *   06: vendor-defined Hall telemetry, 64 bytes on wire
 *   07: gamepad, 14 bytes on wire (16 buttons, hat, sticks and triggers)
 *   5c: bidirectional vendor control, 64 bytes on wire
 */
__attribute__((used, section(".rodata.usb_descriptors")))
static const uint8_t report_descriptor[] = {
    /* NKRO keyboard and its five LED output bits. */
    0x05,0x01, 0x09,0x06, 0xa1,0x01, 0x85,KB7_REPORT_ID_KEYBOARD,
    0x05,0x07, 0x19,0xe0, 0x29,0xe7, 0x15,0x00, 0x25,0x01,
    0x75,0x01, 0x95,0x08, 0x81,0x02,
    0x19,0x00, 0x29,0x97, 0x75,0x01, 0x95,0x98, 0x81,0x02,
    0x05,0x08, 0x19,0x01, 0x29,0x05, 0x95,0x05, 0x75,0x01,
    0x91,0x02, 0x95,0x03, 0x91,0x03, 0xc0,

    /* One 16-bit Consumer-page usage. */
    0x05,0x0c, 0x09,0x01, 0xa1,0x01, 0x85,KB7_REPORT_ID_CONSUMER,
    0x15,0x00, 0x26,0xff,0xff, 0x19,0x00, 0x2a,0xff,0xff,
    0x75,0x10, 0x95,0x01, 0x81,0x00, 0xc0,

    /* Existing 63-byte Hall telemetry payload, described as vendor data. */
    0x06,0x00,0xff, 0x09,0x04, 0xa1,0x01, 0x85,KB7_REPORT_ID_ANALOG,
    0x09,0x05, 0x15,0x00, 0x26,0xff,0x00,
    0x75,0x08, 0x95,0x3f, 0x81,0x02, 0xc0,

    /* 16 buttons, hat, four signed stick axes and two unsigned triggers. */
    0x05,0x01, 0x09,0x05, 0xa1,0x01, 0x85,KB7_USB_GAMEPAD_REPORT_ID,
    0x05,0x09, 0x19,0x01, 0x29,0x10, 0x15,0x00, 0x25,0x01,
    0x75,0x01, 0x95,0x10, 0x81,0x02,
    0x05,0x01, 0x09,0x39, 0x15,0x00, 0x25,0x07,
    0x35,0x00, 0x46,0x3b,0x01, 0x65,0x14, 0x75,0x04, 0x95,0x01,
    0x81,0x42, 0x75,0x04, 0x95,0x01, 0x81,0x03,
    0x65,0x00, 0x36,0x01,0x80, 0x46,0xff,0x7f,
    0x09,0x30, 0x09,0x31, 0x09,0x33, 0x09,0x34,
    0x16,0x01,0x80, 0x26,0xff,0x7f, 0x75,0x10, 0x95,0x04, 0x81,0x02,
    0x35,0x00, 0x46,0xff,0x00,
    0x09,0x32, 0x09,0x35, 0x15,0x00, 0x26,0xff,0x00,
    0x75,0x08, 0x95,0x02, 0x81,0x02, 0xc0,

    /* 63-byte application frames in either direction, plus the report ID. */
    0x06,0x00,0xff, 0x09,0x01, 0xa1,0x01, 0x85,KB7_REPORT_ID_VENDOR,
    0x09,0x02, 0x15,0x00, 0x26,0xff,0x00, 0x75,0x08, 0x95,0x3f,
    0x91,0x02, 0x09,0x03, 0x75,0x08, 0x95,0x3f, 0x81,0x02, 0xc0,
};

#define USB_CONFIG_TOTAL_LENGTH 41U
#define USB_HID_DESCRIPTOR_OFFSET 18U

__attribute__((used, section(".rodata.usb_descriptors")))
static const uint8_t configuration_descriptor[USB_CONFIG_TOTAL_LENGTH] = {
    9U, USB_DESC_CONFIGURATION, USB_CONFIG_TOTAL_LENGTH, 0U, 1U, 1U, 0U,
    0x80U, (uint8_t)((KB7_USB_MAX_POWER_MA + 1U) / 2U),
    9U, 4U, KB7_USB_HID_INTERFACE, 0U, 2U, 3U, 0U, 0U, 0U,
    9U, USB_DESC_HID, 0x11U, 0x01U, 0U, 1U, USB_DESC_REPORT,
    (uint8_t)sizeof(report_descriptor), (uint8_t)(sizeof(report_descriptor) >> 8U),
    7U, 5U, KB7_USB_DATA_IN_ADDRESS, 3U, KB7_USB_ENDPOINT_SIZE, 0U, 1U,
    7U, 5U, KB7_USB_DATA_OUT_ADDRESS, 3U, KB7_USB_ENDPOINT_SIZE, 0U, 1U,
};

static struct usb_in_endpoint in_endpoints[USB_ENDPOINT_COUNT];
static struct usb_out_endpoint out_endpoints[USB_ENDPOINT_COUNT];
static struct usb_ep0_transfer ep0;
static enum kb7_usb_device_state device_state;
static enum kb7_usb_device_state resume_state;
static uint8_t configuration_value;
static uint8_t device_address;
static uint8_t keyboard_led_state;
static uint8_t hid_protocol = 1U;
static uint8_t hid_idle[5];
static bool endpoint_halt[USB_ENDPOINT_COUNT][2];
static bool controller_available;
static bool dispatching;

static uint8_t control_buffer[KB7_USB_ENDPOINT_SIZE];
static uint8_t last_keyboard[KB7_KEYBOARD_REPORT_BYTES];
static uint8_t last_consumer[KB7_CONSUMER_REPORT_BYTES];
static uint8_t last_gamepad[KB7_ANALOG_REPORT_BYTES];
static uint8_t last_joystick[KB7_USB_GAMEPAD_REPORT_BYTES];
static uint8_t last_vendor[KB7_USB_ENDPOINT_SIZE];
static uint8_t last_vendor_output[KB7_USB_ENDPOINT_SIZE];

#if defined(KB7_USB_TEST)
extern uint32_t kb7_usb_test_mmio_read(uintptr_t address);
extern void kb7_usb_test_mmio_write(uintptr_t address, uint32_t value);
static uint32_t usb_read(uintptr_t address) {
    return kb7_usb_test_mmio_read(address);
}
static void usb_write(uintptr_t address, uint32_t value) {
    kb7_usb_test_mmio_write(address, value);
}
#else
static uint32_t usb_read(uintptr_t address) { return KB7_MMIO32(address); }
static void usb_write(uintptr_t address, uint32_t value) { KB7_MMIO32(address) = value; }
#endif

#if defined(KB7_HOST_TEST)
static uint32_t usb_critical_enter(void) { return 0U; }
static void usb_critical_exit(uint32_t previous) { (void)previous; }
#else
static uint32_t usb_critical_enter(void) {
    uint32_t previous;
    __asm__ volatile("mrs %0, primask\ncpsid i" : "=r"(previous) :: "memory");
    return previous;
}
static void usb_critical_exit(uint32_t previous) {
    if ((previous & 1U) == 0U) __asm__ volatile("cpsie i" ::: "memory");
}
#endif

static uint16_t min_u16(uint16_t left, uint16_t right) {
    return left < right ? left : right;
}

static uint8_t report_index(uint8_t report_id) {
    switch (report_id) {
    case KB7_REPORT_ID_KEYBOARD: return 0U;
    case KB7_REPORT_ID_CONSUMER: return 1U;
    case KB7_REPORT_ID_ANALOG: return 2U;
    case KB7_USB_GAMEPAD_REPORT_ID: return 3U;
    case KB7_REPORT_ID_VENDOR: return 4U;
    default: return 0xffU;
    }
}

static const uint8_t *input_report(uint8_t report_id, uint16_t *length) {
    switch (report_id) {
    case KB7_REPORT_ID_KEYBOARD:
        *length = sizeof(last_keyboard);
        return last_keyboard;
    case KB7_REPORT_ID_CONSUMER:
        *length = sizeof(last_consumer);
        return last_consumer;
    case KB7_REPORT_ID_ANALOG:
        *length = sizeof(last_gamepad);
        return last_gamepad;
    case KB7_USB_GAMEPAD_REPORT_ID:
        *length = sizeof(last_joystick);
        return last_joystick;
    case KB7_REPORT_ID_VENDOR:
        *length = sizeof(last_vendor);
        return last_vendor;
    default:
        *length = 0U;
        return NULL;
    }
}

static const uint8_t *output_report(uint8_t report_id, uint16_t *length) {
    if (report_id == KB7_REPORT_ID_KEYBOARD) {
        control_buffer[0] = KB7_REPORT_ID_KEYBOARD;
        control_buffer[1] = keyboard_led_state;
        *length = 2U;
        return control_buffer;
    }
    if (report_id == KB7_REPORT_ID_VENDOR) {
        *length = sizeof(last_vendor_output);
        return last_vendor_output;
    }
    *length = 0U;
    return NULL;
}

static const uint8_t *make_string_descriptor(uint8_t index, uint16_t *length) {
    static const char manufacturer[] = KB7_USB_MANUFACTURER_STRING;
    static const char product[] = KB7_USB_PRODUCT_STRING;
    const char *ascii;
    size_t ascii_length;

    if (index == 0U) {
        control_buffer[0] = 4U;
        control_buffer[1] = USB_DESC_STRING;
        control_buffer[2] = 0x09U;
        control_buffer[3] = 0x04U;
        *length = 4U;
        return control_buffer;
    }
    if (index == 1U) {
        ascii = manufacturer;
        ascii_length = sizeof(manufacturer) - 1U;
    } else if (index == 2U) {
        ascii = product;
        ascii_length = sizeof(product) - 1U;
    } else {
        *length = 0U;
        return NULL;
    }
    if (ascii_length > (sizeof(control_buffer) - 2U) / 2U) {
        ascii_length = (sizeof(control_buffer) - 2U) / 2U;
    }
    control_buffer[0] = (uint8_t)(2U + ascii_length * 2U);
    control_buffer[1] = USB_DESC_STRING;
    for (size_t index_char = 0U; index_char < ascii_length; ++index_char) {
        control_buffer[2U + index_char * 2U] = (uint8_t)ascii[index_char];
        control_buffer[3U + index_char * 2U] = 0U;
    }
    *length = control_buffer[0];
    return control_buffer;
}

static void set_response(struct kb7_usb_control_response *response,
                         const uint8_t *data, uint16_t available, uint16_t requested) {
    response->data = data;
    response->length = min_u16(available, requested);
    response->expected_out_length = 0U;
}

static int32_t descriptor_request(const struct kb7_usb_setup_packet *setup,
                                  struct kb7_usb_control_response *response) {
    const uint8_t descriptor_type = (uint8_t)(setup->value >> 8U);
    const uint8_t descriptor_index = (uint8_t)setup->value;
    const uint8_t *data = NULL;
    uint16_t length = 0U;

    switch (descriptor_type) {
    case USB_DESC_DEVICE:
        if ((setup->request_type & USB_RECIPIENT_MASK) != USB_RECIPIENT_DEVICE ||
            descriptor_index != 0U || setup->index != 0U) return KB7_USB_STALL;
        data = (const uint8_t *)&device_descriptor;
        length = sizeof(device_descriptor);
        break;
    case USB_DESC_CONFIGURATION:
        if ((setup->request_type & USB_RECIPIENT_MASK) != USB_RECIPIENT_DEVICE ||
            descriptor_index != 0U || setup->index != 0U) return KB7_USB_STALL;
        data = configuration_descriptor;
        length = sizeof(configuration_descriptor);
        break;
    case USB_DESC_STRING:
        if ((setup->request_type & USB_RECIPIENT_MASK) != USB_RECIPIENT_DEVICE ||
            (descriptor_index == 0U ? setup->index != 0U : setup->index != 0x0409U))
            return KB7_USB_STALL;
        data = make_string_descriptor(descriptor_index, &length);
        if (data == NULL) return KB7_USB_STALL;
        break;
    case USB_DESC_HID:
        if ((setup->request_type & USB_RECIPIENT_MASK) != USB_RECIPIENT_INTERFACE ||
            setup->index != KB7_USB_HID_INTERFACE || descriptor_index != 0U)
            return KB7_USB_STALL;
        data = &configuration_descriptor[USB_HID_DESCRIPTOR_OFFSET];
        length = 9U;
        break;
    case USB_DESC_REPORT:
        if ((setup->request_type & USB_RECIPIENT_MASK) != USB_RECIPIENT_INTERFACE ||
            setup->index != KB7_USB_HID_INTERFACE || descriptor_index != 0U)
            return KB7_USB_STALL;
        data = report_descriptor;
        length = sizeof(report_descriptor);
        break;
    default:
        return KB7_USB_STALL;
    }
    set_response(response, data, length, setup->length);
    return KB7_USB_OK;
}

static int32_t standard_request(const struct kb7_usb_setup_packet *setup,
                                struct kb7_usb_control_response *response) {
    const bool in = (setup->request_type & USB_DIRECTION_IN) != 0U;
    const uint8_t recipient = setup->request_type & USB_RECIPIENT_MASK;

    if (setup->request == USB_REQ_GET_DESCRIPTOR && in) {
        return descriptor_request(setup, response);
    }
    if (setup->request == USB_REQ_GET_STATUS && in && setup->value == 0U &&
        setup->length == 2U) {
        uint16_t status = 0U;
        if (recipient == USB_RECIPIENT_DEVICE) {
            if (setup->index != 0U) return KB7_USB_STALL;
        } else if (recipient == USB_RECIPIENT_INTERFACE) {
            if (setup->index != KB7_USB_HID_INTERFACE || configuration_value != 1U)
                return KB7_USB_STALL;
        } else if (recipient == USB_RECIPIENT_ENDPOINT) {
            const uint8_t endpoint = (uint8_t)setup->index & 0x0fU;
            const uint8_t direction = ((uint8_t)setup->index & 0x80U) != 0U ? 1U : 0U;
            if (setup->index != (uint8_t)setup->index || endpoint >= USB_ENDPOINT_COUNT ||
                (endpoint != 0U && endpoint != 2U) ||
                (endpoint == 2U && configuration_value != 1U))
                return KB7_USB_STALL;
            if (endpoint_halt[endpoint][direction]) status = 1U;
        } else {
            return KB7_USB_STALL;
        }
        control_buffer[0] = (uint8_t)status;
        control_buffer[1] = (uint8_t)(status >> 8U);
        set_response(response, control_buffer, 2U, setup->length);
        return KB7_USB_OK;
    }
    if ((setup->request == USB_REQ_CLEAR_FEATURE || setup->request == USB_REQ_SET_FEATURE) &&
        !in && setup->length == 0U) {
        const bool set = setup->request == USB_REQ_SET_FEATURE;
        if (recipient == USB_RECIPIENT_ENDPOINT &&
            setup->value == USB_FEATURE_ENDPOINT_HALT) {
            const uint8_t address = (uint8_t)setup->index;
            const uint8_t endpoint = address & 0x0fU;
            const uint8_t direction = (address & 0x80U) != 0U ? 1U : 0U;
            if (setup->index != address || endpoint == 0U ||
                endpoint >= USB_ENDPOINT_COUNT || endpoint != 2U ||
                configuration_value != 1U)
                return KB7_USB_STALL;
            endpoint_halt[endpoint][direction] = set;
            return KB7_USB_OK;
        }
        return KB7_USB_STALL;
    }
    if (setup->request == USB_REQ_SET_ADDRESS && !in && recipient == USB_RECIPIENT_DEVICE &&
        setup->index == 0U && setup->length == 0U && setup->value <= 127U &&
        configuration_value == 0U) {
        ep0.pending_address = (uint8_t)setup->value;
        ep0.address_pending = true;
        return KB7_USB_OK;
    }
    if (setup->request == USB_REQ_GET_CONFIGURATION && in &&
        recipient == USB_RECIPIENT_DEVICE && setup->value == 0U && setup->index == 0U &&
        setup->length == 1U) {
        control_buffer[0] = configuration_value;
        set_response(response, control_buffer, 1U, setup->length);
        return KB7_USB_OK;
    }
    if (setup->request == USB_REQ_SET_CONFIGURATION && !in &&
        recipient == USB_RECIPIENT_DEVICE && setup->index == 0U && setup->length == 0U &&
        setup->value <= 1U) {
        configuration_value = (uint8_t)setup->value;
        device_state = configuration_value == 0U
                           ? (device_address == 0U ? KB7_USB_DEFAULT : KB7_USB_ADDRESSED)
                           : KB7_USB_CONFIGURED;
        return KB7_USB_OK;
    }
    if (setup->request == USB_REQ_GET_INTERFACE && in &&
        recipient == USB_RECIPIENT_INTERFACE && setup->value == 0U &&
        setup->index == KB7_USB_HID_INTERFACE && setup->length == 1U &&
        configuration_value == 1U) {
        control_buffer[0] = 0U;
        set_response(response, control_buffer, 1U, setup->length);
        return KB7_USB_OK;
    }
    if (setup->request == USB_REQ_SET_INTERFACE && !in &&
        recipient == USB_RECIPIENT_INTERFACE && setup->value == 0U &&
        setup->index == KB7_USB_HID_INTERFACE && setup->length == 0U &&
        configuration_value == 1U) {
        return KB7_USB_OK;
    }
    return KB7_USB_STALL;
}

static int32_t class_request(const struct kb7_usb_setup_packet *setup,
                             const uint8_t *out_data, uint16_t out_length,
                             struct kb7_usb_control_response *response) {
    if ((setup->request_type & USB_RECIPIENT_MASK) != USB_RECIPIENT_INTERFACE ||
        setup->index != KB7_USB_HID_INTERFACE) return KB7_USB_STALL;

    const bool in = (setup->request_type & USB_DIRECTION_IN) != 0U;
    const uint8_t report_type = (uint8_t)(setup->value >> 8U);
    const uint8_t report_id = (uint8_t)setup->value;
    uint16_t report_length = 0U;
    const uint8_t *report;

    if (setup->request == USB_HID_GET_REPORT && in) {
        if (report_type == 1U) report = input_report(report_id, &report_length);
        else if (report_type == 2U) report = output_report(report_id, &report_length);
        else return KB7_USB_STALL;
        if (report == NULL) return KB7_USB_STALL;
        set_response(response, report, report_length, setup->length);
        return KB7_USB_OK;
    }
    if (setup->request == USB_HID_SET_REPORT && !in && report_type == 2U) {
        report = output_report(report_id, &report_length);
        if (report == NULL || setup->length != report_length || report_length == 0U ||
            report_length > KB7_USB_ENDPOINT_SIZE) return KB7_USB_STALL;
        if (out_data == NULL) {
            if (out_length != 0U) return KB7_USB_INVALID;
            response->expected_out_length = report_length;
            return KB7_USB_NEED_OUT_DATA;
        }
        if (out_length != report_length || out_data[0] != report_id) return KB7_USB_STALL;
        if (report_id == KB7_REPORT_ID_KEYBOARD) {
            keyboard_led_state = out_data[1] & 0x1fU;
            kb7_usb_keyboard_led_output(keyboard_led_state);
        } else {
            kb7_memcpy(last_vendor_output, out_data, report_length);
            kb7_usb_vendor_output(last_vendor_output, report_length);
        }
        return KB7_USB_OK;
    }
    if (setup->request == USB_HID_GET_IDLE && in && setup->length == 1U &&
        (uint8_t)(setup->value >> 8U) == 0U) {
        const uint8_t index = report_index(report_id);
        if (index == 0xffU) return KB7_USB_STALL;
        control_buffer[0] = hid_idle[index];
        set_response(response, control_buffer, 1U, setup->length);
        return KB7_USB_OK;
    }
    if (setup->request == USB_HID_SET_IDLE && !in && setup->length == 0U) {
        const uint8_t duration = (uint8_t)(setup->value >> 8U);
        if (report_id == 0U) {
            for (size_t index = 0U; index < KB7_ARRAY_LEN(hid_idle); ++index)
                hid_idle[index] = duration;
            return KB7_USB_OK;
        }
        const uint8_t index = report_index(report_id);
        if (index == 0xffU) return KB7_USB_STALL;
        hid_idle[index] = duration;
        return KB7_USB_OK;
    }
    if (setup->request == USB_HID_GET_PROTOCOL && in && setup->value == 0U &&
        setup->length == 1U) {
        control_buffer[0] = hid_protocol;
        set_response(response, control_buffer, 1U, setup->length);
        return KB7_USB_OK;
    }
    if (setup->request == USB_HID_SET_PROTOCOL && !in && setup->length == 0U &&
        setup->value <= 1U) {
        hid_protocol = (uint8_t)setup->value;
        return KB7_USB_OK;
    }
    return KB7_USB_STALL;
}

int32_t kb7_usb_control_request(const struct kb7_usb_setup_packet *setup,
                                const uint8_t *out_data, uint16_t out_length,
                                struct kb7_usb_control_response *response) {
    if (setup == NULL || response == NULL || (out_data == NULL && out_length != 0U))
        return KB7_USB_INVALID;
    response->data = NULL;
    response->length = 0U;
    response->expected_out_length = 0U;

    const uint8_t type = setup->request_type & USB_TYPE_MASK;
    if (type == USB_TYPE_STANDARD) return standard_request(setup, response);
    if (type == USB_TYPE_CLASS)
        return class_request(setup, out_data, out_length, response);
    return KB7_USB_STALL;
}

#if defined(KB7_USB_TEST)
__attribute__((weak))
void kb7_usb_vendor_output(const uint8_t *report, uint16_t length) {
    (void)report;
    (void)length;
}
#else
void kb7_usb_vendor_output(const uint8_t *report, uint16_t length) {
    if (report == NULL || length != KB7_SHARED_HOST_REPORT_BYTES ||
        report[0] != KB7_REPORT_ID_VENDOR) return;

    volatile struct kb7_shared_host_mailbox *const mailbox = kb7_host_mailbox();
    const uint32_t previous = usb_critical_enter();
    if (mailbox->state != KB7_HOST_MAILBOX_EMPTY) {
        ++mailbox->dropped;
        usb_critical_exit(previous);
        return;
    }
    for (uint16_t index = 0U; index < length; ++index)
        mailbox->report[index] = report[index];
    kb7_dmb();
    mailbox->state = KB7_HOST_MAILBOX_FULL;
    usb_critical_exit(previous);
}
#endif

__attribute__((weak))
void kb7_usb_keyboard_led_output(uint8_t leds) {
    (void)leds;
}

static void endpoint_configure(uint8_t address, uint32_t configuration) {
    usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT, address);
    usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_CONFIG, configuration);
    usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_MODE,
              (address & USB_DIRECTION_IN) != 0U
                  ? UINT32_C(0x80000080) : UINT32_C(0x80000090));
}

#if !defined(KB7_USB_TEST)
static bool endpoint_ready(void) {
    uint32_t timeout = USB_CONTROLLER_TIMEOUT;
    while ((usb_read(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_STATE) & KB7_BIT(3)) != 0U) {
        if (timeout == 0U) return false;
        --timeout;
    }
    return true;
}
#endif

static bool start_in(uint8_t endpoint) {
    struct usb_in_endpoint *const queue = &in_endpoints[endpoint];
    if (queue->active || queue->count == 0U) return true;
    const uint16_t length = queue->length[queue->head];
    queue->dma[0].buffer = (uint32_t)(uintptr_t)queue->data[queue->head];
    queue->dma[0].length = USB_DMA_VALID | length;
    queue->dma[0].control = USB_DMA_DATA_CONTROL;
    /* The terminal TRB links back to the first 12-byte TRB, as in the
     * recovered controller builder.  The engine consumes this as a ring. */
    queue->dma[1].buffer = (uint32_t)(uintptr_t)&queue->dma[0];
    queue->dma[1].length = 0U;
    queue->dma[1].control = USB_DMA_END_CONTROL;
    kb7_dmb();
#if !defined(KB7_USB_TEST)
    usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT, endpoint | USB_DIRECTION_IN);
    if (!endpoint_ready()) return false;
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_STATE, KB7_BIT(3));
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_CONTROL,
              (uint32_t)(uintptr_t)&queue->dma[0]);
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_START, KB7_BIT(endpoint + 16U));
#endif
    queue->active = true;
    return true;
}

static bool arm_out(uint8_t endpoint, uint16_t length) {
    struct usb_out_endpoint *const out = &out_endpoints[endpoint];
    if (length > KB7_USB_ENDPOINT_SIZE) return false;
    kb7_memset(out->data, 0, sizeof(out->data));
    out->requested = length;
    out->completed = 0U;
    out->dma[0].buffer = (uint32_t)(uintptr_t)out->data;
    out->dma[0].length = USB_DMA_VALID | length;
    out->dma[0].control = USB_DMA_DATA_CONTROL;
    out->dma[1].buffer = (uint32_t)(uintptr_t)&out->dma[0];
    out->dma[1].length = 0U;
    out->dma[1].control = USB_DMA_END_CONTROL;
    kb7_dmb();
#if !defined(KB7_USB_TEST)
    usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT, endpoint);
    if (!endpoint_ready()) return false;
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_STATE, KB7_BIT(3));
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_CONTROL,
              (uint32_t)(uintptr_t)&out->dma[0]);
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_START, KB7_BIT(endpoint));
#endif
    out->active = true;
    return true;
}

static int32_t enqueue_in(uint8_t endpoint, const void *data, uint16_t length) {
    if (endpoint >= USB_ENDPOINT_COUNT || data == NULL || length > KB7_USB_ENDPOINT_SIZE)
        return KB7_USB_INVALID;
    struct usb_in_endpoint *const queue = &in_endpoints[endpoint];
    if (queue->count >= USB_ENDPOINT_QUEUE_DEPTH) return KB7_USB_BUSY;
    kb7_memcpy(queue->data[queue->tail], data, length);
    queue->length[queue->tail] = length;
    queue->tail = (uint8_t)((queue->tail + 1U) % USB_ENDPOINT_QUEUE_DEPTH);
    ++queue->count;
    kb7_dmb();
    if (!start_in(endpoint)) {
        queue->tail = (uint8_t)((queue->tail + USB_ENDPOINT_QUEUE_DEPTH - 1U) %
                                USB_ENDPOINT_QUEUE_DEPTH);
        --queue->count;
        return KB7_USB_IO;
    }
    return KB7_USB_OK;
}

static void complete_in(uint8_t endpoint) {
    if (endpoint >= USB_ENDPOINT_COUNT) return;
    struct usb_in_endpoint *const queue = &in_endpoints[endpoint];
    if (!queue->active || queue->count == 0U) return;
    queue->active = false;
    queue->head = (uint8_t)((queue->head + 1U) % USB_ENDPOINT_QUEUE_DEPTH);
    --queue->count;
    (void)start_in(endpoint);
}

static void initialize_report_cache(void) {
    kb7_memset(last_keyboard, 0, sizeof(last_keyboard));
    kb7_memset(last_consumer, 0, sizeof(last_consumer));
    kb7_memset(last_gamepad, 0, sizeof(last_gamepad));
    kb7_memset(last_joystick, 0, sizeof(last_joystick));
    kb7_memset(last_vendor, 0, sizeof(last_vendor));
    kb7_memset(last_vendor_output, 0, sizeof(last_vendor_output));
    last_keyboard[0] = KB7_REPORT_ID_KEYBOARD;
    last_consumer[0] = KB7_REPORT_ID_CONSUMER;
    last_gamepad[0] = KB7_REPORT_ID_ANALOG;
    last_joystick[0] = KB7_USB_GAMEPAD_REPORT_ID;
    last_vendor[0] = KB7_REPORT_ID_VENDOR;
    last_vendor_output[0] = KB7_REPORT_ID_VENDOR;
}

static void reset_software_state(void) {
    kb7_memset(in_endpoints, 0, sizeof(in_endpoints));
    kb7_memset(out_endpoints, 0, sizeof(out_endpoints));
    kb7_memset(&ep0, 0, sizeof(ep0));
    kb7_memset(hid_idle, 0, sizeof(hid_idle));
    kb7_memset(endpoint_halt, 0, sizeof(endpoint_halt));
    configuration_value = 0U;
    device_address = 0U;
    keyboard_led_state = 0U;
    hid_protocol = 1U;
    device_state = KB7_USB_DEFAULT;
    resume_state = KB7_USB_DEFAULT;
    initialize_report_cache();
}

static void configure_ep0(void) {
    /* Stock state handling programs enabled control endpoints with MPS=64. */
    endpoint_configure(0x00U, UINT32_C(0x00400001));
    endpoint_configure(0x80U, UINT32_C(0x00400001));
    (void)arm_out(0U, KB7_USB_ENDPOINT_SIZE);
}

static void note_data_queue_reset(void) {
#if !defined(KB7_USB_TEST)
    ++kb7_shared()->usb_events;
    kb7_dmb();
#endif
}

static void disable_data_endpoints(void) {
    endpoint_configure(KB7_USB_DATA_OUT_ADDRESS, 0U);
    endpoint_configure(KB7_USB_DATA_IN_ADDRESS, 0U);
    kb7_memset(&in_endpoints[KB7_USB_DATA_ENDPOINT], 0,
               sizeof(in_endpoints[KB7_USB_DATA_ENDPOINT]));
    kb7_memset(&out_endpoints[KB7_USB_DATA_ENDPOINT], 0,
               sizeof(out_endpoints[KB7_USB_DATA_ENDPOINT]));
    note_data_queue_reset();
}

static void configure_data_endpoints(void) {
    kb7_memset(&in_endpoints[KB7_USB_DATA_ENDPOINT], 0,
               sizeof(in_endpoints[KB7_USB_DATA_ENDPOINT]));
    kb7_memset(&out_endpoints[KB7_USB_DATA_ENDPOINT], 0,
               sizeof(out_endpoints[KB7_USB_DATA_ENDPOINT]));
    note_data_queue_reset();
    /* interrupt, max packet 64: 1 | (3 << 1) | (64 << 16) */
    endpoint_configure(KB7_USB_DATA_OUT_ADDRESS, UINT32_C(0x00400007));
    endpoint_configure(KB7_USB_DATA_IN_ADDRESS, UINT32_C(0x00400007));
    (void)arm_out(KB7_USB_DATA_ENDPOINT, KB7_USB_ENDPOINT_SIZE);
}

static void bus_reset(void) {
    reset_software_state();
    disable_data_endpoints();
    configure_ep0();
}

static void stall_ep0(void);

static void ep0_send_next(void) {
    if (ep0.remaining == 0U) {
        if (ep0.needs_zlp) {
            static const uint8_t zero;
            ep0.needs_zlp = false;
            if (enqueue_in(0U, &zero, 0U) == KB7_USB_OK) ep0.data_in = true;
            else stall_ep0();
            return;
        }
        ep0.data_in = false;
        (void)arm_out(0U, KB7_USB_ENDPOINT_SIZE);
        return;
    }
    const uint16_t packet = min_u16(ep0.remaining, KB7_USB_ENDPOINT_SIZE);
    if (enqueue_in(0U, ep0.next, packet) == KB7_USB_OK) {
        ep0.next += packet;
        ep0.remaining -= packet;
        ep0.data_in = true;
    }
}

static void ep0_reply(const struct kb7_usb_control_response *response,
                      const struct kb7_usb_setup_packet *setup) {
    if (response->length == 0U) {
        if ((setup->request_type & USB_DIRECTION_IN) != 0U) {
            ep0.data_in = false;
            ep0.status_in = false;
            (void)arm_out(0U, KB7_USB_ENDPOINT_SIZE);
            return;
        }
        static const uint8_t zero;
        (void)enqueue_in(0U, &zero, 0U);
        ep0.data_in = false;
        ep0.status_in = true;
        return;
    }
    ep0.next = response->data;
    ep0.remaining = response->length;
    ep0.requested = setup->length;
    ep0.needs_zlp = response->length < setup->length &&
                    (response->length % KB7_USB_ENDPOINT_SIZE) == 0U;
    ep0_send_next();
}

static bool endpoint_apply_halt(uint8_t address, bool set) {
    const uint8_t endpoint = address & 0x0fU;
    const bool in = (address & USB_DIRECTION_IN) != 0U;
    usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT, address);
    if (set) {
        /* Recovered endpoint STALL command. */
        usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_STATE, KB7_BIT(1));
        if (in) {
            kb7_memset(&in_endpoints[endpoint], 0, sizeof(in_endpoints[endpoint]));
            if (endpoint == KB7_USB_DATA_ENDPOINT) note_data_queue_reset();
        }
        else out_endpoints[endpoint].active = false;
        return true;
    }

    /* Stock CLEAR_FEATURE preserves endpoint control, resets the toggle, waits
     * for the controller to accept it, and then restores the control word. */
    const uint32_t control = usb_read(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_CONTROL);
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_CONTROL, control);
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_STATE, KB7_BIT(0));
    uint32_t timeout = USB_CONTROLLER_TIMEOUT;
    while ((usb_read(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_STATE) & KB7_BIT(0)) != 0U) {
        if (timeout == 0U) return false;
        --timeout;
    }
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_STATE, KB7_BIT(2));
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_CONTROL, control);
    if (!in && endpoint == KB7_USB_DATA_ENDPOINT)
        return arm_out(endpoint, KB7_USB_ENDPOINT_SIZE);
    return true;
}

static void stall_ep0(void) {
    endpoint_halt[0][0] = true;
    endpoint_halt[0][1] = true;
    usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT, 0U);
    usb_write(SNC_USB_BASE + USB_CONTROLLER_ENDPOINT_STATE, KB7_BIT(1));
}

static void process_setup_packet(void) {
    struct kb7_usb_setup_packet setup;
    struct kb7_usb_control_response response;
    if (out_endpoints[0].completed != sizeof(setup)) {
        stall_ep0();
        return;
    }
    kb7_memcpy(&setup, out_endpoints[0].data, sizeof(setup));
    /* A SETUP token aborts any earlier control transfer, including a deferred
     * address, and starts from a fresh EP0 software queue. */
    kb7_memset(&in_endpoints[0], 0, sizeof(in_endpoints[0]));
    kb7_memset(&ep0, 0, sizeof(ep0));
    endpoint_halt[0][0] = false;
    endpoint_halt[0][1] = false;
    const int32_t result = kb7_usb_control_request(&setup, NULL, 0U, &response);
    if (result == KB7_USB_NEED_OUT_DATA) {
        ep0.pending_setup = setup;
        ep0.pending_out = response.expected_out_length;
        if (!arm_out(0U, ep0.pending_out)) stall_ep0();
    } else if (result == KB7_USB_OK) {
        if (setup.request == USB_REQ_SET_CONFIGURATION) {
            if (configuration_value == 1U) configure_data_endpoints();
            else disable_data_endpoints();
        }
        if ((setup.request == USB_REQ_CLEAR_FEATURE ||
             setup.request == USB_REQ_SET_FEATURE) &&
            (setup.request_type & USB_RECIPIENT_MASK) == USB_RECIPIENT_ENDPOINT &&
            !endpoint_apply_halt((uint8_t)setup.index,
                                 setup.request == USB_REQ_SET_FEATURE)) {
            const uint8_t failed_address = (uint8_t)setup.index;
            endpoint_halt[failed_address & 0x0fU]
                         [(failed_address & USB_DIRECTION_IN) != 0U ? 1U : 0U] = true;
            stall_ep0();
            return;
        }
        ep0_reply(&response, &setup);
    } else {
        stall_ep0();
    }
}

static void process_ep0_out_data(void) {
    struct kb7_usb_control_response response;
    if (out_endpoints[0].completed != ep0.pending_out) {
        ep0.pending_out = 0U;
        stall_ep0();
        return;
    }
    const int32_t result = kb7_usb_control_request(
        &ep0.pending_setup, out_endpoints[0].data,
        out_endpoints[0].completed, &response);
    ep0.pending_out = 0U;
    if (result == KB7_USB_OK) ep0_reply(&response, &ep0.pending_setup);
    else stall_ep0();
}

static void process_vendor_out(void) {
    struct usb_out_endpoint *const out = &out_endpoints[KB7_USB_DATA_ENDPOINT];
    if (out->completed == KB7_USB_ENDPOINT_SIZE &&
        out->data[0] == KB7_REPORT_ID_VENDOR) {
        kb7_memcpy(last_vendor_output, out->data, KB7_USB_ENDPOINT_SIZE);
        kb7_usb_vendor_output(last_vendor_output, KB7_USB_ENDPOINT_SIZE);
    }
    (void)arm_out(KB7_USB_DATA_ENDPOINT, KB7_USB_ENDPOINT_SIZE);
}

static void endpoint_event(uint8_t address, uint32_t status) {
    const uint8_t endpoint = address & 0x0fU;
    const bool in = (address & USB_DIRECTION_IN) != 0U;
    if (endpoint >= USB_ENDPOINT_COUNT) return;
    if ((status & USB_CONTROLLER_EP_ERROR) != 0U) {
        if (endpoint == 0U) {
            stall_ep0();
        } else if (in) {
            kb7_memset(&in_endpoints[endpoint], 0, sizeof(in_endpoints[endpoint]));
            if (endpoint == KB7_USB_DATA_ENDPOINT) note_data_queue_reset();
        } else {
            out_endpoints[endpoint].active = false;
            (void)arm_out(endpoint, KB7_USB_ENDPOINT_SIZE);
        }
        return;
    }
    if (in) {
        if ((status & USB_CONTROLLER_EP_IN_COMPLETE) == 0U) return;
        complete_in(endpoint);
        if (endpoint == 0U) {
            if (ep0.address_pending && in_endpoints[0].count == 0U) {
                device_address = ep0.pending_address;
                ep0.address_pending = false;
                device_state = device_address == 0U ? KB7_USB_DEFAULT : KB7_USB_ADDRESSED;
            }
            if (ep0.data_in) ep0_send_next();
            else if (ep0.status_in) {
                ep0.status_in = false;
                (void)arm_out(0U, KB7_USB_ENDPOINT_SIZE);
            }
        }
        return;
    }
    if ((status & (USB_CONTROLLER_EP0_SETUP | USB_CONTROLLER_EP_EVENT_A |
                   USB_CONTROLLER_EP_EVENT_B)) == 0U) return;
    struct usb_out_endpoint *const out = &out_endpoints[endpoint];
    const uint32_t completed = out->dma[0].length & USB_DMA_LENGTH_MASK;
    out->completed = completed <= out->requested ? (uint16_t)completed : UINT16_MAX;
    out->active = false;
    if (endpoint == 0U) {
        if ((status & USB_CONTROLLER_EP0_SETUP) != 0U) process_setup_packet();
        else if ((status & (USB_CONTROLLER_EP_EVENT_A | USB_CONTROLLER_EP_EVENT_B)) != 0U &&
                 ep0.pending_out != 0U) process_ep0_out_data();
        else (void)arm_out(0U, KB7_USB_ENDPOINT_SIZE);
    } else if (endpoint == KB7_USB_DATA_ENDPOINT) {
        process_vendor_out();
    }
}

static bool transaction_ready(void) {
    uint32_t timeout = USB_CONTROLLER_TIMEOUT;
    while ((usb_read(SNC_USB_BASE + SNC_USB_TRANSACTION_STATUS) &
            USB_TRANSACTION_READY) == 0U) {
        if (timeout == 0U) return false;
        --timeout;
    }
    return true;
}

static void disconnect_controller(void) {
    device_state = KB7_USB_DETACHED;
    configuration_value = 0U;
    kb7_memset(in_endpoints, 0, sizeof(in_endpoints));
    kb7_memset(out_endpoints, 0, sizeof(out_endpoints));
    usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, UINT32_C(0x00080000));
    usb_write(SNC_USB_PHY_GATE,
              usb_read(SNC_USB_PHY_GATE) & ~KB7_BIT(16));
}

static void reconnect_controller(void) {
    usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, UINT32_C(0x00040000));
    usb_write(SNC_USB_PHY_GATE,
              usb_read(SNC_USB_PHY_GATE) | KB7_BIT(16));
    bus_reset();
}

static void controller_state_change(void) {
    const uint8_t hardware_state = (uint8_t)(
        (usb_read(SNC_USB_BASE + SNC_USB_CONFIGURATION) >> 4U) & 7U);

    /* Stock programs EP0 in controller states 2 and 3.  State 4 maps to
     * the stock stack's software state 5 and is its suspended state. */
    if (hardware_state == 2U || hardware_state == 3U) configure_ep0();
    if (hardware_state == 4U) {
        if (device_state != KB7_USB_SUSPENDED) resume_state = device_state;
        device_state = KB7_USB_SUSPENDED;
    }
}

static void global_events(uint32_t events) {
    if ((events & USB_EVENT_DISCONNECT) != 0U) disconnect_controller();
    if ((events & USB_EVENT_CONNECT) != 0U) reconnect_controller();
    if ((events & USB_EVENT_RESET) != 0U) bus_reset();
    if ((events & USB_EVENT_STATE_CHANGE) != 0U) controller_state_change();
    if ((events & USB_EVENT_RESUME) != 0U && device_state == KB7_USB_SUSPENDED)
        device_state = resume_state;
}

static void dispatch_controller(void) {
    if (!controller_available || dispatching) return;
    dispatching = true;
    const uint32_t global = usb_read(SNC_USB_BASE + SNC_USB_GLOBAL_EVENT_STATUS);
    if (global != 0U) {
        if (!transaction_ready()) {
            disconnect_controller();
            dispatching = false;
            return;
        }
        usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_ACK, global);
        global_events(global);
    } else {
        const uint32_t pending = usb_read(SNC_USB_BASE + SNC_USB_ENDPOINT_PENDING);
        const uint32_t previous = usb_read(SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT);
        for (uint8_t bit = 0U; bit < 32U; ++bit) {
            if ((pending & KB7_BIT(bit)) == 0U) continue;
            const uint8_t address = bit < 16U ? bit : (uint8_t)((bit - 16U) | 0x80U);
            usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT, address);
            const uint32_t status = usb_read(SNC_USB_BASE + SNC_USB_ENDPOINT_STATUS);
            usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_ACK, status);
            endpoint_event(address, status);
        }
        usb_write(SNC_USB_BASE + SNC_USB_ENDPOINT_SELECT, previous);
    }
    dispatching = false;
}

bool kb7_usb_init(void) {
    reset_software_state();
    device_state = KB7_USB_DETACHED;
    controller_available = false;
    dispatching = false;

    if (KB7_USB_VENDOR_ID == 0U || KB7_USB_PRODUCT_ID == 0U ||
        KB7_USB_BOARD_PROFILE_VERIFIED != 1) return false;

    /* Recovered from the independent stock HID and loader controller stacks. */
    usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, UINT32_C(0x00000020));
    usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, UINT32_C(0x00020000));
    usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, UINT32_C(0x00080000));
    usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_ACK, UINT32_C(0xffffffff));
    usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_EVENT_ENABLE, UINT32_C(0x07370800));
    usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_CONFIG, UINT32_C(0x00010001));
    usb_write(SNC_USB_BASE + USB_CONTROLLER_AUX_CONTROL,
              usb_read(SNC_USB_BASE + USB_CONTROLLER_AUX_CONTROL) | UINT32_C(0x0000ffff));
    usb_write(SNC_USB_BASE + SNC_USB_GLOBAL_CONTROL, UINT32_C(0x00004200));
    usb_write(SNC_SYS1_BASE + SNC_SYS1_USB_CONTROL, UINT32_C(0x28));
    kb7_dsb();
    controller_available = true;
    bus_reset();
    usb_write(SNC_USB_PHY_GATE, usb_read(SNC_USB_PHY_GATE) | KB7_BIT(16));
#if !defined(KB7_USB_TEST)
    KB7_MMIO32(SNC_NVIC_ICPR) = KB7_BIT(6);
    KB7_MMIO32(SNC_NVIC_ISER) = KB7_BIT(6);
    kb7_dsb();
#endif
    return true;
}

void kb7_usb_poll(void) {
    dispatch_controller();
}

void kb7_usb_irq_handler(void) {
    dispatch_controller();
}

int32_t kb7_usb_send(uint8_t endpoint, const void *data, uint16_t length) {
    if (data == NULL || length == 0U || length > KB7_USB_ENDPOINT_SIZE ||
        endpoint == 0U || endpoint >= USB_ENDPOINT_COUNT) return KB7_USB_INVALID;
    if (endpoint != KB7_USB_DATA_ENDPOINT) return KB7_USB_UNAVAILABLE;

    const uint8_t *const bytes = (const uint8_t *)data;
    if ((bytes[0] == KB7_REPORT_ID_KEYBOARD && length != sizeof(last_keyboard)) ||
        (bytes[0] == KB7_REPORT_ID_CONSUMER && length != sizeof(last_consumer)) ||
        (bytes[0] == KB7_REPORT_ID_ANALOG && length != sizeof(last_gamepad)) ||
        (bytes[0] == KB7_USB_GAMEPAD_REPORT_ID && length != sizeof(last_joystick)) ||
        (bytes[0] == KB7_REPORT_ID_VENDOR && length != sizeof(last_vendor)) ||
        report_index(bytes[0]) == 0xffU) return KB7_USB_INVALID;

    const uint32_t interrupt_state = usb_critical_enter();
    if (!controller_available || device_state != KB7_USB_CONFIGURED ||
        endpoint_halt[endpoint][1]) {
        usb_critical_exit(interrupt_state);
        return KB7_USB_UNAVAILABLE;
    }
    const int32_t result = enqueue_in(endpoint, data, length);
    if (result != KB7_USB_OK) {
        usb_critical_exit(interrupt_state);
        return result;
    }
    if (bytes[0] == KB7_REPORT_ID_KEYBOARD) kb7_memcpy(last_keyboard, data, length);
    else if (bytes[0] == KB7_REPORT_ID_CONSUMER) kb7_memcpy(last_consumer, data, length);
    else if (bytes[0] == KB7_REPORT_ID_ANALOG) kb7_memcpy(last_gamepad, data, length);
    else if (bytes[0] == KB7_USB_GAMEPAD_REPORT_ID)
        kb7_memcpy(last_joystick, data, length);
    else kb7_memcpy(last_vendor, data, length);
    usb_critical_exit(interrupt_state);
    return KB7_USB_OK;
}

/* Core 0 does not originate application reports, but these APIs remain safe. */
void kb7_usb_keyboard_report(const uint8_t bits[19], uint8_t modifiers) {
    if (bits == NULL) return;
    uint8_t report[KB7_KEYBOARD_REPORT_BYTES];
    report[0] = KB7_REPORT_ID_KEYBOARD;
    report[1] = modifiers;
    kb7_memcpy(&report[2], bits, 19U);
    (void)kb7_usb_send(KB7_USB_DATA_ENDPOINT, report, sizeof(report));
}

void kb7_usb_keyboard_action(uint16_t usage, bool pressed) {
    if (usage >= 0xe0U && usage <= 0xe7U) {
        const uint8_t bit = (uint8_t)KB7_BIT(usage - 0xe0U);
        if (pressed) last_keyboard[1] |= bit;
        else last_keyboard[1] &= (uint8_t)~bit;
    } else if (usage < KB7_KEYBOARD_USAGE_BITS) {
        const size_t byte = 2U + (usage >> 3U);
        const uint8_t bit = (uint8_t)KB7_BIT(usage & 7U);
        if (pressed) last_keyboard[byte] |= bit;
        else last_keyboard[byte] &= (uint8_t)~bit;
    } else {
        return;
    }
    (void)kb7_usb_send(KB7_USB_DATA_ENDPOINT, last_keyboard, sizeof(last_keyboard));
}

void kb7_usb_consumer_usage(uint16_t usage) {
    const uint8_t report[KB7_CONSUMER_REPORT_BYTES] = {
        KB7_REPORT_ID_CONSUMER, (uint8_t)usage, (uint8_t)(usage >> 8U)
    };
    (void)kb7_usb_send(KB7_USB_DATA_ENDPOINT, report, sizeof(report));
}

void kb7_usb_consumer_action(uint16_t usage, bool pressed) {
    kb7_usb_consumer_usage(pressed ? usage : 0U);
}

void kb7_usb_consumer_pulse(uint16_t usage) {
    kb7_usb_consumer_usage(usage);
    kb7_usb_consumer_usage(0U);
}

enum kb7_usb_device_state kb7_usb_state(void) {
    return device_state;
}

bool kb7_usb_configured(void) {
    return controller_available && device_state == KB7_USB_CONFIGURED;
}

uint8_t kb7_usb_keyboard_leds(void) {
    return keyboard_led_state;
}

#if defined(KB7_USB_TEST)
void kb7_usb_test_reset(void) {
    controller_available = true;
    dispatching = false;
    reset_software_state();
}

void kb7_usb_test_bus_reset(void) {
    bus_reset();
}

void kb7_usb_test_set_configured(bool configured) {
    configuration_value = configured ? 1U : 0U;
    device_state = configured ? KB7_USB_CONFIGURED : KB7_USB_DEFAULT;
    if (configured) configure_data_endpoints();
    else disable_data_endpoints();
}

void kb7_usb_test_complete_in(uint8_t endpoint) {
    if (endpoint == 0U)
        endpoint_event(USB_DIRECTION_IN, USB_CONTROLLER_EP_IN_COMPLETE);
    else complete_in(endpoint);
}

bool kb7_usb_test_begin_control(const struct kb7_usb_setup_packet *setup) {
    if (setup == NULL) return false;
    struct kb7_usb_control_response response;
    const int32_t result = kb7_usb_control_request(setup, NULL, 0U, &response);
    if (result != KB7_USB_OK) return false;
    ep0_reply(&response, setup);
    return true;
}

bool kb7_usb_test_complete_out(uint8_t endpoint, const void *data, uint16_t length) {
    if (endpoint >= USB_ENDPOINT_COUNT || data == NULL ||
        !out_endpoints[endpoint].active || length > out_endpoints[endpoint].requested)
        return false;
    kb7_memcpy(out_endpoints[endpoint].data, data, length);
    out_endpoints[endpoint].dma[0].length =
        (out_endpoints[endpoint].dma[0].length & ~USB_DMA_LENGTH_MASK) | length;
    endpoint_event(endpoint, USB_CONTROLLER_EP_EVENT_A);
    return true;
}

void kb7_usb_test_global_events(uint32_t events) {
    global_events(events);
}

bool kb7_usb_test_apply_halt(uint8_t address, bool set) {
    return endpoint_apply_halt(address, set);
}

uint8_t kb7_usb_test_queue_depth(uint8_t endpoint) {
    return endpoint < USB_ENDPOINT_COUNT ? in_endpoints[endpoint].count : 0U;
}

uint16_t kb7_usb_test_active_length(uint8_t endpoint) {
    if (endpoint >= USB_ENDPOINT_COUNT || in_endpoints[endpoint].count == 0U) return 0U;
    return in_endpoints[endpoint].length[in_endpoints[endpoint].head];
}

const uint8_t *kb7_usb_test_active_data(uint8_t endpoint) {
    if (endpoint >= USB_ENDPOINT_COUNT || in_endpoints[endpoint].count == 0U) return NULL;
    return in_endpoints[endpoint].data[in_endpoints[endpoint].head];
}

bool kb7_usb_test_out_active(uint8_t endpoint) {
    return endpoint < USB_ENDPOINT_COUNT && out_endpoints[endpoint].active;
}

const uint8_t *kb7_usb_device_descriptor_data(uint16_t *length) {
    if (length != NULL) *length = sizeof(device_descriptor);
    return (const uint8_t *)&device_descriptor;
}

const uint8_t *kb7_usb_configuration_descriptor_data(uint16_t *length) {
    if (length != NULL) *length = sizeof(configuration_descriptor);
    return configuration_descriptor;
}

const uint8_t *kb7_usb_report_descriptor_data(uint16_t *length) {
    if (length != NULL) *length = sizeof(report_descriptor);
    return report_descriptor;
}
#endif
