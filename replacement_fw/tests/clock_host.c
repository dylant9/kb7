#include "kb7/drivers.h"

int main(void) {
    if (kb7_clock_rom_result_ok(0U)) return 1;
    if (kb7_clock_rom_result_ok(UINT32_C(0x00ffffff))) return 2;
    if (!kb7_clock_rom_result_ok(1U)) return 3;
    if (!kb7_clock_rom_result_ok(UINT32_C(0xffffffff))) return 4;

    const uint32_t ordinary = kb7_clock_control_for_state(UINT32_C(0xffffffff), 3U);
    if ((ordinary & UINT32_C(0x3000)) != UINT32_C(0x1000) ||
        (ordinary & UINT32_C(0x8000)) == 0U) return 5;
    const uint32_t divided = kb7_clock_control_for_state(0U, 4U);
    if ((divided & UINT32_C(0x3000)) != UINT32_C(0x3000) ||
        (divided & UINT32_C(0x8000)) == 0U) return 6;
    return 0;
}
