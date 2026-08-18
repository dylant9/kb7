#include "kb7/drivers.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"

typedef void (*core1_entry_t)(void);

static uint32_t milliseconds(void) { return kb7_shared()->milliseconds; }

static bool loader_combo_held(void) {
    const uint8_t pins[] = {72U, 73U, 75U, 76U};
    for (size_t index = 0U; index < KB7_ARRAY_LEN(pins); ++index) {
        kb7_gpio_configure(pins[index], KB7_GPIO_INPUT, 0U, KB7_GPIO_PULL_UP);
    }
    for (uint32_t sample = 0U; sample < 3000U; ++sample) {
        bool held = true;
        for (size_t index = 0U; index < KB7_ARRAY_LEN(pins); ++index) {
            held = held && !kb7_gpio_read(pins[index]);
        }
        if (!held) {
            return false;
        }
        kb7_delay_cycles(1000U);
    }
    return true;
}

void core0_main(void) {
    KB7_MMIO32(SNC_SCB_VTOR) = 0U;
    volatile struct kb7_shared_state *const state = kb7_shared();
    volatile struct kb7_runtime_api *const api = kb7_runtime();
    state->milliseconds = 0U;
    state->boot_flags = KB7_BOOT_INDEPENDENT_BUILD;
    state->usb_events = 0U;
    state->last_error = 0U;

    if (loader_combo_held()) {
        kb7_enter_loader();
    }
    if (!kb7_clock_init()) {
        state->last_error = UINT32_C(0xc10c0006);
        kb7_enter_loader();
    }
    state->boot_flags |= KB7_BOOT_CLOCK_READY;
    if (kb7_dram_init_and_train()) {
        state->boot_flags |= KB7_BOOT_DRAM_READY;
    }
    if (kb7_usb_init()) {
        state->boot_flags |= KB7_BOOT_USB_READY;
    }

    api->magic = KB7_RUNTIME_MAGIC;
    api->abi_version = KB7_RUNTIME_ABI_VERSION;
    api->size = sizeof(*api);
    api->boot_flags = state->boot_flags;
    api->milliseconds = milliseconds;
    api->usb_poll = kb7_usb_poll;
    api->usb_send = kb7_usb_send;
    api->flash_read = kb7_flash_read;
    api->flash_erase_4k = kb7_flash_erase_4k;
    api->flash_program = kb7_flash_program;
    api->enter_loader = kb7_enter_loader;
    kb7_dsb();

    KB7_MMIO32(SNC_SYST_RVR) = UINT32_C(120000) - 1U;
    KB7_MMIO32(SNC_SYST_CVR) = 0U;
    KB7_MMIO32(SNC_SYST_CSR) = 7U;
    ((core1_entry_t)(uintptr_t)KB7_CORE1_ENTRY)();
    kb7_enter_loader();
}
