#define _GNU_SOURCE
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "kb7/drivers.h"
#include "kb7/runtime.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

static uint32_t tick;

static uint32_t milliseconds(void) {
    return tick++;
}

void kb7_gpio_configure(uint8_t logical, enum kb7_gpio_direction direction,
                        uint8_t function, enum kb7_gpio_pull pull) {
    (void)logical;
    (void)direction;
    (void)function;
    (void)pull;
}

int main(void) {
    void *mapping = mmap((void *)(uintptr_t)KB7_SHARED_API_ADDRESS, 4096U,
                         PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (mapping == MAP_FAILED) return 77;
    volatile struct kb7_runtime_api *api = kb7_runtime();
    memset((void *)api, 0, sizeof(*api));
    if (kb7_delay_ms(1U)) return 1;
    api->magic = KB7_RUNTIME_MAGIC;
    api->milliseconds = milliseconds;
    tick = 0U;
    if (!kb7_delay_ms(100U) || tick < 101U) return 2;
    tick = UINT32_C(0xfffffffe);
    if (!kb7_delay_ms(5U) || tick != 4U) return 3;
    return 0;
}
