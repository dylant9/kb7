#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "kb7/build_pair.h"

static struct kb7_build_pair_marker valid_marker(uint32_t role) {
    struct kb7_build_pair_marker marker = {
        .magic = KB7_BUILD_PAIR_MAGIC,
        .format_version = KB7_BUILD_PAIR_FORMAT_VERSION,
        .size = sizeof(struct kb7_build_pair_marker),
        .role = role,
        .runtime_abi_version = 2U,
        .pair_id = {0U},
    };
    for (size_t index = 0U; index < KB7_BUILD_PAIR_ID_BYTES; ++index) {
        marker.pair_id[index] = (uint8_t)(index + 1U);
    }
    return marker;
}

int main(void) {
    uint8_t zero_id[KB7_BUILD_PAIR_ID_BYTES] = {0U};
    uint8_t erased_id[KB7_BUILD_PAIR_ID_BYTES];
    uint8_t valid_id[KB7_BUILD_PAIR_ID_BYTES];
    memset(erased_id, 0xff, sizeof(erased_id));
    for (size_t index = 0U; index < sizeof(valid_id); ++index) {
        valid_id[index] = (uint8_t)(index + 1U);
    }

    assert(!kb7_build_pair_id_valid(zero_id));
    assert(!kb7_build_pair_id_valid(erased_id));
    assert(kb7_build_pair_id_valid(valid_id));
    assert(kb7_build_pair_ids_equal(valid_id, valid_id));
    valid_id[KB7_BUILD_PAIR_ID_BYTES - 1U] ^= UINT8_C(0x80);
    assert(!kb7_build_pair_ids_equal(zero_id, valid_id));

    struct kb7_build_pair_marker marker =
        valid_marker(KB7_BUILD_PAIR_ROLE_CORE0);
    assert(kb7_build_pair_marker_valid(
        &marker, KB7_BUILD_PAIR_ROLE_CORE0, 2U));

    marker.magic ^= UINT32_C(1);
    assert(!kb7_build_pair_marker_valid(
        &marker, KB7_BUILD_PAIR_ROLE_CORE0, 2U));
    marker = valid_marker(KB7_BUILD_PAIR_ROLE_CORE0);
    ++marker.format_version;
    assert(!kb7_build_pair_marker_valid(
        &marker, KB7_BUILD_PAIR_ROLE_CORE0, 2U));
    marker = valid_marker(KB7_BUILD_PAIR_ROLE_CORE0);
    --marker.size;
    assert(!kb7_build_pair_marker_valid(
        &marker, KB7_BUILD_PAIR_ROLE_CORE0, 2U));
    marker = valid_marker(KB7_BUILD_PAIR_ROLE_CORE0);
    marker.role = KB7_BUILD_PAIR_ROLE_CORE1;
    assert(!kb7_build_pair_marker_valid(
        &marker, KB7_BUILD_PAIR_ROLE_CORE0, 2U));
    marker = valid_marker(KB7_BUILD_PAIR_ROLE_CORE0);
    ++marker.runtime_abi_version;
    assert(!kb7_build_pair_marker_valid(
        &marker, KB7_BUILD_PAIR_ROLE_CORE0, 2U));
    marker = valid_marker(KB7_BUILD_PAIR_ROLE_CORE0);
    memset(marker.pair_id, 0xff, sizeof(marker.pair_id));
    assert(!kb7_build_pair_marker_valid(
        &marker, KB7_BUILD_PAIR_ROLE_CORE0, 2U));

    struct kb7_build_pair_marker peer =
        valid_marker(KB7_BUILD_PAIR_ROLE_CORE1);
    marker = valid_marker(KB7_BUILD_PAIR_ROLE_CORE0);
    assert(kb7_build_pair_ids_equal(marker.pair_id, peer.pair_id));
    peer.pair_id[7] ^= UINT8_C(1);
    assert(!kb7_build_pair_ids_equal(marker.pair_id, peer.pair_id));
    return 0;
}
