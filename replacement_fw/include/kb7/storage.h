#ifndef KB7_STORAGE_H
#define KB7_STORAGE_H

#include "kb7/platform.h"

#define KB7_STORAGE_SUPER_A UINT32_C(0x0156b000)
#define KB7_STORAGE_SUPER_B UINT32_C(0x0156c000)
#define KB7_STORAGE_SCREEN_A UINT32_C(0x01570000)
#define KB7_STORAGE_SCREEN_B UINT32_C(0x01770000)
#define KB7_STORAGE_SCREEN_SLOT_BYTES UINT32_C(0x00200000)
#define KB7_STORAGE_PROFILE_A UINT32_C(0x01f70000)
#define KB7_STORAGE_PROFILE_B UINT32_C(0x01fa8000)
#define KB7_STORAGE_PROFILE_SLOT_BYTES UINT32_C(0x00038000)
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
