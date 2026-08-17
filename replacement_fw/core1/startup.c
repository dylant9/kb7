#include "kb7/platform.h"

extern uint32_t __data_load_start__, __data_start__, __data_end__;
extern uint32_t __bss_start__, __bss_end__;
void kb7_application_main(void) KB7_NORETURN;

__attribute__((section(".entry"), used, noreturn))
void core1_entry(void) {
    uint32_t *source = &__data_load_start__;
    for (uint32_t *destination = &__data_start__; destination < &__data_end__;) {
        *destination++ = *source++;
    }
    for (uint32_t *destination = &__bss_start__; destination < &__bss_end__;) {
        *destination++ = 0U;
    }
    kb7_application_main();
}
