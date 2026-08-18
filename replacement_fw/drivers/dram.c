#include "kb7/drivers.h"
#include "kb7/config.h"
#include "kb7/platform_boot.h"
#include "kb7/regs.h"

#define KB7_OPI_BASE UINT32_C(0x30000000)
#define KB7_OPI_END UINT32_C(0x30800000)
#define KB7_DRAM_WAIT_LIMIT UINT32_C(100000)
#define KB7_CACHE_WAIT_LIMIT UINT32_C(1000000)

#if KB7_ENABLE_UNVERIFIED_DRAM_INIT
static uint32_t dram_field_insert(uint32_t value, uint8_t high, uint8_t low,
                                  uint32_t field) {
    if (high > 31U || low > high) {
        return value;
    }
    const uint8_t width = (uint8_t)(high - low + 1U);
    const uint32_t unshifted_mask = width == 32U
                                        ? UINT32_MAX
                                        : (UINT32_C(1) << width) - 1U;
    const uint32_t mask = unshifted_mask << low;
    return (value & ~mask) | ((field & unshifted_mask) << low);
}
#endif

static void dram_copy(void *destination, const void *source, size_t length) {
    uint8_t *to = (uint8_t *)destination;
    const uint8_t *from = (const uint8_t *)source;
    for (size_t index = 0U; index < length; ++index) {
        to[index] = from[index];
    }
}

static bool dram_equal(const void *left, const void *right, size_t length) {
    const uint8_t *a = (const uint8_t *)left;
    const uint8_t *b = (const uint8_t *)right;
    for (size_t index = 0U; index < length; ++index) {
        if (a[index] != b[index]) {
            return false;
        }
    }
    return true;
}

#if KB7_ENABLE_UNVERIFIED_DRAM_INIT
#if defined(KB7_HOST_TEST)
static void dram_delay_cycles(uint32_t cycles) { (void)cycles; }
static bool dram_delay_us(uint32_t microseconds) {
    (void)microseconds;
    return true;
}
#else
#define dram_delay_cycles kb7_delay_cycles
#define dram_delay_us kb7_delay_us
#endif
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

#if KB7_ENABLE_UNVERIFIED_DRAM_INIT
static bool wait_register(uint32_t offset, uint32_t mask, uint32_t expected) {
    uint32_t timeout = KB7_DRAM_WAIT_LIMIT;
    while ((KB7_MMIO32(SNC_DRAM_BASE + offset) & mask) != expected) {
        if (timeout == 0U) {
            return false;
        }
        --timeout;
        dram_delay_cycles(8U);
    }
    return true;
}

static void dram_set(uint32_t offset, uint8_t high, uint8_t low, uint32_t value) {
    KB7_MMIO32(SNC_DRAM_BASE + offset) =
        dram_field_insert(KB7_MMIO32(SNC_DRAM_BASE + offset), high, low, value);
}

static bool dram_command(uint8_t first, uint8_t second, uint8_t third) {
    uint32_t command = KB7_MMIO32(SNC_DRAM_BASE + SNC_DRAM_COMMAND);
    command = dram_field_insert(command, 7U, 0U, first);
    command = dram_field_insert(command, 15U, 8U, second);
    command = dram_field_insert(command, 23U, 16U, third);
    KB7_MMIO32(SNC_DRAM_BASE + SNC_DRAM_COMMAND) = command;

    uint32_t control = KB7_MMIO32(SNC_DRAM_BASE + SNC_DRAM_CONTROL);
    KB7_MMIO32(SNC_DRAM_BASE + SNC_DRAM_CONTROL) = control & ~KB7_BIT(16);
    KB7_MMIO32(SNC_DRAM_BASE + SNC_DRAM_CONTROL) = control | KB7_BIT(16);
    return wait_register(SNC_DRAM_CONTROL, KB7_BIT(17), KB7_BIT(17));
}

static bool dram_phy_train(void) {
    KB7_MMIO32(SNC_DRAM_BASE + 0x60U) =
        (KB7_MMIO32(SNC_DRAM_BASE + 0x60U) & UINT32_C(6)) | UINT32_C(4);
    KB7_MMIO32(SNC_DRAM_BASE + 0xd4U) = KB7_MMIO32(SNC_DRAM_BASE + 0xd4U);
    KB7_MMIO32(SNC_DRAM_BASE + 0xa0U) = UINT32_C(0x0f0f0f0f);
    KB7_MMIO32(SNC_DRAM_BASE + 0xa4U) = UINT32_C(0x0f0f0f0f);
    KB7_MMIO32(SNC_DRAM_BASE + 0xc0U) = 0U;
    KB7_MMIO32(SNC_DRAM_BASE + 0xc4U) &= UINT32_C(0xffff8888);
    KB7_MMIO32(SNC_DRAM_BASE + 0x1cU) = UINT32_C(0x00420004);
    KB7_MMIO32(SNC_DRAM_BASE + 0x20U) = UINT32_C(0x40404040);
    KB7_MMIO32(SNC_DRAM_BASE + 0x24U) = UINT32_C(0x00051402);
    dram_set(0x04U, 23U, 22U, 1U);
    KB7_MMIO32(SNC_DRAM_BASE + 0x28U) = UINT32_C(0x01010008);
    KB7_MMIO32(SNC_DRAM_BASE + 0x34U) = UINT32_C(0xf5ffffff);
    KB7_MMIO32(SNC_DRAM_BASE + 0x38U) = UINT32_C(0x0000f000);
    KB7_MMIO32(SNC_DRAM_BASE + 0x3cU) = 0U;
    KB7_MMIO32(SNC_DRAM_BASE + 0x40U) = 0U;
    dram_set(0x5cU, 23U, 22U, 1U);
    KB7_MMIO32(SNC_DRAM_BASE + 0x18U) =
        (KB7_MMIO32(SNC_DRAM_BASE + 0x18U) & UINT32_C(0xfffe0088)) |
        UINT32_C(0x00010000);
    if (!wait_register(0x18U, UINT32_C(3) << 24U, UINT32_C(3) << 24U)) {
        return false;
    }

    uint32_t training = KB7_MMIO32(SNC_DRAM_BASE + 0xe0U);
    training = dram_field_insert(training, 3U, 3U, 1U);
    training = dram_field_insert(training, 0U, 0U, 1U);
    training = dram_field_insert(training, 6U, 4U, 2U);
    training = dram_field_insert(training, 12U, 8U, 6U);
    training = dram_field_insert(training, 15U, 13U, 3U);
    training = dram_field_insert(training, 31U, 16U, UINT32_C(0x0140));
    KB7_MMIO32(SNC_DRAM_BASE + 0xe0U) = training | KB7_BIT(0);
    KB7_MMIO32(SNC_DRAM_BASE + 0xf0U) = UINT32_C(0xffff00f0);

    dram_set(0xe4U, 11U, 8U, 4U);
    dram_set(0xe4U, 27U, 24U, 8U);
    dram_set(0xe4U, 28U, 28U, 0U);
    dram_set(0xe4U, 31U, 30U, 1U);
    dram_set(0xe8U, 3U, 0U, 2U);
    dram_set(0xe8U, 6U, 4U, 4U);
    dram_set(0xe8U, 23U, 16U, 2U);
    dram_set(0xe8U, 31U, 24U, 3U);
    dram_delay_cycles(6942U);
    if (!wait_register(0xe0U, KB7_BIT(1), KB7_BIT(1))) {
        return false;
    }
    KB7_MMIO32(SNC_DRAM_BASE + 0xe0U) &= ~KB7_BIT(1);
    if (!wait_register(0xe0U, KB7_BIT(1), KB7_BIT(1))) {
        return false;
    }

    dram_set(0xecU, 7U, 0U, UINT32_C(0xff));
    KB7_MMIO32(SNC_DRAM_BASE + SNC_DRAM_CONTROL) |= KB7_BIT(16);
    dram_delay_cycles(462U);
    if (!wait_register(SNC_DRAM_CONTROL, KB7_BIT(17), KB7_BIT(17))) {
        return false;
    }
    dram_delay_cycles(1000U);

    if (!dram_command(UINT8_C(0xc0), 0U, 4U) ||
        !dram_command(UINT8_C(0xc0), 4U, UINT8_C(0x80)) ||
        !dram_command(UINT8_C(0xc0), 8U, 3U) ||
        !dram_command(UINT8_C(0x40), 2U, 0U) ||
        !dram_command(UINT8_C(0x40), 0U, 0U) ||
        !dram_command(UINT8_C(0x40), 4U, 0U)) {
        return false;
    }
    if ((KB7_MMIO32(SNC_DRAM_BASE + SNC_DRAM_COMMAND) >> 24U) != UINT32_C(0x80)) {
        return false;
    }

    dram_set(0xe8U, 3U, 0U, 2U);
    dram_set(0xe8U, 6U, 4U, 4U);
    dram_set(0xe8U, 23U, 16U, 2U);
    dram_set(0xe8U, 31U, 24U, 3U);
    KB7_MMIO32(SNC_DRAM_BASE + 0x0cU) |= KB7_BIT(0);
    kb7_dsb();
    return true;
}
#endif

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

#if KB7_ENABLE_UNVERIFIED_DRAM_INIT
static bool dram_non_destructive_test(uintptr_t address) {
    volatile uint32_t *const memory = (volatile uint32_t *)address;
    uint32_t saved[16];
    bool valid = true;
    for (size_t index = 0U; index < KB7_ARRAY_LEN(saved); ++index) {
        saved[index] = memory[index];
        memory[index] = pattern(index, 4U);
    }
    kb7_dsb();
    for (size_t index = 0U; index < KB7_ARRAY_LEN(saved); ++index) {
        if (memory[index] != pattern(index, 4U)) {
            valid = false;
        }
    }
    for (size_t index = 0U; index < KB7_ARRAY_LEN(saved); ++index) {
        memory[index] = saved[index];
    }
    kb7_dsb();
    for (size_t index = 0U; index < KB7_ARRAY_LEN(saved); ++index) {
        if (memory[index] != saved[index]) {
            valid = false;
        }
    }
    return valid;
}
#endif

bool kb7_dram_init_and_train(void) {
#if KB7_ENABLE_UNVERIFIED_DRAM_INIT
    KB7_MMIO32(SNC_SYS1_BASE + SNC_SYS1_DRAM_CLOCK) = 1U;
    if (!dram_delay_us(500U)) {
        return false;
    }
    if (!dram_phy_train()) {
        return false;
    }

    uint32_t clocks =
        KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PERIPHERAL_CLOCK_CONTROL);
    clocks = dram_field_insert(clocks, 15U, 14U, 3U);
    clocks = dram_field_insert(clocks, 5U, 4U, 3U);
    clocks = dram_field_insert(clocks, 13U, 12U, 2U);
    clocks = dram_field_insert(clocks, 7U, 6U, 2U);
    clocks = dram_field_insert(clocks, 9U, 8U, 2U);
    clocks = dram_field_insert(clocks, 3U, 2U, 2U);
    clocks = dram_field_insert(clocks, 1U, 0U, 1U);
    clocks = dram_field_insert(clocks, 11U, 10U, 1U);
    KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PERIPHERAL_CLOCK_CONTROL) = clocks;
    return dram_non_destructive_test(KB7_FRAMEBUFFER_A);
#else
    return false;
#endif
}

#if defined(KB7_HOST_TEST)
__attribute__((weak)) uint8_t
kb7_cache_test_control_read(volatile const uint8_t *address) {
    return *address;
}
#endif

static bool cache_copy_mode_idle(void) {
    uint32_t timeout = KB7_CACHE_WAIT_LIMIT;
    /*
     * Stock V1.22 at 0x00006f9e..0x00006faa reads the control byte,
     * adds four to that value, and tests bit one.  Adding four cannot change
     * bit one, so express the same poll directly without suggesting that +4
     * is a status-register address (the real +0x04 register is the remap
     * offset written later at 0x00006fd4).
     */
    volatile const uint8_t *const control =
        (volatile const uint8_t *)(uintptr_t)(SNC_ICACHE_BASE +
                                              SNC_ICACHE_CONTROL);
#if defined(KB7_HOST_TEST)
#define CACHE_CONTROL_READ(address) kb7_cache_test_control_read(address)
#else
#define CACHE_CONTROL_READ(address) (*(address))
#endif
    while ((CACHE_CONTROL_READ(control) & UINT8_C(2)) != 0U) {
        if (timeout == 0U) {
            return false;
        }
        --timeout;
    }
#undef CACHE_CONTROL_READ
    return true;
}

bool kb7_cache_prepare_region1(void) {
    if (KB7_REGION1_OPI_SOURCE < KB7_OPI_BASE ||
        KB7_REGION1_COPY_BYTES > KB7_OPI_END - KB7_REGION1_OPI_SOURCE ||
        KB7_REGION1_COPY_BYTES > UINT32_C(0x00100000)) {
        return false;
    }

    uint32_t control = KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL);
    KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL) =
        (control & ~UINT32_C(0xf0)) | UINT32_C(0x40);
    dram_copy((void *)(uintptr_t)KB7_REGION1_OPI_SOURCE,
              (const void *)(uintptr_t)KB7_REGION1_FLASH_SOURCE,
              KB7_REGION1_COPY_BYTES);
    kb7_dsb();
    if (!cache_copy_mode_idle() ||
        !dram_equal((const void *)(uintptr_t)KB7_REGION1_OPI_SOURCE,
                    (const void *)(uintptr_t)KB7_REGION1_FLASH_SOURCE,
                    KB7_REGION1_COPY_BYTES)) {
        KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL) = 0U;
        kb7_dsb();
        kb7_isb();
        return false;
    }

    control = KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL);
    KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL) =
        (control & ~UINT32_C(0xf0)) | UINT32_C(0x80);
    KB7_MMIO32(SNC_SYS1_BASE + SNC_SYS1_CLOCK_RESET) |= KB7_BIT(11);
    KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_OFFSET) = KB7_REGION1_OPI_SOURCE;
    KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_OFFSET) = KB7_REGION1_OPI_SOURCE;
    KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL) = UINT32_C(2);
    kb7_dsb();
    kb7_isb();
    if (!dram_equal((const void *)(uintptr_t)(KB7_REGION1_ENTRY & ~UINT32_C(1)),
                    (const void *)(uintptr_t)KB7_REGION1_OPI_SOURCE,
                    KB7_REGION1_COPY_BYTES)) {
        KB7_MMIO32(SNC_ICACHE_BASE + SNC_ICACHE_CONTROL) = 0U;
        kb7_dsb();
        kb7_isb();
        return false;
    }
    return true;
}
