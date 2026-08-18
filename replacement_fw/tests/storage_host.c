#define _GNU_SOURCE
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "kb7/runtime.h"
#include "kb7/storage.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

static uint8_t slot_a[KB7_STORAGE_SCREEN_SLOT_BYTES];
static uint8_t slot_b[KB7_STORAGE_SCREEN_SLOT_BYTES];
static uint8_t profile_a[KB7_STORAGE_PROFILE_SLOT_BYTES];
static uint8_t profile_b[KB7_STORAGE_PROFILE_SLOT_BYTES];

static int32_t flash_read(uint32_t offset, void *data, uint32_t length) {
    uint8_t *slot;
    uint32_t relative;
    if (offset >= KB7_STORAGE_SCREEN_A &&
        offset <= KB7_STORAGE_SCREEN_A + KB7_STORAGE_SCREEN_SLOT_BYTES &&
        length <= KB7_STORAGE_SCREEN_A + KB7_STORAGE_SCREEN_SLOT_BYTES - offset) {
        slot = slot_a;
        relative = offset - KB7_STORAGE_SCREEN_A;
    } else if (offset >= KB7_STORAGE_SCREEN_B &&
               offset <= KB7_STORAGE_SCREEN_B + KB7_STORAGE_SCREEN_SLOT_BYTES &&
               length <= KB7_STORAGE_SCREEN_B + KB7_STORAGE_SCREEN_SLOT_BYTES - offset) {
        slot = slot_b;
        relative = offset - KB7_STORAGE_SCREEN_B;
    } else if (offset >= KB7_STORAGE_PROFILE_A &&
               offset <= KB7_STORAGE_PROFILE_A + KB7_STORAGE_PROFILE_SLOT_BYTES &&
               length <= KB7_STORAGE_PROFILE_A + KB7_STORAGE_PROFILE_SLOT_BYTES - offset) {
        slot = profile_a;
        relative = offset - KB7_STORAGE_PROFILE_A;
    } else if (offset >= KB7_STORAGE_PROFILE_B &&
               offset <= KB7_STORAGE_PROFILE_B + KB7_STORAGE_PROFILE_SLOT_BYTES &&
               length <= KB7_STORAGE_PROFILE_B + KB7_STORAGE_PROFILE_SLOT_BYTES - offset) {
        slot = profile_b;
        relative = offset - KB7_STORAGE_PROFILE_B;
    } else {
        return -1;
    }
    memcpy(data, &slot[relative], length);
    return 0;
}

static void make_slot(uint8_t *slot, size_t capacity, uint32_t generation, uint8_t fill) {
    struct kb7_slot_header header;
    uint8_t payload[48];
    memset(slot, 0xff, capacity);
    memset(payload, fill, sizeof(payload));
    memset(&header, 0, sizeof(header));
    header.magic = KB7_STORAGE_SLOT_MAGIC;
    header.version = KB7_STORAGE_SLOT_VERSION;
    header.header_length = sizeof(header);
    header.state = KB7_SLOT_VALID;
    header.generation = generation;
    header.payload_length = sizeof(payload);
    header.payload_crc32 = kb7_crc32(payload, sizeof(payload));
    header.header_crc32 = 0U;
    header.header_crc32 = kb7_crc32(&header, sizeof(header));
    memcpy(slot, &header, sizeof(header));
    memcpy(slot + sizeof(header), payload, sizeof(payload));
}

int main(void) {
    void *mapping = mmap((void *)(uintptr_t)KB7_SHARED_API_ADDRESS, 4096U,
                         PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (mapping == MAP_FAILED) return 77;
    volatile struct kb7_runtime_api *api = kb7_runtime();
    memset((void *)api, 0, sizeof(*api));
    api->magic = KB7_RUNTIME_MAGIC;
    api->flash_read = flash_read;

    make_slot(slot_a, sizeof(slot_a), 1U, 0x11U);
    make_slot(slot_b, sizeof(slot_b), 2U, 0x22U);
    if (kb7_storage_select().offset != KB7_STORAGE_SCREEN_B) return 1;

    slot_b[sizeof(struct kb7_slot_header)] ^= 1U;
    if (kb7_storage_select().offset != KB7_STORAGE_SCREEN_A) return 2;

    make_slot(slot_b, sizeof(slot_b), 2U, 0x22U);
    struct kb7_slot_header *header = (struct kb7_slot_header *)slot_b;
    header->reserved[0] = 1U;
    header->header_crc32 = 0U;
    header->header_crc32 = kb7_crc32(header, sizeof(*header));
    if (kb7_storage_select().offset != KB7_STORAGE_SCREEN_A) return 3;

    make_slot(profile_a, sizeof(profile_a), 7U, 0x33U);
    make_slot(profile_b, sizeof(profile_b), 9U, 0x44U);
    if (kb7_storage_select_profiles().offset != KB7_STORAGE_PROFILE_B) return 4;
    profile_b[sizeof(struct kb7_slot_header)] ^= 1U;
    if (kb7_storage_select_profiles().offset != KB7_STORAGE_PROFILE_A) return 5;

    const uint8_t sample[] = {1U, 2U, 3U, 4U, 5U};
    uint32_t crc = kb7_crc32_begin();
    crc = kb7_crc32_extend(crc, sample, 2U);
    crc = kb7_crc32_extend(crc, sample + 2U, sizeof(sample) - 2U);
    if (kb7_crc32_finish(crc) != kb7_crc32(sample, sizeof(sample))) return 6;
    return 0;
}
