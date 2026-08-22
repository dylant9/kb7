#ifndef KB7_STORAGE_H
#define KB7_STORAGE_H

#include "kb7/platform.h"

#define KB7_STORAGE_SUPER_A UINT32_C(0x0156b000)
#define KB7_STORAGE_SUPER_B UINT32_C(0x0156c000)
#define KB7_STORAGE_STOCK_IMAGE_END UINT32_C(0x0156b000)
#define KB7_STORAGE_SCREEN_A UINT32_C(0x01570000)
#define KB7_STORAGE_SCREEN_B UINT32_C(0x016b0000)
#define KB7_STORAGE_SCREEN_SLOT_BYTES UINT32_C(0x00140000)
#define KB7_STORAGE_PROFILE_A UINT32_C(0x01c00000)
#define KB7_STORAGE_PROFILE_B UINT32_C(0x01c38000)
#define KB7_STORAGE_PROFILE_SLOT_BYTES UINT32_C(0x00038000)

/* Full-chip reads proved that these vendor partitions are not free tail space. */
#define KB7_STORAGE_STOCK_LEGACY_START UINT32_C(0x01800000)
#define KB7_STORAGE_STOCK_LEGACY_END UINT32_C(0x01a00000)
#define KB7_STORAGE_STOCK_CONFIG_START UINT32_C(0x01a00000)
#define KB7_STORAGE_STOCK_CONFIG_END UINT32_C(0x01c00000)
#define KB7_STORAGE_STOCK_UPLOAD_START UINT32_C(0x01f00000)
#define KB7_STORAGE_STOCK_UPLOAD_END UINT32_C(0x02000000)

_Static_assert(KB7_STORAGE_SCREEN_A + KB7_STORAGE_SCREEN_SLOT_BYTES ==
                   KB7_STORAGE_SCREEN_B,
               "screen slots must be adjacent");
_Static_assert(KB7_STORAGE_SCREEN_A >= KB7_STORAGE_STOCK_IMAGE_END,
               "screen slots overlap the stock manifest image");
_Static_assert(KB7_STORAGE_SCREEN_B + KB7_STORAGE_SCREEN_SLOT_BYTES <=
                   KB7_STORAGE_STOCK_LEGACY_START,
               "screen slots overlap stock configuration storage");
_Static_assert(KB7_STORAGE_PROFILE_A >= KB7_STORAGE_STOCK_CONFIG_END &&
                   KB7_STORAGE_PROFILE_B + KB7_STORAGE_PROFILE_SLOT_BYTES <=
                       KB7_STORAGE_STOCK_UPLOAD_START,
               "profile slots overlap stock-owned flash");
_Static_assert(KB7_STORAGE_PROFILE_A + KB7_STORAGE_PROFILE_SLOT_BYTES ==
                   KB7_STORAGE_PROFILE_B,
               "profile slots must be adjacent");
#define KB7_STORAGE_SLOT_MAGIC UINT32_C(0x314c534b) /* KSL1 */
#define KB7_STORAGE_SLOT_VERSION 1U

enum kb7_slot_state { KB7_SLOT_ERASED = 0xffffffffU, KB7_SLOT_WRITING = 0x7fffffffU,
                      KB7_SLOT_VALID = 0x3fffffffU };

struct KB7_PACKED kb7_slot_header {
    uint32_t magic;
    uint16_t version;
    uint16_t header_length;
    uint32_t state;
    uint32_t generation;
    uint32_t payload_length;
    uint32_t payload_crc32;
    uint32_t header_crc32;
    uint8_t reserved[36];
};

struct kb7_slot_choice { uint32_t offset; struct kb7_slot_header header; bool valid; };
bool kb7_storage_header_valid(const struct kb7_slot_header *header);
struct kb7_slot_choice kb7_storage_read_slot(uint32_t offset);
struct kb7_slot_choice kb7_storage_select_pair(uint32_t slot_a, uint32_t slot_b);
struct kb7_slot_choice kb7_storage_select(void);
struct kb7_slot_choice kb7_storage_select_profiles(void);

#endif
