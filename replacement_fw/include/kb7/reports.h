#ifndef KB7_REPORTS_H
#define KB7_REPORTS_H

#include "kb7/platform.h"

/* Each report has one identifier and one fixed wire size. */
#define KB7_REPORT_ID_KEYBOARD 0x04U
#define KB7_REPORT_ID_CONSUMER 0x05U
#define KB7_REPORT_ID_ANALOG 0x06U
#define KB7_REPORT_ID_VENDOR 0x5cU

#define KB7_KEYBOARD_USAGE_BITS 152U
#define KB7_KEYBOARD_REPORT_BYTES 21U
#define KB7_CONSUMER_REPORT_BYTES 3U
#define KB7_ANALOG_REPORT_BYTES 64U
#define KB7_ANALOG_VALUES_PER_PAGE 60U

_Static_assert(KB7_REPORT_ID_KEYBOARD != KB7_REPORT_ID_CONSUMER &&
               KB7_REPORT_ID_KEYBOARD != KB7_REPORT_ID_ANALOG &&
               KB7_REPORT_ID_KEYBOARD != KB7_REPORT_ID_VENDOR &&
               KB7_REPORT_ID_CONSUMER != KB7_REPORT_ID_ANALOG &&
               KB7_REPORT_ID_CONSUMER != KB7_REPORT_ID_VENDOR &&
               KB7_REPORT_ID_ANALOG != KB7_REPORT_ID_VENDOR,
               "report IDs must be unique");

struct kb7_hid_binding {
    uint8_t usage;
    uint8_t modifier_mask;
};

bool kb7_keymap_lookup(uint8_t sensor, struct kb7_hid_binding *binding);

#endif
