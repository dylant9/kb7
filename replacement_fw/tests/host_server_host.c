#define _GNU_SOURCE
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "kb7/host_server.h"
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

static int32_t flash_read(uint32_t offset, void *data, uint32_t length) {
    if (data == NULL || offset > FLASH_BYTES || length > FLASH_BYTES - offset) return -1;
    memcpy(data, (const void *)(uintptr_t)(FLASH_XIP_BASE + offset), length);
    return 0;
}

static int32_t flash_erase(uint32_t offset) {
    if ((offset & 0xfffU) != 0U || offset > FLASH_BYTES - 0x1000U) return -1;
    memset((void *)(uintptr_t)(FLASH_XIP_BASE + offset), 0xff, 0x1000U);
    last_erased = offset;
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
                    uint32_t transfer_id) {
    struct kb7_host_report command;
    struct kb7_host_report response;
    const uint32_t crc = kb7_crc32(payload, length);
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_BEGIN;
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
        command.transfer_id = transfer_id;
        command.offset = offset;
        command.total_length = length;
        memcpy(command.payload, (const uint8_t *)payload + offset, count);
        if (process(server, &command, &response) != KB7_HOST_STATUS_OK) return 2;
    }
    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_TRANSFER_COMMIT;
    command.transfer_id = transfer_id;
    command.offset = length;
    command.total_length = length;
    memcpy(command.payload, &crc, sizeof(crc));
    return process(server, &command, &response) == KB7_HOST_STATUS_OK ? 0 : 3;
}

int main(void) {
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
    api->flash_read = flash_read;
    api->flash_erase_4k = flash_erase;
    api->flash_program = flash_program;

    struct kb7_host_server server;
    kb7_host_server_init(&server);
    const struct minimal_screen first = make_screen(0x1111U);
    const struct minimal_screen second = make_screen(0x2222U);
    if (transfer(&server, &first, sizeof(first), 1U) != 0) return 1;
    if (kb7_storage_select().offset != KB7_STORAGE_SCREEN_A) return 2;
    if (transfer(&server, &second, sizeof(second), 2U) != 0) return 3;
    if (kb7_storage_select().offset != KB7_STORAGE_SCREEN_B) return 4;

    uint8_t *flash = (uint8_t *)(uintptr_t)FLASH_XIP_BASE;
    flash[KB7_STORAGE_SCREEN_B + sizeof(struct kb7_slot_header)] ^= 1U;
    if (kb7_storage_select().offset != KB7_STORAGE_SCREEN_A) return 5;

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

    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_STORE_READ;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK ||
        response.total_length != sizeof(first) ||
        memcmp(response.payload, &first, KB7_HOST_PAYLOAD_SIZE) != 0) return 9;

    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_STORE_SELECT;
    command.offset = 1U;
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK) return 10;

    memset(&command, 0, sizeof(command));
    command.kind = KB7_HOST_COMMAND;
    command.opcode = KB7_HOST_STORE_FACTORY_RESET;
    command.flags = 0xa5U;
    command.transfer_id = UINT32_C(0x4b423752);
    memcpy(command.payload, "RESETKB7", 8U);
    if (process(&server, &command, &response) != KB7_HOST_STATUS_OK ||
        kb7_storage_select().valid) return 11;
    return 0;
}
