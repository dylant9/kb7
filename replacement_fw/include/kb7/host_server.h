#ifndef KB7_HOST_SERVER_H
#define KB7_HOST_SERVER_H

#include "kb7/host_protocol.h"

struct kb7_host_server {
    bool receiving;
    uint32_t transfer_id;
    uint32_t total_length;
    uint32_t expected_crc32;
    uint32_t next_offset;
    uint32_t target_slot;
    uint32_t generation;
    uint32_t erased_until;
    uint32_t last_activity_ms;
    uint8_t store;
    bool timeout_armed;
    uint32_t read_slot[2];
    uint32_t read_length[2];
    bool read_cache_loaded[2];
    bool read_cache_present[2];
    bool storage_invalidated;
};

#define KB7_HOST_TRANSFER_TIMEOUT_MS UINT32_C(5000)

void kb7_host_server_init(struct kb7_host_server *server);
void kb7_host_server_process(struct kb7_host_server *server,
                             const struct kb7_host_report *command,
                             struct kb7_host_report *response);
/* True once after a factory-reset attempt may have erased a live store. */
bool kb7_host_server_take_storage_invalidation(struct kb7_host_server *server);

#endif
