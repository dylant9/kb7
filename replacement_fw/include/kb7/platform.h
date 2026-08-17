#ifndef KB7_PLATFORM_H
#define KB7_PLATFORM_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define KB7_BIT(n) (UINT32_C(1) << (n))
#define KB7_ARRAY_LEN(a) (sizeof(a) / sizeof((a)[0]))
#define KB7_MMIO32(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define KB7_PACKED __attribute__((packed))
#define KB7_NORETURN __attribute__((noreturn))

static inline void kb7_dmb(void) { __asm__ volatile("dmb" ::: "memory"); }
static inline void kb7_dsb(void) { __asm__ volatile("dsb" ::: "memory"); }
static inline void kb7_isb(void) { __asm__ volatile("isb" ::: "memory"); }
static inline void kb7_wfi(void) { __asm__ volatile("wfi"); }

void *kb7_memcpy(void *destination, const void *source, size_t length);
void *kb7_memset(void *destination, int value, size_t length);
int kb7_memcmp(const void *left, const void *right, size_t length);
uint32_t kb7_crc32(const void *data, size_t length);

#endif
