#include "kb7/drivers.h"
#include "kb7/regs.h"

typedef uint32_t (*rom_clock_fn_t)(uint32_t control, volatile uint32_t *instance);
#define KB7_ROM_CLOCK_TRANSITION ((rom_clock_fn_t)(uintptr_t)UINT32_C(0x0800603d))

bool kb7_clock_init(void) {
    volatile uint32_t *const instance =
        (volatile uint32_t *)(uintptr_t)SNC_PERIPHERAL_CLOCKED_BASE;
    uint32_t control = *instance;
    const uint32_t clock_state = KB7_MMIO32(SNC_CLOCK_BASE + 0x0cU) & 7U;
    if (clock_state != 4U) {
        control = (control & ~UINT32_C(0x3000)) | UINT32_C(0x1000);
    }
    control |= UINT32_C(0x8000);
    *instance = control;
    const uint32_t result = KB7_ROM_CLOCK_TRANSITION(control, instance);
    kb7_dsb();
    return result == 0U || result == UINT32_C(0x00ffffff);
}
