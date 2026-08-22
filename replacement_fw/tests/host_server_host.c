#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "kb7/host_server.h"
#include "kb7/profile_blob.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"
#include "kb7/screen.h"
#include "kb7/storage.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

#define FLASH_XIP_BASE UINT32_C(0x60000000)
#define FLASH_BYTES UINT32_C(0x02000000)

struct KB7_PACKED minimal_screen {
    struct kb7_screen_header header;
    struct kb7_screen_record screen;
};

static uint32_t last_erased;
static uint32_t fake_milliseconds;
static uint32_t erase_advance_ms;
static uint32_t flash_read_calls;
static uint32_t flash_read_bytes;
static uint32_t erase_fail_offset = UINT32_MAX;
static uint8_t profile_blob[KB7_PROFILE_MAX_SIZE];

static uint32_t milliseconds(void) { return fake_milliseconds; }

static int32_t flash_read(uint32_t offset, void *data, uint32_t length) {
    if (data == NULL || offset > FLASH_BYTES || length > FLASH_BYTES - offset) return -1;
    ++flash_read_calls;
    flash_read_bytes += length;
    memcpy(data, (const void *)(uintptr_t)(FLASH_XIP_BASE + offset), length);
    return 0;
}

static int32_t flash_erase(uint32_t offset) {
    if ((offset & 0xfffU) != 0U || offset > FLASH_BYTES - 0x1000U) return -1;
    if (offset == erase_fail_offset) return -1;
    memset((void *)(uintptr_t)(FLASH_XIP_BASE + offset), 0xff, 0x1000U);
    last_erased = offset;
    fake_milliseconds += erase_advance_ms;
    return 0;
}

static int32_t flash_program(uint32_t offset, const void *data, uint32_t length) {
    if (data == NULL || offset > FLASH_BYTES || length > FLASH_BYTES - offset) return -1;
    uint8_t *target = (uint8_t *)(uintptr_t)(FLASH_XIP_BASE + offset);
    const uint8_t *source = (const uint8_t *)data;
    for (uint32_t index = 0U; index < length; ++index) {
        if ((source[index] | target[index]) != target[index]) return -1;
        target[index] &= source[index];
    }
    return 0;
}

bool kb7_ui_navigate(uint16_t screen_id) {
    return screen_id == 1U;
}

static struct minimal_screen make_screen(uint16_t background) {
    struct minimal_screen result;
    memset(&result, 0, sizeof(result));
    result.header.magic = KB7_SCREEN_MAGIC;
    result.header.version = KB7_SCREEN_VERSION;
    result.header.header_length = KB7_SCREEN_HEADER_SIZE;
    result.header.total_length = sizeof(result);
    result.header.screen_count = 1U;
    result.header.boot_screen = 1U;
    result.header.screens_offset = sizeof(result.header);
    result.header.widgets_offset = sizeof(result);
    result.header.strings_offset = sizeof(result);
    result.screen.id = 1U;
    result.screen.background_rgb565 = background;
    result.header.body_crc32 = kb7_crc32(&result.screen, sizeof(result.screen));
    return result;
}

static enum kb7_host_status process(struct kb7_host_server *server,
                                    struct kb7_host_report *command,
                                    struct kb7_host_report *response) {
    kb7_host_report_finalize(command);
    kb7_host_server_process(server, command, response);
    if (!kb7_host_report_valid(response)) return KB7_HOST_STATUS_BAD_CRC;
    return (enum kb7_host_status)response->status;
}

static int transfer(struct kb7_host_server *server, const void *payload, uint32_t length,
                    uint32_t transfer_id, uint8_t store) {
    struct kb7_host_report command;
    struct kb7_host_report response;
    const uint32_t crc = kb7_crc32(payload, length);
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_BEGIN;
    command.flags = store;
    command.transfer_id = transfer_id;
    command.total_length = length;
    memcpy(command.payload, &crc, sizeof(crc));
    if (process(server, &command, &response) != KB7_HOST_STATUS_OK) return 1;

    for (uint32_t offset = 0U; offset < length; offset += KB7_HOST_PAYLOAD_SIZE) {
        uint32_t count = length - offset;
        if (count > KB7_HOST_PAYLOAD_SIZE) count = KB7_HOST_PAYLOAD_SIZE;
        memset(&command, 0, sizeof(command));
        command.kind = KB7_HOST_COMMAND;
        command.opcode = KB7_HOST_TRANSFER_WRITE;
        command.flags = store;
        command.transfer_id = transfer_id;
        command.offset = offset;
        command.total_length = length;
        memcpy(command.payload, (const uint8_t *)payload + offset, count);
        if (process(server, &command, &response) != KB7_HOST_STATUS_OK) return 2;
    }
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_COMMIT;
    command.flags = store;
    command.transfer_id = transfer_id;
    command.offset = length;
    command.total_length = length;
    memcpy(command.payload, &crc, sizeof(crc));
    return process(server, &command, &response) == KB7_HOST_STATUS_OK ? 0 : 3;
}

int main(int argc, char **argv) {
    if (argc != 2) return 76;
    FILE *profile_file = fopen(argv[1], "rb");
    if (profile_file == NULL) return 75;
    const size_t profile_length = fread(profile_blob, 1U, sizeof(profile_blob), profile_file);
    const int trailing = fgetc(profile_file);
    if (fclose(profile_file) != 0 || trailing != EOF ||
        profile_length < KB7_PROFILE_MIN_SIZE) return 74;
    void *api_mapping = mmap((void *)(uintptr_t)KB7_SHARED_API_ADDRESS, 4096U,
                             PROT_READ | PROT_WRITE,
                             MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    void *flash_mapping = mmap((void *)(uintptr_t)FLASH_XIP_BASE, FLASH_BYTES,
                               PROT_READ | PROT_WRITE,
                               MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (api_mapping == MAP_FAILED || flash_mapping == MAP_FAILED) return 77;
    memset(flash_mapping, 0xff, FLASH_BYTES);
    volatile struct kb7_runtime_api *api = kb7_runtime();
    memset((void *)api, 0, sizeof(*api));
    api->magic = KB7_RUNTIME_MAGIC;
    api->milliseconds = milliseconds;
    api->flash_read = flash_read;
    api->flash_erase_4k = flash_erase;
    api->flash_program = flash_program;

    struct kb7_host_server server;
    kb7_host_server_init(&server);
    const struct minimal_screen first = make_screen(0x1111U);
    const struct minimal_screen second = make_screen(0x2222U);
    if (transfer(&server, &first, sizeof(first), 1U, KB7_HOST_STORE_SCREEN) != 0) return 1;
    if (kb7_storage_select().offset != KB7_STORAGE_SCREEN_A) return 2;
    if (transfer(&server, &second, sizeof(second), 2U, KB7_HOST_STORE_SCREEN) != 0) return 3;
    if (kb7_storage_select().offset != KB7_STORAGE_SCREEN_B) return 4;

    uint8_t *flash = (uint8_t *)(uintptr_t)FLASH_XIP_BASE;
    struct kb7_slot_header *const newest_slot =
        (struct kb7_slot_header *)&flash[KB7_STORAGE_SCREEN_B];
    struct minimal_screen *const invalid_newest = (struct minimal_screen *)(void *)(
        &flash[KB7_STORAGE_SCREEN_B + sizeof(struct kb7_slot_header)]);
    invalid_newest->header.boot_screen = 2U; /* CRC-correct but no such screen. */
    newest_slot->payload_crc32 = kb7_crc32(invalid_newest, sizeof(*invalid_newest));
    newest_slot->header_crc32 = 0U;
    newest_slot->header_crc32 = kb7_crc32(newest_slot, sizeof(*newest_slot));
    if (kb7_storage_select().offset != KB7_STORAGE_SCREEN_B) return 5;

    struct kb7_host_report command;
    struct kb7_host_report response;
    const uint32_t crc = kb7_crc32(&second, sizeof(second));
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_BEGIN;
    command.transfer_id = 3U;
    command.total_length = sizeof(second);
    memcpy(command.payload, &crc, sizeof(crc));
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 6;
    if (last_erased != KB7_STORAGE_SCREEN_B || !kb7_storage_read_slot(KB7_STORAGE_SCREEN_A).valid)
        return 7;

    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_ABORT;
    command.transfer_id = 3U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 8;

    /* An abandoned transfer expires without touching the previous valid slot. */
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_BEGIN;
    command.transfer_id = 4U;
    command.total_length = sizeof(second);
    memcpy(command.payload, &crc, sizeof(crc));
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 12;
    fake_milliseconds += KB7_HOST_TRANSFER_TIMEOUT_MS;
    command.transfer_id = 5U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 13;
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_ABORT;
    command.transfer_id = 5U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 14;

    /* Slow erase time is measured after BEGIN, so it cannot instantly expire. */
    erase_advance_ms = KB7_HOST_TRANSFER_TIMEOUT_MS + 1U;
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_BEGIN;
    command.transfer_id = 6U;
    command.total_length = sizeof(second);
    memcpy(command.payload, &crc, sizeof(crc));
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 15;
    erase_advance_ms = 0U;
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_WRITE;
    command.transfer_id = 6U;
    command.total_length = sizeof(second);
    memcpy(command.payload, &second, KB7_HOST_PAYLOAD_SIZE);
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 16;
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_ABORT;
    command.transfer_id = 6U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 17;

    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_STORE_READ;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK ||
        response.total_length != sizeof(first) ||
        memcmp(response.payload, &first, KB7_HOST_PAYLOAD_SIZE) != 0) return 9;
    const uint32_t reads_after_first = flash_read_calls;
    const uint32_t bytes_after_first = flash_read_bytes;
    command.offset = KB7_HOST_PAYLOAD_SIZE;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK ||
        response.total_length != sizeof(first) ||
        response.offset != sizeof(first) ||
        flash_read_calls != reads_after_first + 1U ||
        flash_read_bytes != bytes_after_first + sizeof(first) - KB7_HOST_PAYLOAD_SIZE) return 26;

    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_STORE_SELECT;
    command.offset = 1U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 10;

    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_QUERY_CAPABILITIES;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK ||
        response.payload[10] != KB7_SCREEN_VERSION ||
        response.payload[11] != KB7_PROFILE_VERSION ||
        response.payload[12] != KB7_INPUT_PROFILE_SLOT_COUNT ||
        response.payload[14] != (uint8_t)KB7_PROFILE_RECORD_SIZE ||
        response.payload[15] != (uint8_t)(KB7_PROFILE_RECORD_SIZE >> 8U)) return 25;

    const uint32_t erased_before_short_screen = last_erased;
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_BEGIN;
    command.transfer_id = 30U;
    command.total_length = KB7_SCREEN_MIN_SIZE - 1U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_RANGE ||
        last_erased != erased_before_short_screen) return 29;
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_ENTER_LOADER;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_UNSUPPORTED) return 30;

    /* Profile BEGIN rejects impossible v1 sizes before wearing the inactive slot. */
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_BEGIN;
    command.flags = KB7_HOST_STORE_PROFILE;
    command.transfer_id = 7U;
    command.total_length = KB7_PROFILE_MIN_SIZE - 1U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_RANGE) return 18;
    command.total_length = KB7_PROFILE_MAX_SIZE + 1U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_RANGE) return 19;
    command.total_length = KB7_PROFILE_MAX_SIZE;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 20;
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_ABORT;
    command.flags = KB7_HOST_STORE_PROFILE;
    command.transfer_id = 7U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 21;

    if (transfer(&server, profile_blob, (uint32_t)profile_length, 8U,
                 KB7_HOST_STORE_PROFILE) != 0 ||
        kb7_storage_select_profiles().offset != KB7_STORAGE_PROFILE_A) return 22;
    if (transfer(&server, profile_blob, (uint32_t)profile_length, 9U,
                 KB7_HOST_STORE_PROFILE) != 0 ||
        kb7_storage_select_profiles().offset != KB7_STORAGE_PROFILE_B) return 23;
    flash[KB7_STORAGE_PROFILE_B + sizeof(struct kb7_slot_header)] ^= 1U;
    if (kb7_storage_select_profiles().offset != KB7_STORAGE_PROFILE_A) return 24;

    /* Once every payload byte is accepted, an extra zero-length WRITE is a
     * protocol error rather than a successful no-op. */
    const struct minimal_screen complete_write = make_screen(0x3333U);
    const uint32_t complete_crc = kb7_crc32(&complete_write, sizeof(complete_write));
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_BEGIN;
    command.transfer_id = 10U;
    command.total_length = sizeof(complete_write);
    memcpy(command.payload, &complete_crc, sizeof(complete_crc));
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 33;
    for (uint32_t offset = 0U; offset < sizeof(complete_write);
         offset += KB7_HOST_PAYLOAD_SIZE) {
        uint32_t count = sizeof(complete_write) - offset;
        if (count > KB7_HOST_PAYLOAD_SIZE) count = KB7_HOST_PAYLOAD_SIZE;
        memset(&command, 0, sizeof(command));
        command.kind = KB7_HOST_COMMAND;
        command.opcode = KB7_HOST_TRANSFER_WRITE;
        command.transfer_id = 10U;
        command.offset = offset;
        command.total_length = sizeof(complete_write);
        memcpy(command.payload, (const uint8_t *)&complete_write + offset, count);
        if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 34;
    }
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_WRITE;
    command.transfer_id = 10U;
    command.offset = sizeof(complete_write);
    command.total_length = sizeof(complete_write);
    if (process(&server, &command, &response) != KB7_HOST_STATUS_BAD_STATE) return 35;
    command.opcode = KB7_HOST_TRANSFER_ABORT;
    command.offset = 0U;
    command.total_length = 0U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 36;

    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_STORE_FACTORY_RESET;
    command.flags = 0xa5U;
    command.transfer_id = UINT32_C(0x4b423752);
    memcpy(command.payload, "RESETKB7", 8U);
    erase_fail_offset = KB7_STORAGE_SCREEN_B;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_STORAGE) return 27;
    if (!kb7_host_server_take_storage_invalidation(&server) ||
        kb7_host_server_take_storage_invalidation(&server)) return 31;
    struct kb7_host_report read_after_failed_reset;
    memset(&read_after_failed_reset, 0, sizeof(read_after_failed_reset));
    read_after_failed_reset.kind = KB7_HOST_COMMAND;
    read_after_failed_reset.opcode = KB7_HOST_STORE_READ;
    if (process(&server, &read_after_failed_reset, &response) !=
        KB7_HOST_STATUS_BAD_STATE) return 28;
    erase_fail_offset = UINT32_MAX;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK ||
        kb7_storage_select().valid || kb7_storage_select_profiles().valid) return 11;
    if (!kb7_host_server_take_storage_invalidation(&server) ||
        kb7_host_server_take_storage_invalidation(&server)) return 32;
    return 0;
}
