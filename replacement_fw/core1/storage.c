#include "kb7/runtime.h"
#include "kb7/storage.h"

_Static_assert(sizeof(struct kb7_slot_header) == 64U, "slot header wire size changed");

static uint32_t header_crc(const struct kb7_slot_header *header) {
    struct kb7_slot_header copy = *header;
    copy.state = KB7_SLOT_VALID;
    copy.header_crc32 = 0U;
    return kb7_crc32(&copy, sizeof(copy));
}

bool kb7_storage_header_valid(const struct kb7_slot_header *header) {
    if (header == NULL || header->magic != KB7_STORAGE_SLOT_MAGIC ||
        header->version != KB7_STORAGE_SLOT_VERSION ||
        header->header_length != sizeof(*header) || header->state != KB7_SLOT_VALID ||
        header->payload_length < 48U ||
        header->payload_length > KB7_STORAGE_SCREEN_SLOT_BYTES - sizeof(*header) ||
        header->header_crc32 != header_crc(header)) {
        return false;
    }
    for (size_t index = 0U; index < sizeof(header->reserved); ++index) {
        if (header->reserved[index] != 0U) return false;
    }
    return true;
}

static bool payload_crc_valid(uint32_t offset, const struct kb7_slot_header *header) {
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (api->magic != KB7_RUNTIME_MAGIC || api->flash_read == NULL) return false;
    uint8_t block[128];
    uint32_t remaining = header->payload_length;
    uint32_t cursor = offset + (uint32_t)sizeof(*header);
    uint32_t crc = kb7_crc32_begin();
    while (remaining != 0U) {
        uint32_t count = remaining;
        if (count > sizeof(block)) count = sizeof(block);
        if (api->flash_read(cursor, block, count) != 0) return false;
        crc = kb7_crc32_extend(crc, block, count);
        cursor += count;
        remaining -= count;
    }
    return kb7_crc32_finish(crc) == header->payload_crc32;
}

struct kb7_slot_choice kb7_storage_read_slot(uint32_t offset) {
    struct kb7_slot_choice result;
    result.offset = offset;
    result.valid = false;
    kb7_memset(&result.header, 0, sizeof(result.header));
    if (offset != KB7_STORAGE_SCREEN_A && offset != KB7_STORAGE_SCREEN_B) return result;
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (api->magic == KB7_RUNTIME_MAGIC && api->flash_read != NULL &&
        api->flash_read(offset, &result.header, sizeof(result.header)) == 0 &&
        kb7_storage_header_valid(&result.header)) {
        result.valid = payload_crc_valid(offset, &result.header);
    }
    return result;
}

/*
 * Keep this comparison wrap-safe: a generation within INT32_MAX steps ahead
 * wins. Slots more ambiguous than that are treated according to this same
 * deterministic ordering by the writer and reader.
 */
static bool generation_after(uint32_t left, uint32_t right) {
    return (int32_t)(left - right) > 0;
}

struct kb7_slot_choice kb7_storage_select(void) {
    struct kb7_slot_choice a = kb7_storage_read_slot(KB7_STORAGE_SCREEN_A);
    struct kb7_slot_choice b = kb7_storage_read_slot(KB7_STORAGE_SCREEN_B);
    if (!a.valid) return b;
    if (!b.valid) return a;
    return generation_after(a.header.generation, b.header.generation) ? a : b;
}
