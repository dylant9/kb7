#ifndef KB7_RUNTIME_H
#define KB7_RUNTIME_H

#include "kb7/platform.h"
#include "kb7/regs.h"

#define KB7_RUNTIME_MAGIC UINT32_C(0x4b423741)
#define KB7_RUNTIME_ABI_VERSION 1U

enum kb7_boot_flags {
    KB7_BOOT_CLOCK_READY = KB7_BIT(0),
    KB7_BOOT_DRAM_READY = KB7_BIT(1),
    KB7_BOOT_USB_READY = KB7_BIT(2),
    KB7_BOOT_INDEPENDENT_BUILD = KB7_BIT(31),
};

struct kb7_runtime_api {
    uint32_t magic;
    uint16_t abi_version;
    uint16_t size;
    uint32_t boot_flags;
    uint32_t (*milliseconds)(void);
    void (*usb_poll)(void);
    int32_t (*usb_send)(uint8_t endpoint, const void *data, uint16_t length);
    int32_t (*flash_read)(uint32_t offset, void *data, uint32_t length);
    int32_t (*flash_erase_4k)(uint32_t offset);
    int32_t (*flash_program)(uint32_t offset, const void *data, uint32_t length);
    void (*enter_loader)(void);
};

struct kb7_shared_state {
    volatile uint32_t milliseconds;
    volatile uint32_t boot_flags;
    volatile uint32_t usb_events;
    volatile uint32_t last_error;
};

static inline volatile struct kb7_runtime_api *kb7_runtime(void) {
    return (volatile struct kb7_runtime_api *)(uintptr_t)KB7_SHARED_API_ADDRESS;
}

static inline volatile struct kb7_shared_state *kb7_shared(void) {
    return (volatile struct kb7_shared_state *)(uintptr_t)KB7_SHARED_STATE_ADDRESS;
}

#endif
