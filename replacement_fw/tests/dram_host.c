#define _GNU_SOURCE
#include <stdint.h>
#include <sys/mman.h>

#include "kb7/drivers.h"
#include "kb7/regs.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

int main(void) {
    void *dram = mmap((void *)(uintptr_t)SNC_DRAM_BASE, 4096U,
                      PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    void *clock = mmap((void *)(uintptr_t)SNC_CLOCK_BASE, 4096U,
                       PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (dram == MAP_FAILED || clock == MAP_FAILED) return 77;
    /* Status remains zero. A real timeout must return before the march test. */
    if (kb7_dram_init_and_train()) return 1;
    return 0;
}
