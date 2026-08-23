#include "kb7/platform.h"
#include "kb7/build_pair.h"
#include "kb7/runtime.h"

extern uint32_t __data_load_start__, __data_start__, __data_end__;
extern uint32_t __bss_start__, __bss_end__;
void kb7_application_main(void) KB7_NORETURN;

__attribute__((section(".kb7_pair"), used))
const struct kb7_build_pair_marker kb7_core1_build_pair = {
    .magic = KB7_BUILD_PAIR_MAGIC,
    .format_version = KB7_BUILD_PAIR_FORMAT_VERSION,
    .size = sizeof(struct kb7_build_pair_marker),
    .role = KB7_BUILD_PAIR_ROLE_CORE1,
    .runtime_abi_version = KB7_RUNTIME_ABI_VERSION,
    .pair_id = {[0 ... KB7_BUILD_PAIR_ID_BYTES - 1U] = UINT8_C(0xff)},
};

static void pair_mismatch_park(void) KB7_NORETURN;
static void pair_mismatch_park(void) {
    kb7_disable_irq();
    for (;;) kb7_wfi();
}

__attribute__((section(".entry"), used, noreturn))
void core1_entry(void) {
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    volatile const struct kb7_build_pair_marker *const core0_pair =
        kb7_build_pair_at(KB7_CORE0_BUILD_PAIR_ADDRESS);
    volatile const struct kb7_build_pair_marker *const core1_pair =
        kb7_build_pair_at(KB7_CORE1_BUILD_PAIR_ADDRESS);
    if (api->magic != KB7_RUNTIME_MAGIC ||
        api->abi_version != KB7_RUNTIME_ABI_VERSION || api->size != sizeof(*api) ||
        !kb7_build_pair_marker_valid(core0_pair, KB7_BUILD_PAIR_ROLE_CORE0,
                                     KB7_RUNTIME_ABI_VERSION) ||
        !kb7_build_pair_marker_valid(core1_pair, KB7_BUILD_PAIR_ROLE_CORE1,
                                     KB7_RUNTIME_ABI_VERSION) ||
        !kb7_build_pair_ids_equal(core0_pair->pair_id, core1_pair->pair_id) ||
        !kb7_build_pair_ids_equal(core1_pair->pair_id, api->build_pair_id)) {
        pair_mismatch_park();
    }
    uint32_t *source = &__data_load_start__;
    for (uint32_t *destination = &__data_start__; destination < &__data_end__;) {
        *destination++ = *source++;
    }
    for (uint32_t *destination = &__bss_start__; destination < &__bss_end__;) {
        *destination++ = 0U;
    }
    kb7_application_main();
}
