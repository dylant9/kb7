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
};

void kb7_host_server_init(struct kb7_host_server *server);
void kb7_host_server_process(struct kb7_host_server *server,
                             const struct kb7_host_report *command,
                             struct kb7_host_report *response);

#endif
