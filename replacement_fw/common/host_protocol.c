#include "kb7/host_protocol.h"

_Static_assert(sizeof(struct kb7_host_report) == KB7_HOST_REPORT_SIZE,
               "vendor report wire size changed");

bool kb7_host_report_valid(const struct kb7_host_report *report) {
    if (report == NULL || report->report_id != KB7_VENDOR_REPORT_ID ||
        report->version != KB7_HOST_PROTOCOL_VERSION) {
        return false;
    }
    if (report->payload_crc32 != kb7_crc32(report->payload, sizeof(report->payload))) {
        return false;
    }
    return report->frame_crc32 == kb7_crc32(&report->version, 59U);
}

void kb7_host_report_finalize(struct kb7_host_report *report) {
    report->report_id = KB7_VENDOR_REPORT_ID;
    report->version = KB7_HOST_PROTOCOL_VERSION;
    report->payload_crc32 = kb7_crc32(report->payload, sizeof(report->payload));
    report->frame_crc32 = kb7_crc32(&report->version, 59U);
}
