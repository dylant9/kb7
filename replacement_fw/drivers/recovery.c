#include "kb7/drivers.h"
#include "kb7/config.h"
#include "kb7/platform_boot.h"
#include "kb7/regs.h"

#if KB7_ENABLE_UNVERIFIED_LOADER_REENTRY
extern const uint8_t kb7_loader_trampoline_blob_start[];
extern const uint8_t kb7_loader_trampoline_blob_end[];
extern void kb7_loader_trampoline_relocate_and_enter(
    const uint8_t *source, size_t length) KB7_NORETURN;

_Static_assert(KB7_LOADER_TRAMPOLINE_MAX_BYTES +
                   KB7_LOADER_TRAMPOLINE_MIN_STACK_GAP <=
               KB7_LOADER_TRAMPOLINE_STACK_RESERVE,
               "loader trampoline must retain its live-stack safety gap");

static void kb7_reenter_preserved_loader(void) KB7_NORETURN;
static void kb7_reenter_preserved_loader(void) {
    const uintptr_t trampoline_start =
        (uintptr_t)kb7_loader_trampoline_blob_start;
    const uintptr_t trampoline_end =
        (uintptr_t)kb7_loader_trampoline_blob_end;
    if (trampoline_end <= trampoline_start) {
        for (;;) {
            kb7_wfi();
        }
    }
    const size_t trampoline_bytes =
        (size_t)(trampoline_end - trampoline_start);
    if ((trampoline_start & (uintptr_t)UINT32_C(3)) != 0U ||
        trampoline_bytes > (size_t)KB7_LOADER_TRAMPOLINE_MAX_BYTES ||
        trampoline_bytes + (size_t)KB7_LOADER_TRAMPOLINE_MIN_STACK_GAP >
            (size_t)KB7_LOADER_TRAMPOLINE_STACK_RESERVE) {
        for (;;) {
            kb7_wfi();
        }
    }

    kb7_loader_trampoline_relocate_and_enter(
        kb7_loader_trampoline_blob_start, trampoline_bytes);
}
#endif

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
     * A bare AIRCR reset restarts the current PRAM image and is not loader
     * entry.  Stock first copies the preserved loader from 0x60001000 into
     * PRAM, then requests that reset.  Keep that stock-equivalent sequence
     * behind an explicit hardware-validation gate; ordinary builds retain the
     * previous marker-and-park behavior.
     */
    KB7_MMIO32(KB7_LOADER_FLAG_ADDRESS) = KB7_LOADER_FLAG_VALUE;
    kb7_dsb();
    if (KB7_MMIO32(KB7_LOADER_FLAG_ADDRESS) != KB7_LOADER_FLAG_VALUE) {
        for (;;) {
            kb7_wfi();
        }
    }
    KB7_MMIO32(SNC_SYST_CSR) = 0U;
    KB7_MMIO32(SNC_NVIC_ICER) = UINT32_C(0xffffffff);
    KB7_MMIO32(SNC_NVIC_ICER + 4U) = UINT32_C(0xffffffff);
    kb7_disable_irq();
    kb7_dsb();
    kb7_isb();
#if KB7_ENABLE_UNVERIFIED_LOADER_REENTRY
    kb7_reenter_preserved_loader();
#endif
    for (;;) {
        kb7_wfi();
    }
}
