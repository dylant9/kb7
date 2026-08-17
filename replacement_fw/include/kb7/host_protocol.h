#ifndef KB7_HOST_PROTOCOL_H
#define KB7_HOST_PROTOCOL_H

#include "kb7/platform.h"

#define KB7_VENDOR_REPORT_ID 0x5cU
#define KB7_HOST_PROTOCOL_VERSION 1U
#define KB7_HOST_REPORT_SIZE 64U
#define KB7_HOST_PAYLOAD_SIZE 36U

enum kb7_host_kind { KB7_HOST_COMMAND = 1, KB7_HOST_RESPONSE = 2, KB7_HOST_EVENT = 3 };
enum kb7_host_opcode {
    KB7_HOST_QUERY_VERSION = 0x01,
    KB7_HOST_QUERY_CAPABILITIES = 0x02,
    KB7_HOST_TRANSFER_BEGIN = 0x10,
    KB7_HOST_TRANSFER_WRITE = 0x11,
    KB7_HOST_TRANSFER_COMMIT = 0x12,
    KB7_HOST_TRANSFER_ABORT = 0x13,
    KB7_HOST_STORE_READ = 0x14,
    KB7_HOST_STORE_SELECT = 0x15,
    KB7_HOST_STORE_FACTORY_RESET = 0x16,
    KB7_HOST_WIDGET_EVENT = 0x40,
    KB7_HOST_ENTER_LOADER = 0x7e,
};
enum kb7_host_status {
    KB7_HOST_STATUS_OK = 0,
    KB7_HOST_STATUS_BAD_VERSION = 1,
    KB7_HOST_STATUS_BAD_CRC = 2,
    KB7_HOST_STATUS_BAD_LENGTH = 3,
    KB7_HOST_STATUS_BAD_STATE = 4,
    KB7_HOST_STATUS_RANGE = 5,
    KB7_HOST_STATUS_STORAGE = 6,
    KB7_HOST_STATUS_UNSUPPORTED = 7,
};

struct KB7_PACKED kb7_host_report {
    uint8_t report_id;
    uint8_t version;
    uint8_t kind;
    uint8_t opcode;
    uint8_t flags;
    uint8_t status;
    uint16_t sequence;
    uint32_t transfer_id;
    uint32_t offset;
    uint32_t total_length;
    uint32_t payload_crc32;
    uint8_t payload[KB7_HOST_PAYLOAD_SIZE];
    uint32_t frame_crc32;
};

bool kb7_host_report_valid(const struct kb7_host_report *report);
void kb7_host_report_finalize(struct kb7_host_report *report);

#endif
