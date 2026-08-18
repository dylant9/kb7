#define _GNU_SOURCE
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "kb7/platform_boot.h"
#include "kb7/regs.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

static bool map_at(uintptr_t address, size_t length) {
    void *result = mmap((void *)address, length, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    return result != MAP_FAILED;
}

static uint32_t simulated_busy_reads;
static bool simulated_stuck_busy;

uint8_t kb7_cache_test_control_read(volatile const uint8_t *address) {
    if (simulated_stuck_busy) return UINT8_C(2);
    if (simulated_busy_reads != 0U) {
        --simulated_busy_reads;
        return UINT8_C(2);
    }
    return *address;
}

int main(void) {
    if (!map_at(KB7_REGION1_FLASH_SOURCE, KB7_REGION1_COPY_BYTES) ||
        !map_at(KB7_REGION1_OPI_SOURCE, KB7_REGION1_COPY_BYTES) ||
        !map_at(KB7_REGION1_ENTRY & ~(uintptr_t)1U, KB7_REGION1_COPY_BYTES) ||
        !map_at(SNC_ICACHE_BASE, 4096U) || !map_at(SNC_SYS0_BASE, 4096U)) {
        return 77;
    }
    uint8_t *source = (uint8_t *)(uintptr_t)KB7_REGION1_FLASH_SOURCE;
    uint8_t *window = (uint8_t *)(uintptr_t)(KB7_REGION1_ENTRY & ~(uintptr_t)1U);
    for (uint32_t index = 0U; index < KB7_REGION1_COPY_BYTES; ++index) {
        source[index] = (uint8_t)(index ^ (index >> 8U));
    }
    memcpy(window, source, KB7_REGION1_COPY_BYTES);
    simulated_busy_reads = 3U;
    if (!kb7_cache_prepare_region1()) return 1;
    if (simulated_busy_reads != 0U) return 6;
    if (memcmp((const void *)(uintptr_t)KB7_REGION1_OPI_SOURCE, source,
               KB7_REGION1_COPY_BYTES) != 0) return 2;
    if (KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_OFFSET) !=
            KB7_REGION1_OPI_SOURCE ||
        KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL) != 2U ||
        (KB7_MMIO32(SNC_SYS1_BASE + SNC_SYS1_CLOCK_RESET) & KB7_BIT(11)) == 0U) {
        return 3;
    }
    window[KB7_REGION1_COPY_BYTES - 1U] ^= UINT8_C(1);
    if (kb7_cache_prepare_region1()) return 4;
    if (KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL) != 0U) return 5;
    memcpy(window, source, KB7_REGION1_COPY_BYTES);
    simulated_stuck_busy = true;
    if (kb7_cache_prepare_region1()) return 7;
    if (KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL) != 0U) return 8;
    return 0;
}
