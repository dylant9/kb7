#include "kb7/host_server.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"
#include "kb7/screen.h"
#include "kb7/storage.h"
#include "kb7/ui.h"

#define KB7_FLASH_XIP_BASE UINT32_C(0x60000000)
#define KB7_RESET_TOKEN UINT32_C(0x4b423752)

static bool bytes_zero(const uint8_t *bytes, size_t length) {
    while (length-- != 0U) {
        if (*bytes++ != 0U) return false;
    }
    return true;
}

static uint32_t read_u32(const uint8_t bytes[4]) {
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8U) |
           ((uint32_t)bytes[2] << 16U) | ((uint32_t)bytes[3] << 24U);
}

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
}

static bool runtime_flash_available(bool write) {
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    return api->magic == KB7_RUNTIME_MAGIC && api->flash_read != NULL &&
           (!write || (api->flash_erase_4k != NULL && api->flash_program != NULL));
}

static enum kb7_host_status begin_transfer(struct kb7_host_server *server,
                                           const struct kb7_host_report *command) {
    if (command->flags != 0U || command->status != 0U || command->transfer_id == 0U ||
        command->offset != 0U || !bytes_zero(&command->payload[4], KB7_HOST_PAYLOAD_SIZE - 4U)) {
        return KB7_HOST_STATUS_BAD_LENGTH;
    }
    if (command->total_length < KB7_SCREEN_HEADER_SIZE ||
        command->total_length > KB7_STORAGE_SCREEN_SLOT_BYTES - sizeof(struct kb7_slot_header)) {
        return KB7_HOST_STATUS_RANGE;
    }
    if (!runtime_flash_available(true)) return KB7_HOST_STATUS_STORAGE;

    const struct kb7_slot_choice active = kb7_storage_select();
    server->target_slot = active.valid && active.offset == KB7_STORAGE_SCREEN_A
                              ? KB7_STORAGE_SCREEN_B : KB7_STORAGE_SCREEN_A;
    if (active.valid && server->target_slot == active.offset) {
        return KB7_HOST_STATUS_BAD_STATE;
    }
    server->generation = active.valid ? active.header.generation + 1U : 1U;
    server->transfer_id = command->transfer_id;
    server->total_length = command->total_length;
    server->expected_crc32 = read_u32(command->payload);
    server->next_offset = 0U;

    volatile struct kb7_runtime_api *const api = kb7_runtime();
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

static enum kb7_host_status write_transfer(struct kb7_host_server *server,
                                           const struct kb7_host_report *command) {
    if (!server->receiving || command->flags != 0U || command->status != 0U ||
        command->transfer_id != server->transfer_id || command->offset != server->next_offset ||
        command->total_length != server->total_length) {
        return KB7_HOST_STATUS_BAD_STATE;
    }
    uint32_t count = server->total_length - server->next_offset;
    if (count > KB7_HOST_PAYLOAD_SIZE) count = KB7_HOST_PAYLOAD_SIZE;
    if (!bytes_zero(&command->payload[count], KB7_HOST_PAYLOAD_SIZE - count)) {
        return KB7_HOST_STATUS_BAD_LENGTH;
    }
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (api->flash_program(server->target_slot + sizeof(struct kb7_slot_header) +
                           server->next_offset, command->payload, count) != 0) {
        return KB7_HOST_STATUS_STORAGE;
    }
    server->next_offset += count;
    return KB7_HOST_STATUS_OK;
}

static enum kb7_host_status commit_transfer(struct kb7_host_server *server,
                                            const struct kb7_host_report *command) {
    if (!server->receiving || command->flags != 0U || command->status != 0U ||
        command->transfer_id != server->transfer_id || command->offset != server->total_length ||
        command->total_length != server->total_length ||
        server->next_offset != server->total_length) {
        return KB7_HOST_STATUS_BAD_STATE;
    }
    if (read_u32(command->payload) != server->expected_crc32 ||
        !bytes_zero(&command->payload[4], KB7_HOST_PAYLOAD_SIZE - 4U)) {
        return KB7_HOST_STATUS_BAD_CRC;
    }
    const void *payload = (const void *)(uintptr_t)(KB7_FLASH_XIP_BASE +
        server->target_slot + sizeof(struct kb7_slot_header));
    if (kb7_crc32(payload, server->total_length) != server->expected_crc32) {
        return KB7_HOST_STATUS_BAD_CRC;
    }
    struct kb7_screen_store parsed;
    if (kb7_screen_parse(payload, server->total_length, &parsed) != KB7_SCREEN_VALID) {
        return KB7_HOST_STATUS_BAD_LENGTH;
    }
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    const uint32_t valid = KB7_SLOT_VALID;
    if (api->flash_program(server->target_slot + 8U, &valid, sizeof(valid)) != 0) {
        return KB7_HOST_STATUS_STORAGE;
    }
    if (!kb7_storage_read_slot(server->target_slot).valid) {
        return KB7_HOST_STATUS_STORAGE;
    }
    reset_transfer(server);
    return KB7_HOST_STATUS_OK;
}

static enum kb7_host_status read_store(const struct kb7_host_report *command,
                                       uint8_t payload[KB7_HOST_PAYLOAD_SIZE],
                                       uint32_t *next, uint32_t *total) {
    if (command->flags != 0U || command->status != 0U || command->transfer_id != 0U ||
        command->total_length != 0U || !bytes_zero(command->payload, KB7_HOST_PAYLOAD_SIZE)) {
        return KB7_HOST_STATUS_BAD_LENGTH;
    }
    const struct kb7_slot_choice active = kb7_storage_select();
    if (!active.valid) return KB7_HOST_STATUS_BAD_STATE;
    if (command->offset > active.header.payload_length) return KB7_HOST_STATUS_RANGE;
    uint32_t count = active.header.payload_length - command->offset;
    if (count > KB7_HOST_PAYLOAD_SIZE) count = KB7_HOST_PAYLOAD_SIZE;
    if (kb7_runtime()->flash_read(active.offset + sizeof(struct kb7_slot_header) + command->offset,
                                  payload, count) != 0) {
        return KB7_HOST_STATUS_STORAGE;
    }
    *next = command->offset + count;
    *total = active.header.payload_length;
    return KB7_HOST_STATUS_OK;
}

static enum kb7_host_status factory_reset(const struct kb7_host_report *command) {
    if (command->flags != 0xa5U || command->status != 0U ||
        command->transfer_id != KB7_RESET_TOKEN || command->offset != 0U ||
        command->total_length != 0U || kb7_memcmp(command->payload, "RESETKB7", 8U) != 0 ||
        !bytes_zero(&command->payload[8], KB7_HOST_PAYLOAD_SIZE - 8U)) {
        return KB7_HOST_STATUS_BAD_STATE;
    }
    if (!runtime_flash_available(true)) return KB7_HOST_STATUS_STORAGE;
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (api->flash_erase_4k(KB7_STORAGE_SCREEN_A) != 0 ||
        api->flash_erase_4k(KB7_STORAGE_SCREEN_B) != 0) {
        return KB7_HOST_STATUS_STORAGE;
    }
    return KB7_HOST_STATUS_OK;
}

void kb7_host_server_process(struct kb7_host_server *server,
                             const struct kb7_host_report *command,
                             struct kb7_host_report *response) {
    if (server == NULL || command == NULL || response == NULL) return;
    const enum kb7_host_validation validation = kb7_host_report_validate(command);
    if (validation != KB7_HOST_FRAME_VALID) {
        const enum kb7_host_status status =
            validation == KB7_HOST_FRAME_BAD_VERSION || validation == KB7_HOST_FRAME_BAD_ID
                ? KB7_HOST_STATUS_BAD_VERSION : KB7_HOST_STATUS_BAD_CRC;
        reply(command, response, status, server->next_offset, server->total_length);
        kb7_host_report_finalize(response);
        return;
    }
    if (command->kind != KB7_HOST_COMMAND || command->status != 0U) {
        reply(command, response, KB7_HOST_STATUS_BAD_STATE, server->next_offset,
              server->total_length);
        kb7_host_report_finalize(response);
        return;
    }

    enum kb7_host_status status = KB7_HOST_STATUS_OK;
    uint8_t response_payload[KB7_HOST_PAYLOAD_SIZE];
    kb7_memset(response_payload, 0, sizeof(response_payload));
    uint32_t response_next = server->next_offset;
    uint32_t response_total = server->total_length;
    switch (command->opcode) {
    case KB7_HOST_QUERY_VERSION:
        if (command->flags != 0U || command->transfer_id != 0U || command->offset != 0U ||
            command->total_length != 0U ||
            !bytes_zero(command->payload, KB7_HOST_PAYLOAD_SIZE)) {
            status = KB7_HOST_STATUS_BAD_LENGTH;
        } else {
            response_payload[0] = KB7_HOST_PROTOCOL_VERSION;
            response_payload[1] = KB7_SCREEN_VERSION;
        }
        break;
    case KB7_HOST_QUERY_CAPABILITIES:
        if (command->flags != 0U || command->transfer_id != 0U || command->offset != 0U ||
            command->total_length != 0U ||
            !bytes_zero(command->payload, KB7_HOST_PAYLOAD_SIZE)) {
            status = KB7_HOST_STATUS_BAD_LENGTH;
        } else {
            response_payload[0] = (uint8_t)KB7_DISPLAY_WIDTH;
            response_payload[1] = (uint8_t)(KB7_DISPLAY_WIDTH >> 8U);
            response_payload[2] = (uint8_t)KB7_DISPLAY_HEIGHT;
            response_payload[3] = (uint8_t)(KB7_DISPLAY_HEIGHT >> 8U);
            response_payload[4] = KB7_SCREEN_MAX_SCREENS;
            response_payload[5] = KB7_SCREEN_MAX_WIDGETS;
            response_payload[6] = (uint8_t)KB7_STORAGE_SCREEN_SLOT_BYTES;
            response_payload[7] = (uint8_t)(KB7_STORAGE_SCREEN_SLOT_BYTES >> 8U);
            response_payload[8] = (uint8_t)(KB7_STORAGE_SCREEN_SLOT_BYTES >> 16U);
            response_payload[9] = (uint8_t)(KB7_STORAGE_SCREEN_SLOT_BYTES >> 24U);
        }
        break;
    case KB7_HOST_TRANSFER_BEGIN:
        status = server->receiving ? KB7_HOST_STATUS_BAD_STATE
                                   : begin_transfer(server, command);
        break;
    case KB7_HOST_TRANSFER_WRITE:
        status = write_transfer(server, command);
        break;
    case KB7_HOST_TRANSFER_COMMIT:
        status = commit_transfer(server, command);
        break;
    case KB7_HOST_TRANSFER_ABORT:
        if (command->flags != 0U || command->status != 0U || command->offset != 0U ||
            command->total_length != 0U ||
            !bytes_zero(command->payload, KB7_HOST_PAYLOAD_SIZE)) {
            status = KB7_HOST_STATUS_BAD_LENGTH;
        } else if (server->receiving && command->transfer_id != server->transfer_id) {
            status = KB7_HOST_STATUS_BAD_STATE;
        } else {
            reset_transfer(server);
        }
        break;
    case KB7_HOST_STORE_READ:
        status = read_store(command, response_payload, &response_next, &response_total);
        break;
    case KB7_HOST_STORE_SELECT:
        if (command->flags != 0U || command->transfer_id != 0U ||
            command->offset > UINT16_MAX || command->total_length != 0U ||
            !bytes_zero(command->payload, KB7_HOST_PAYLOAD_SIZE)) {
            status = KB7_HOST_STATUS_BAD_LENGTH;
        } else if (!kb7_ui_navigate((uint16_t)command->offset)) {
            status = KB7_HOST_STATUS_RANGE;
        }
        break;
    case KB7_HOST_STORE_FACTORY_RESET:
        status = server->receiving ? KB7_HOST_STATUS_BAD_STATE : factory_reset(command);
        break;
    case KB7_HOST_ENTER_LOADER:
        if (command->flags == 0xa5U && command->status == 0U &&
            command->transfer_id == UINT32_C(0x4b42374c) && command->offset == 0U &&
            command->total_length == 0U &&
            kb7_memcmp(command->payload, "ENTERKB7", 8U) == 0 &&
            bytes_zero(&command->payload[8], KB7_HOST_PAYLOAD_SIZE - 8U)) {
            kb7_runtime()->enter_loader();
        }
        status = KB7_HOST_STATUS_BAD_STATE;
        break;
    default:
        status = KB7_HOST_STATUS_UNSUPPORTED;
        break;
    }

    if (command->opcode != KB7_HOST_STORE_READ) {
        response_next = server->next_offset;
        response_total = server->total_length;
    }
    reply(command, response, status, response_next, response_total);
    if (status == KB7_HOST_STATUS_OK) {
        kb7_memcpy(response->payload, response_payload, sizeof(response->payload));
    }
    kb7_host_report_finalize(response);
}
