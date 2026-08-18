#include "kb7/host_server.h"
#include "kb7/profile_blob.h"
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
    server->erased_until = 0U;
    server->last_activity_ms = 0U;
    server->store = KB7_HOST_STORE_SCREEN;
    server->timeout_armed = false;
}

void kb7_host_server_init(struct kb7_host_server *server) {
    if (server == NULL) return;
    kb7_memset(server, 0, sizeof(*server));
    reset_transfer(server);
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

static bool store_valid(uint8_t store) {
    return store == KB7_HOST_STORE_SCREEN || store == KB7_HOST_STORE_PROFILE;
}

static bool runtime_milliseconds(uint32_t *now) {
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (now == NULL || api->magic != KB7_RUNTIME_MAGIC || api->milliseconds == NULL) {
        return false;
    }
    *now = api->milliseconds();
    return true;
}

static uint32_t store_slot_a(uint8_t store) {
    return store == KB7_HOST_STORE_PROFILE ? KB7_STORAGE_PROFILE_A : KB7_STORAGE_SCREEN_A;
}

static uint32_t store_slot_b(uint8_t store) {
    return store == KB7_HOST_STORE_PROFILE ? KB7_STORAGE_PROFILE_B : KB7_STORAGE_SCREEN_B;
}

static uint32_t store_capacity(uint8_t store) {
    return store == KB7_HOST_STORE_PROFILE ? KB7_STORAGE_PROFILE_SLOT_BYTES
                                           : KB7_STORAGE_SCREEN_SLOT_BYTES;
}

static struct kb7_slot_choice select_store_crc(uint8_t store) {
    return store == KB7_HOST_STORE_PROFILE ? kb7_storage_select_profiles()
                                           : kb7_storage_select();
}

static bool choice_semantically_valid(uint8_t store,
                                      const struct kb7_slot_choice *choice) {
    if (choice == NULL || !choice->valid) return false;
    const void *const payload = (const void *)(uintptr_t)(
        KB7_FLASH_XIP_BASE + choice->offset + sizeof(struct kb7_slot_header));
    if (store == KB7_HOST_STORE_PROFILE) {
        return kb7_profile_validate(payload, choice->header.payload_length) ==
               KB7_PROFILE_VALID;
    }
    struct kb7_screen_store parsed;
    return kb7_screen_parse(payload, choice->header.payload_length, &parsed) ==
           KB7_SCREEN_VALID;
}

static struct kb7_slot_choice select_store(uint8_t store) {
    struct kb7_slot_choice choice = select_store_crc(store);
    if (choice_semantically_valid(store, &choice)) return choice;
    const uint32_t alternate = choice.offset == store_slot_a(store)
                                   ? store_slot_b(store) : store_slot_a(store);
    struct kb7_slot_choice fallback = kb7_storage_read_slot(alternate);
    if (choice_semantically_valid(store, &fallback)) return fallback;
    choice.valid = false;
    return choice;
}

static enum kb7_host_status begin_transfer(struct kb7_host_server *server,
                                           const struct kb7_host_report *command) {
    if (!store_valid(command->flags) || command->status != 0U || command->transfer_id == 0U ||
        command->offset != 0U || !bytes_zero(&command->payload[4], KB7_HOST_PAYLOAD_SIZE - 4U)) {
        return KB7_HOST_STATUS_BAD_LENGTH;
    }
    const uint32_t minimum = command->flags == KB7_HOST_STORE_PROFILE
                                 ? KB7_PROFILE_MIN_SIZE : KB7_SCREEN_MIN_SIZE;
    const uint32_t maximum = command->flags == KB7_HOST_STORE_PROFILE
                                 ? KB7_PROFILE_MAX_SIZE
                                 : store_capacity(command->flags) -
                                       (uint32_t)sizeof(struct kb7_slot_header);
    if (command->total_length < minimum ||
        command->total_length > maximum) {
        return KB7_HOST_STATUS_RANGE;
    }
    if (!runtime_flash_available(true)) return KB7_HOST_STATUS_STORAGE;

    const struct kb7_slot_choice active = select_store(command->flags);
    const uint32_t slot_a = store_slot_a(command->flags);
    const uint32_t slot_b = store_slot_b(command->flags);
    server->target_slot = active.valid && active.offset == slot_a ? slot_b : slot_a;
    if (active.valid && server->target_slot == active.offset) {
        return KB7_HOST_STATUS_BAD_STATE;
    }
    server->generation = active.valid ? active.header.generation + 1U : 1U;
    server->transfer_id = command->transfer_id;
    server->total_length = command->total_length;
    server->expected_crc32 = read_u32(command->payload);
    server->next_offset = 0U;
    server->store = command->flags;

    volatile struct kb7_runtime_api *const api = kb7_runtime();
    /* Erase only the header sector now. Later sectors are erased lazily by
     * WRITE, bounding each command to at most one sector erase. */
    if (api->flash_erase_4k(server->target_slot) != 0) {
        reset_transfer(server);
        return KB7_HOST_STATUS_STORAGE;
    }
    server->erased_until = UINT32_C(0x1000);
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
    if (!server->receiving || command->flags != server->store || command->status != 0U ||
        command->transfer_id != server->transfer_id || command->offset != server->next_offset ||
        command->total_length != server->total_length ||
        server->next_offset >= server->total_length) {
        return KB7_HOST_STATUS_BAD_STATE;
    }
    uint32_t count = server->total_length - server->next_offset;
    if (count > KB7_HOST_PAYLOAD_SIZE) count = KB7_HOST_PAYLOAD_SIZE;
    if (!bytes_zero(&command->payload[count], KB7_HOST_PAYLOAD_SIZE - count)) {
        return KB7_HOST_STATUS_BAD_LENGTH;
    }
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    const uint32_t relative_end = (uint32_t)sizeof(struct kb7_slot_header) +
                                  server->next_offset + count;
    while (relative_end > server->erased_until) {
        if (api->flash_erase_4k(server->target_slot + server->erased_until) != 0) {
            return KB7_HOST_STATUS_STORAGE;
        }
        server->erased_until += UINT32_C(0x1000);
    }
    if (api->flash_program(server->target_slot + sizeof(struct kb7_slot_header) +
                           server->next_offset, command->payload, count) != 0) {
        return KB7_HOST_STATUS_STORAGE;
    }
    server->next_offset += count;
    return KB7_HOST_STATUS_OK;
}

static enum kb7_host_status commit_transfer(struct kb7_host_server *server,
                                            const struct kb7_host_report *command) {
    if (!server->receiving || command->flags != server->store || command->status != 0U ||
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
    if (server->store == KB7_HOST_STORE_PROFILE) {
        if (kb7_profile_validate(payload, server->total_length) != KB7_PROFILE_VALID) {
            return KB7_HOST_STATUS_BAD_LENGTH;
        }
    } else {
        struct kb7_screen_store parsed;
        if (kb7_screen_parse(payload, server->total_length, &parsed) != KB7_SCREEN_VALID) {
            return KB7_HOST_STATUS_BAD_LENGTH;
        }
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

static void invalidate_read_cache(struct kb7_host_server *server, uint8_t store) {
    if (server == NULL || !store_valid(store)) return;
    server->read_cache_loaded[store] = false;
    server->read_cache_present[store] = false;
    server->read_slot[store] = 0U;
    server->read_length[store] = 0U;
}

static enum kb7_host_status read_store(struct kb7_host_server *server,
                                       const struct kb7_host_report *command,
                                       uint8_t payload[KB7_HOST_PAYLOAD_SIZE],
                                       uint32_t *next, uint32_t *total) {
    if (!store_valid(command->flags) || command->status != 0U || command->transfer_id != 0U ||
        command->total_length != 0U || !bytes_zero(command->payload, KB7_HOST_PAYLOAD_SIZE)) {
        return KB7_HOST_STATUS_BAD_LENGTH;
    }
    const uint8_t store = command->flags;
    if (!server->read_cache_loaded[store]) {
        const struct kb7_slot_choice active = select_store(store);
        server->read_cache_loaded[store] = true;
        server->read_cache_present[store] = active.valid;
        if (active.valid) {
            server->read_slot[store] = active.offset;
            server->read_length[store] = active.header.payload_length;
        }
    }
    if (!server->read_cache_present[store]) return KB7_HOST_STATUS_BAD_STATE;
    if (command->offset > server->read_length[store]) return KB7_HOST_STATUS_RANGE;
    uint32_t count = server->read_length[store] - command->offset;
    if (count > KB7_HOST_PAYLOAD_SIZE) count = KB7_HOST_PAYLOAD_SIZE;
    if (kb7_runtime()->flash_read(server->read_slot[store] + sizeof(struct kb7_slot_header) + command->offset,
                                  payload, count) != 0) {
        return KB7_HOST_STATUS_STORAGE;
    }
    *next = command->offset + count;
    *total = server->read_length[store];
    return KB7_HOST_STATUS_OK;
}

static bool factory_reset_valid(const struct kb7_host_report *command) {
    return command->flags == 0xa5U && command->status == 0U &&
           command->transfer_id == KB7_RESET_TOKEN && command->offset == 0U &&
           command->total_length == 0U &&
           kb7_memcmp(command->payload, "RESETKB7", 8U) == 0 &&
           bytes_zero(&command->payload[8], KB7_HOST_PAYLOAD_SIZE - 8U);
}

static enum kb7_host_status factory_reset(const struct kb7_host_report *command) {
    if (!factory_reset_valid(command)) return KB7_HOST_STATUS_BAD_STATE;
    if (!runtime_flash_available(true)) return KB7_HOST_STATUS_STORAGE;
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    if (api->flash_erase_4k(KB7_STORAGE_SCREEN_A) != 0 ||
        api->flash_erase_4k(KB7_STORAGE_SCREEN_B) != 0 ||
        api->flash_erase_4k(KB7_STORAGE_PROFILE_A) != 0 ||
        api->flash_erase_4k(KB7_STORAGE_PROFILE_B) != 0) {
        return KB7_HOST_STATUS_STORAGE;
    }
    return KB7_HOST_STATUS_OK;
}

bool kb7_host_server_take_storage_invalidation(struct kb7_host_server *server) {
    if (server == NULL || !server->storage_invalidated) return false;
    server->storage_invalidated = false;
    return true;
}

void kb7_host_server_process(struct kb7_host_server *server,
                             const struct kb7_host_report *command,
                             struct kb7_host_report *response) {
    if (server == NULL || command == NULL || response == NULL) return;
    uint32_t now = 0U;
    const bool have_time = runtime_milliseconds(&now);
    if (server->receiving && server->timeout_armed && have_time &&
        (uint32_t)(now - server->last_activity_ms) >= KB7_HOST_TRANSFER_TIMEOUT_MS) {
        reset_transfer(server);
    }
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
            response_payload[10] = KB7_SCREEN_VERSION;
            response_payload[11] = KB7_PROFILE_VERSION;
            response_payload[12] = KB7_INPUT_PROFILE_SLOT_COUNT;
            response_payload[13] = KB7_HOST_PROTOCOL_VERSION;
            response_payload[14] = (uint8_t)KB7_PROFILE_RECORD_SIZE;
            response_payload[15] = (uint8_t)(KB7_PROFILE_RECORD_SIZE >> 8U);
            response_payload[16] = (uint8_t)KB7_STORAGE_PROFILE_SLOT_BYTES;
            response_payload[17] = (uint8_t)(KB7_STORAGE_PROFILE_SLOT_BYTES >> 8U);
            response_payload[18] = (uint8_t)(KB7_STORAGE_PROFILE_SLOT_BYTES >> 16U);
            response_payload[19] = (uint8_t)(KB7_STORAGE_PROFILE_SLOT_BYTES >> 24U);
            response_payload[20] = (uint8_t)KB7_PROFILE_MAX_SIZE;
            response_payload[21] = (uint8_t)(KB7_PROFILE_MAX_SIZE >> 8U);
            response_payload[22] = (uint8_t)(KB7_PROFILE_MAX_SIZE >> 16U);
            response_payload[23] = (uint8_t)(KB7_PROFILE_MAX_SIZE >> 24U);
            const uint32_t features = KB7_HOST_CAP_SCREEN_STORE |
                                      KB7_HOST_CAP_PROFILE_STORE |
                                      KB7_HOST_CAP_RUNTIME_SCREEN_SELECT |
                                      KB7_HOST_CAP_GAMEPAD |
                                      KB7_HOST_CAP_HALL_TELEMETRY;
            response_payload[24] = (uint8_t)features;
            response_payload[25] = (uint8_t)(features >> 8U);
            response_payload[26] = (uint8_t)(features >> 16U);
            response_payload[27] = (uint8_t)(features >> 24U);
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
        /* Finalization may have mutated the slot even when readback reports a
         * storage error, so never retain a pre-COMMIT slot cache. */
        if (store_valid(command->flags)) invalidate_read_cache(server, command->flags);
        break;
    case KB7_HOST_TRANSFER_ABORT:
        if (!store_valid(command->flags) || command->status != 0U || command->offset != 0U ||
            command->total_length != 0U ||
            !bytes_zero(command->payload, KB7_HOST_PAYLOAD_SIZE)) {
            status = KB7_HOST_STATUS_BAD_LENGTH;
        } else if (server->receiving &&
                   (command->transfer_id != server->transfer_id ||
                    command->flags != server->store)) {
            status = KB7_HOST_STATUS_BAD_STATE;
        } else {
            reset_transfer(server);
        }
        break;
    case KB7_HOST_STORE_READ:
        status = read_store(server, command, response_payload, &response_next, &response_total);
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
        /* The erase sequence can fail after invalidating one cached slot. */
        invalidate_read_cache(server, KB7_HOST_STORE_SCREEN);
        invalidate_read_cache(server, KB7_HOST_STORE_PROFILE);
        if (server->receiving) {
            status = KB7_HOST_STATUS_BAD_STATE;
        } else {
            if (factory_reset_valid(command) && runtime_flash_available(true)) {
                /* Publish before the first erase: even a reported STORAGE
                 * failure may already have invalidated the live XIP object. */
                server->storage_invalidated = true;
            }
            status = factory_reset(command);
        }
        break;
    case KB7_HOST_ENTER_LOADER:
        /* No software path is proven to reach ROM/loader. Exposing the
         * fail-closed recovery park to an ordinary host report would only be
         * a denial-of-service primitive, so this opcode remains reserved. */
        status = KB7_HOST_STATUS_UNSUPPORTED;
        break;
    default:
        status = KB7_HOST_STATUS_UNSUPPORTED;
        break;
    }

    if (status == KB7_HOST_STATUS_OK && server->receiving &&
        (command->opcode == KB7_HOST_TRANSFER_BEGIN ||
         command->opcode == KB7_HOST_TRANSFER_WRITE)) {
        uint32_t completed_at;
        if (runtime_milliseconds(&completed_at)) {
            server->last_activity_ms = completed_at;
            server->timeout_armed = true;
        }
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
