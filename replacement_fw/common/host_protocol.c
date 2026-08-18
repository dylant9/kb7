#include "kb7/host_protocol.h"

_Static_assert(sizeof(struct kb7_host_report) == KB7_HOST_REPORT_SIZE,
               "vendor report wire size changed");

enum kb7_host_validation kb7_host_report_validate(const struct kb7_host_report *report) {
    if (report == NULL || report->report_id != KB7_VENDOR_REPORT_ID) {
        return KB7_HOST_FRAME_BAD_ID;
    }
    if (report->version != KB7_HOST_PROTOCOL_VERSION) {
        return KB7_HOST_FRAME_BAD_VERSION;
    }
    if (report->payload_crc32 != kb7_crc32(report->payload, sizeof(report->payload))) {
        return KB7_HOST_FRAME_BAD_PAYLOAD_CRC;
    }
    if (report->frame_crc32 != kb7_crc32(&report->version, 59U)) {
        return KB7_HOST_FRAME_BAD_FRAME_CRC;
    }
    return KB7_HOST_FRAME_VALID;
}

bool kb7_host_report_valid(const struct kb7_host_report *report) {
    return kb7_host_report_validate(report) == KB7_HOST_FRAME_VALID;
}

void kb7_host_report_finalize(struct kb7_host_report *report) {
    report->report_id = KB7_VENDOR_REPORT_ID;
    report->version = KB7_HOST_PROTOCOL_VERSION;
    report->payload_crc32 = kb7_crc32(report->payload, sizeof(report->payload));
    report->frame_crc32 = kb7_crc32(&report->version, 59U);
}
