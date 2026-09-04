/*
 * Region-1 loader-reentry proof.
 *
 * Stock region 0 boots the SoC, copies region 1 into OPI DRAM behind the
 * instruction-cache aperture and calls 0x1004a525 with SP = 0x1803f5c0,
 * PRIMASK clear and no interrupt enabled by region 0 itself (the loader's
 * residual NVIC state is unknown).  This image replaces the stock main at
 * that entry and does one thing: it takes ownership of the exception state
 * and then deliberately re-enters the preserved USB loader through the
 * stock-equivalent relocation in drivers/recovery.c.
 *
 * Nothing here touches flash, USB, clocks, DRAM or any peripheral.
 */
#include "kb7/config.h"
#include "kb7/drivers.h"
#include "kb7/platform.h"
#include "kb7/regs.h"

#if !KB7_BUILD_LOADER_REENTRY_PROOF || !KB7_ENABLE_UNVERIFIED_LOADER_REENTRY
#error "region1_reentry_proof.c is only part of the loader re-entry proof profile"
#endif

#define KB7_REGION1_PROOF_VECTOR_TABLE UINT32_C(0x18030000)
#define KB7_REGION1_PROOF_VECTOR_COUNT 79U

static void region1_proof_park(void) KB7_NORETURN;
static void region1_proof_park(void) {
    kb7_disable_irq();
    for (;;) {
        kb7_wfi();
    }
}

_Static_assert(KB7_CORE0_STACK_TOP == UINT32_C(0x1803f5c0),
               "the naked entry below hard-codes the stock stack top");

void region1_proof_main(void) KB7_NORETURN;
__attribute__((used, noinline))
void region1_proof_main(void) {
    /*
     * Review F1 (2026-09-02) for the Core-0 proof, applied to region 1: mask,
     * disable and clear every interrupt source and stop SysTick before any
     * other action, so nothing the loader or region 0 left armed can fire
     * into a stale vector.
     */
    kb7_disable_irq();
    KB7_MMIO32(SNC_NVIC_ICER) = UINT32_C(0xffffffff);
    KB7_MMIO32(SNC_NVIC_ICER + 4U) = UINT32_C(0xffffffff);
    KB7_MMIO32(SNC_NVIC_ICPR) = UINT32_C(0xffffffff);
    KB7_MMIO32(SNC_NVIC_ICPR + 4U) = UINT32_C(0xffffffff);
    KB7_MMIO32(SNC_SYST_CSR) = 0U;
    kb7_dsb();
    kb7_isb();

    /*
     * Own the vector table.  Region 0's table at PRAM 0 dispatches five
     * vectors into stale stock region-1 addresses; from here every exception
     * parks instead.  The table lives in zeroed SRAM below the stack window
     * that the relocation bridge checks, at a 512-byte aligned address as the
     * 79-entry table requires.
     */
    volatile uint32_t *const table =
        (volatile uint32_t *)(uintptr_t)KB7_REGION1_PROOF_VECTOR_TABLE;
    table[0] = KB7_CORE0_STACK_TOP;
    for (uint32_t index = 1U; index < KB7_REGION1_PROOF_VECTOR_COUNT; ++index) {
        table[index] = (uint32_t)(uintptr_t)region1_proof_park;
    }
    kb7_dsb();
    /* Literal-pool form so the build check can see the VTOR address. */
    __asm__ volatile(
        "ldr r1, =0xe000ed08\n"
        "str %0, [r1]\n"
        "dsb sy\n"
        "isb sy\n"
        :
        : "r"(KB7_REGION1_PROOF_VECTOR_TABLE)
        : "r1", "memory");

    /* Deliberate loader entry: marker, read-back, relocation, PRAM reset. */
    kb7_enter_loader();
}

/*
 * The entry is naked so that the stack pointer is re-established before any
 * compiler-generated frame exists.  Region 0 hands over SP = 0x1803f5c0
 * already; setting it again makes the proof independent of that detail and
 * keeps MSP inside the window the relocation bridge verifies.
 */
__attribute__((section(".entry"), naked, used, noreturn))
void region1_proof_entry(void) {
    __asm__ volatile(
        "cpsid i\n"
        "ldr r0, =0x1803f5c0\n"
        "msr msp, r0\n"
        "dsb sy\n"
        "isb sy\n"
        "b region1_proof_main\n"
        ::: "r0", "memory");
}
