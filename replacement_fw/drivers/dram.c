#include "kb7/drivers.h"
#include "kb7/regs.h"

/*
 * The timing constants are copied from the register clusters reached by the
 * V1.22 init, but the PHY training algorithm is not yet validated.  The build
 * therefore leaves the block disabled unless explicitly enabled for a staged
 * hardware experiment.
 */
#ifndef KB7_ENABLE_UNVERIFIED_DRAM_INIT
#define KB7_ENABLE_UNVERIFIED_DRAM_INIT 0
#endif

static uint32_t pattern(size_t index, uint32_t phase) {
    static const uint32_t fixed[] = {
        UINT32_C(0x00000000), UINT32_C(0xffffffff),
        UINT32_C(0xaaaaaaaa), UINT32_C(0x55555555),
    };
    return phase < KB7_ARRAY_LEN(fixed)
               ? fixed[phase]
               : ((uint32_t)index * UINT32_C(0x9e3779b1)) ^ UINT32_C(0xa5c35a7d);
}

bool kb7_dram_march_test(uintptr_t address, size_t bytes) {
    if ((address & 3U) != 0U || bytes < 4U) {
        return false;
    }
    volatile uint32_t *memory = (volatile uint32_t *)address;
    const size_t words = bytes / 4U;
    for (uint32_t phase = 0U; phase < 5U; ++phase) {
        for (size_t index = 0; index < words; ++index) {
            memory[index] = pattern(index, phase);
        }
        kb7_dsb();
        for (size_t index = 0; index < words; ++index) {
            if (memory[index] != pattern(index, phase)) {
                return false;
            }
        }
    }
    return true;
}

bool kb7_dram_init_and_train(void) {
#if KB7_ENABLE_UNVERIFIED_DRAM_INIT
    KB7_MMIO32(SNC_CLOCK_BASE + 0x114U) = 1U;
    KB7_MMIO32(SNC_DRAM_BASE + 0x00U) = 0U;
    KB7_MMIO32(SNC_DRAM_BASE + 0x14U) = UINT32_C(0x00030303);
    KB7_MMIO32(SNC_DRAM_BASE + 0x18U) = UINT32_C(0x00060603);
    KB7_MMIO32(SNC_DRAM_BASE + 0x1cU) = UINT32_C(0x00030306);
    KB7_MMIO32(SNC_DRAM_BASE + 0x5cU) |= 1U;
    uint32_t timeout = UINT32_C(4000000);
    while ((KB7_MMIO32(SNC_DRAM_BASE + 0x60U) & 1U) == 0U && timeout-- != 0U) {
    }
    if (timeout == 0U) {
        return false;
    }
    return kb7_dram_march_test(KB7_FRAMEBUFFER_A, UINT32_C(0x10000));
#else
    return false;
#endif
}
