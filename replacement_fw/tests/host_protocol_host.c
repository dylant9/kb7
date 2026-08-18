#include "kb7/host_protocol.h"

int main(void) {
    struct kb7_host_report report;
    kb7_memset(&report, 0, sizeof(report));
    report.kind = KB7_HOST_COMMAND;
    report.opcode = KB7_HOST_QUERY_VERSION;
    kb7_host_report_finalize(&report);
    if (kb7_host_report_validate(&report) != KB7_HOST_FRAME_VALID) return 1;

    report.version = 2U;
    report.frame_crc32 = kb7_crc32(&report.version, 59U);
    if (kb7_host_report_validate(&report) != KB7_HOST_FRAME_BAD_VERSION) return 2;
    report.version = KB7_HOST_PROTOCOL_VERSION;
    report.frame_crc32 = kb7_crc32(&report.version, 59U);
    report.payload[0] ^= 1U;
    if (kb7_host_report_validate(&report) != KB7_HOST_FRAME_BAD_PAYLOAD_CRC) return 3;
    report.payload_crc32 = kb7_crc32(report.payload, sizeof(report.payload));
    if (kb7_host_report_validate(&report) != KB7_HOST_FRAME_BAD_FRAME_CRC) return 4;
    return 0;
}
