#ifndef KB7_BUILD_PAIR_H
#define KB7_BUILD_PAIR_H

#include "kb7/platform.h"

#define KB7_BUILD_PAIR_MAGIC UINT32_C(0x5037424b)
#define KB7_BUILD_PAIR_FORMAT_VERSION 1U
#define KB7_BUILD_PAIR_ID_BYTES 16U
#define KB7_BUILD_PAIR_MARKER_BYTES 32U
#define KB7_BUILD_PAIR_ROLE_CORE0 UINT32_C(0)
#define KB7_BUILD_PAIR_ROLE_CORE1 UINT32_C(1)
#define KB7_CORE0_BUILD_PAIR_ADDRESS UINT32_C(0x00000140)
#define KB7_CORE1_BUILD_PAIR_ADDRESS UINT32_C(0x10000100)

struct KB7_PACKED kb7_build_pair_marker {
    uint32_t magic;
    uint16_t format_version;
    uint16_t size;
    uint32_t role;
    uint32_t runtime_abi_version;
    uint8_t pair_id[KB7_BUILD_PAIR_ID_BYTES];
};

_Static_assert(sizeof(struct kb7_build_pair_marker) == KB7_BUILD_PAIR_MARKER_BYTES,
               "build-pair marker size changed");

static inline volatile const struct kb7_build_pair_marker *
kb7_build_pair_at(uint32_t address) {
    uintptr_t resolved = (uintptr_t)address;
    /* Core 0 intentionally lives at low PRAM addresses; keep GCC's host-style
     * null/object-bounds inference from replacing these volatile target reads. */
    __asm__ volatile("" : "+r"(resolved));
    return (volatile const struct kb7_build_pair_marker *)resolved;
}

static inline bool kb7_build_pair_id_valid(const volatile uint8_t *identifier) {
    uint8_t any_nonzero = 0U;
    uint8_t any_not_ff = 0U;
    for (size_t index = 0U; index < KB7_BUILD_PAIR_ID_BYTES; ++index) {
        any_nonzero |= identifier[index];
        any_not_ff |= (uint8_t)~identifier[index];
    }
    return any_nonzero != 0U && any_not_ff != 0U;
}

static inline bool kb7_build_pair_marker_valid(
    volatile const struct kb7_build_pair_marker *marker, uint32_t role,
    uint16_t runtime_abi_version) {
    return marker->magic == KB7_BUILD_PAIR_MAGIC &&
           marker->format_version == KB7_BUILD_PAIR_FORMAT_VERSION &&
           marker->size == sizeof(*marker) && marker->role == role &&
           marker->runtime_abi_version == runtime_abi_version &&
           kb7_build_pair_id_valid(marker->pair_id);
}

static inline bool kb7_build_pair_ids_equal(
    volatile const uint8_t *left, volatile const uint8_t *right) {
    uint8_t difference = 0U;
    for (size_t index = 0U; index < KB7_BUILD_PAIR_ID_BYTES; ++index) {
        difference |= left[index] ^ right[index];
    }
    return difference == 0U;
}

#endif
