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
    return header != NULL && header->magic == KB7_STORAGE_SLOT_MAGIC &&
           header->version == KB7_STORAGE_SLOT_VERSION &&
           header->header_length == sizeof(*header) && header->state == KB7_SLOT_VALID &&
           header->payload_length >= 48U &&
           header->payload_length <= KB7_STORAGE_SCREEN_SLOT_BYTES - sizeof(*header) &&
           header->header_crc32 == header_crc(header);
}

static struct kb7_slot_choice read_choice(uint32_t offset) {
    struct kb7_slot_choice result;
    result.offset = offset;
    result.valid = false;
    kb7_memset(&result.header, 0, sizeof(result.header));
    volatile struct kb7_runtime_api *api = kb7_runtime();
    if (api->magic == KB7_RUNTIME_MAGIC && api->flash_read(offset, &result.header,
                                                            sizeof(result.header)) == 0) {
        result.valid = kb7_storage_header_valid(&result.header);
    }
    return result;
}

struct kb7_slot_choice kb7_storage_select(void) {
    struct kb7_slot_choice a = read_choice(KB7_STORAGE_SCREEN_A);
    struct kb7_slot_choice b = read_choice(KB7_STORAGE_SCREEN_B);
    if (!a.valid) {
        return b;
    }
    if (!b.valid) {
        return a;
    }
    return (int32_t)(a.header.generation - b.header.generation) > 0 ? a : b;
}
