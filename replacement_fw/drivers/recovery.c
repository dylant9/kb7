#include "kb7/drivers.h"
#include "kb7/regs.h"

void kb7_enter_loader(void) {
    KB7_MMIO32(KB7_LOADER_FLAG_ADDRESS) = KB7_LOADER_FLAG_VALUE;
    kb7_dsb();
    kb7_isb();
    KB7_MMIO32(SNC_SCB_AIRCR) = UINT32_C(0x05fa0004);
    kb7_dsb();
    for (;;) {
        kb7_wfi();
    }
}
