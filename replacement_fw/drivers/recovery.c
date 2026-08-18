#include "kb7/drivers.h"
#include "kb7/platform_boot.h"
#include "kb7/regs.h"

void kb7_fault_capture(uint32_t cause, const uint32_t *stack) {
    kb7_disable_irq();
    volatile struct kb7_fault_record *const record =
        (volatile struct kb7_fault_record *)(uintptr_t)KB7_FAULT_RECORD_ADDRESS;
    record->magic = 0U;
    record->version = KB7_FAULT_VERSION;
    record->cause = cause;
    record->stacked_r0 = stack != NULL ? stack[0] : 0U;
    record->stacked_r1 = stack != NULL ? stack[1] : 0U;
    record->stacked_r2 = stack != NULL ? stack[2] : 0U;
    record->stacked_r3 = stack != NULL ? stack[3] : 0U;
    record->stacked_r12 = stack != NULL ? stack[4] : 0U;
    record->stacked_lr = stack != NULL ? stack[5] : 0U;
    record->stacked_pc = stack != NULL ? stack[6] : 0U;
    record->stacked_xpsr = stack != NULL ? stack[7] : 0U;
    record->cfsr = KB7_MMIO32(SNC_SCB_CFSR);
    record->hfsr = KB7_MMIO32(SNC_SCB_HFSR);
    record->dfsr = KB7_MMIO32(SNC_SCB_DFSR);
    record->afsr = KB7_MMIO32(SNC_SCB_AFSR);
    record->mmfar = KB7_MMIO32(SNC_SCB_MMFAR);
    record->bfar = KB7_MMIO32(SNC_SCB_BFAR);
    record->icsr = KB7_MMIO32(SNC_SCB_ICSR);
    record->shcsr = KB7_MMIO32(SNC_SCB_SHCSR);
    kb7_dsb();
    record->magic = KB7_FAULT_MAGIC;
    kb7_dsb();
    kb7_enter_loader();
}

void kb7_enter_loader(void) {
    /*
     * AIRCR/software reset restarts PRAM on this SoC.  The exact ROM-entering
     * reset entry is not published and a watchdog reset would be destructive
     * if the external recovery path is unavailable. Preserve the observed
     * request marker, then park for the proven MCU_RST/external-reset path.
     */
    KB7_MMIO32(KB7_LOADER_FLAG_ADDRESS) = KB7_LOADER_FLAG_VALUE;
    KB7_MMIO32(SNC_SYST_CSR) = 0U;
    KB7_MMIO32(SNC_NVIC_ICER) = UINT32_C(0xffffffff);
    KB7_MMIO32(SNC_NVIC_ICER + 4U) = UINT32_C(0xffffffff);
    kb7_disable_irq();
    kb7_dsb();
    kb7_isb();
    for (;;) {
        kb7_wfi();
    }
}
