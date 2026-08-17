#include "kb7/platform.h"
#include "kb7/regs.h"
#include "kb7/runtime.h"

extern uint32_t __data_load_start__, __data_start__, __data_end__;
extern uint32_t __bss_start__, __bss_end__;
void core0_main(void) KB7_NORETURN;

static void default_handler(void) {
    kb7_shared()->last_error = UINT32_C(0xdeadc0de);
    for (;;) {
        kb7_wfi();
    }
}

void systick_handler(void) {
    ++kb7_shared()->milliseconds;
}

void reset_handler(void) {
    uint32_t *source = &__data_load_start__;
    for (uint32_t *destination = &__data_start__; destination < &__data_end__;) {
        *destination++ = *source++;
    }
    for (uint32_t *destination = &__bss_start__; destination < &__bss_end__;) {
        *destination++ = 0U;
    }
    core0_main();
}

typedef void (*handler_t)(void);
__attribute__((section(".isr_vector"), used))
const handler_t vectors[64] = {
    [0] = (handler_t)(uintptr_t)KB7_CORE0_STACK_TOP,
    [1] = reset_handler,
    [2 ... 14] = default_handler,
    [15] = systick_handler,
    [16 ... 63] = default_handler,
};
