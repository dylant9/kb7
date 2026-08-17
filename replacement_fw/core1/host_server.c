#include "kb7/host_server.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"
#include "kb7/screen.h"
#include "kb7/storage.h"

#define KB7_FLASH_XIP_BASE UINT32_C(0x60000000)

static uint32_t slot_header_crc(struct kb7_slot_header *header) {
    const uint32_t old_state = header->state;
    const uint32_t old_crc = header->header_crc32;
    header->state = KB7_SLOT_VALID;
    header->header_crc32 = 0U;
    const uint32_t result = kb7_crc32(header, sizeof(*header));
    header->state = old_state;
    header->header_crc32 = old_crc;
    return result;
}

static void reset_transfer(struct kb7_host_server *server) {
    server->receiving = false;
    server->transfer_id = 0U;
    server->total_length = 0U;
    server->expected_crc32 = 0U;
    server->next_offset = 0U;
    server->target_slot = 0U;
    server->generation = 0U;
}

void kb7_host_server_init(struct kb7_host_server *server) {
    if (server != NULL) reset_transfer(server);
}

static void reply(const struct kb7_host_report *command, struct kb7_host_report *response,
                  enum kb7_host_status status, uint32_t next, uint32_t total) {
    kb7_memset(response, 0, sizeof(*response));
    response->kind = KB7_HOST_RESPONSE;
    response->opcode = command->opcode;
    response->status = (uint8_t)status;
    response->sequence = command->sequence;
    response->transfer_id = command->transfer_id;
    response->offset = next;
    response->total_length = total;
    kb7_host_report_finalize(response);
}

static enum kb7_host_status begin_transfer(struct kb7_host_server *server,
                                           const struct kb7_host_report *command) {
    if (command->total_length < KB7_SCREEN_HEADER_SIZE ||
        command->total_length > KB7_STORAGE_SCREEN_SLOT_BYTES - sizeof(struct kb7_slot_header)) {
        return KB7_HOST_STATUS_RANGE;
    }
    const struct kb7_slot_choice active = kb7_storage_select();
    server->target_slot = active.valid && active.offset == KB7_STORAGE_SCREEN_A
                              ? KB7_STORAGE_SCREEN_B : KB7_STORAGE_SCREEN_A;
    server->generation = active.valid ? active.header.generation + 1U : 1U;
    server->transfer_id = command->transfer_id;
    server->total_length = command->total_length;
    server->expected_crc32 = (uint32_t)command->payload[0] |
        ((uint32_t)command->payload[1] << 8U) | ((uint32_t)command->payload[2] << 16U) |
        ((uint32_t)command->payload[3] << 24U);
    server->next_offset = 0U;
    volatile struct kb7_runtime_api *api = kb7_runtime();
    const uint32_t erase_length = (uint32_t)sizeof(struct kb7_slot_header) +
                                  command->total_length;
    for (uint32_t offset = 0U; offset < erase_length; offset += UINT32_C(0x1000)) {
        if (api->flash_erase_4k(server->target_slot + offset) != 0) {
            reset_transfer(server);
            return KB7_HOST_STATUS_STORAGE;
        }
    }
    struct kb7_slot_header header;
    kb7_memset(&header, 0, sizeof(header));
    header.magic = KB7_STORAGE_SLOT_MAGIC;
    header.version = KB7_STORAGE_SLOT_VERSION;
    header.header_length = sizeof(header);
    header.state = KB7_SLOT_WRITING;
    header.generation = server->generation;
    header.payload_length = server->total_length;
    header.payload_crc32 = server->expected_crc32;
    header.header_crc32 = slot_header_crc(&header);
    if (api->flash_program(server->target_slot, &header, sizeof(header)) != 0) {
        reset_transfer(server);
        return KB7_HOST_STATUS_STORAGE;
    }
    server->receiving = true;
    return KB7_HOST_STATUS_OK;
}

void kb7_host_server_process(struct kb7_host_server *server,
                             const struct kb7_host_report *command,
                             struct kb7_host_report *response) {
    if (server == NULL || command == NULL || response == NULL) return;
    if (!kb7_host_report_valid(command) || command->kind != KB7_HOST_COMMAND) {
        reply(command, response, KB7_HOST_STATUS_BAD_CRC, server->next_offset,
              server->total_length);
        return;
    }
    enum kb7_host_status status = KB7_HOST_STATUS_OK;
    volatile struct kb7_runtime_api *api = kb7_runtime();
    switch (command->opcode) {
    case KB7_HOST_QUERY_VERSION:
    case KB7_HOST_QUERY_CAPABILITIES:
        break;
    case KB7_HOST_TRANSFER_BEGIN:
        if (server->receiving) status = KB7_HOST_STATUS_BAD_STATE;
        else status = begin_transfer(server, command);
        break;
    case KB7_HOST_TRANSFER_WRITE:
        if (!server->receiving || command->transfer_id != server->transfer_id ||
            command->offset != server->next_offset) {
            status = KB7_HOST_STATUS_BAD_STATE;
        } else {
            uint32_t count = server->total_length - server->next_offset;
            if (count > KB7_HOST_PAYLOAD_SIZE) count = KB7_HOST_PAYLOAD_SIZE;
            if (api->flash_program(server->target_slot + sizeof(struct kb7_slot_header) +
                                   server->next_offset, command->payload, count) != 0) {
                status = KB7_HOST_STATUS_STORAGE;
            } else {
                server->next_offset += count;
            }
        }
        break;
    case KB7_HOST_TRANSFER_COMMIT:
        if (!server->receiving || command->transfer_id != server->transfer_id ||
            server->next_offset != server->total_length) {
            status = KB7_HOST_STATUS_BAD_STATE;
        } else {
            const void *payload = (const void *)(uintptr_t)(KB7_FLASH_XIP_BASE +
                server->target_slot + sizeof(struct kb7_slot_header));
            if (kb7_crc32(payload, server->total_length) != server->expected_crc32) {
                status = KB7_HOST_STATUS_BAD_CRC;
            } else {
                const uint32_t valid = KB7_SLOT_VALID;
                if (api->flash_program(server->target_slot + 8U, &valid, sizeof(valid)) != 0) {
                    status = KB7_HOST_STATUS_STORAGE;
                } else {
                    reset_transfer(server);
                }
            }
        }
        break;
    case KB7_HOST_TRANSFER_ABORT:
        reset_transfer(server);
        break;
    case KB7_HOST_ENTER_LOADER:
        if (command->flags == 0xa5U && command->transfer_id == UINT32_C(0x4b42374c) &&
            kb7_memcmp(command->payload, "ENTERKB7", 8U) == 0) {
            api->enter_loader();
        }
        status = KB7_HOST_STATUS_BAD_STATE;
        break;
    default:
        status = KB7_HOST_STATUS_UNSUPPORTED;
        break;
    }
    reply(command, response, status, server->next_offset, server->total_length);
    if (status == KB7_HOST_STATUS_OK && command->opcode == KB7_HOST_QUERY_VERSION) {
        response->payload[0] = KB7_HOST_PROTOCOL_VERSION;
        response->payload[1] = KB7_SCREEN_VERSION;
        kb7_host_report_finalize(response);
    } else if (status == KB7_HOST_STATUS_OK &&
               command->opcode == KB7_HOST_QUERY_CAPABILITIES) {
        response->payload[0] = (uint8_t)KB7_DISPLAY_WIDTH;
        response->payload[1] = (uint8_t)(KB7_DISPLAY_WIDTH >> 8U);
        response->payload[2] = (uint8_t)KB7_DISPLAY_HEIGHT;
        response->payload[3] = (uint8_t)(KB7_DISPLAY_HEIGHT >> 8U);
        response->payload[4] = KB7_SCREEN_MAX_SCREENS;
        response->payload[5] = KB7_SCREEN_MAX_WIDGETS;
        kb7_host_report_finalize(response);
    }
}
