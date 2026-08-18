#include "kb7/drivers.h"
#include "kb7/regs.h"

typedef uint32_t (*rom_clock_fn_t)(uint32_t control, volatile uint32_t *instance);
#define KB7_ROM_CLOCK_TRANSITION ((rom_clock_fn_t)(uintptr_t)UINT32_C(0x0800603d))

uint32_t kb7_clock_control_for_state(uint32_t control, uint32_t clock_state) {
    if (clock_state != 4U) {
        control = (control & ~UINT32_C(0x3000)) | UINT32_C(0x1000);
    } else {
        /* Recovered clean-room behavior: choose the first divider <= 40 MHz. */
        uint32_t divider = 1U;
        while (divider < 3U &&
               (UINT32_C(0x0bcd3d80) >> divider) > UINT32_C(0x02625a00)) {
            ++divider;
        }
        control = (control & ~UINT32_C(0x3000)) | ((divider & 3U) << 12U);
    }
    return control | UINT32_C(0x8000);
}

bool kb7_clock_rom_result_ok(uint32_t result) {
    /* Both sentinels enter fatal case 6 in the two reference versions. */
    return result != 0U && result != UINT32_C(0x00ffffff);
}

bool kb7_clock_init(void) {
    /* The datasheet identifies this recovered instance as the SPI-NOR controller. */
    volatile uint32_t *const instance =
        (volatile uint32_t *)(uintptr_t)SNC_SPI_NOR_BASE;
    const uint32_t clock_state = KB7_MMIO32(SNC_CLOCK_BASE + 0x0cU) & 7U;
    const uint32_t control = kb7_clock_control_for_state(*instance, clock_state);
    *instance = control;
    const uint32_t result = KB7_ROM_CLOCK_TRANSITION(control, instance);
    kb7_dsb();
    return kb7_clock_rom_result_ok(result);
}
