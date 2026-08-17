#include "kb7/platform.h"

void *kb7_memcpy(void *destination, const void *source, size_t length) {
    uint8_t *out = (uint8_t *)destination;
    const uint8_t *in = (const uint8_t *)source;
    while (length-- != 0U) {
        *out++ = *in++;
    }
    return destination;
}

void *kb7_memset(void *destination, int value, size_t length) {
    uint8_t *out = (uint8_t *)destination;
    while (length-- != 0U) {
        *out++ = (uint8_t)value;
    }
    return destination;
}

int kb7_memcmp(const void *left, const void *right, size_t length) {
    const uint8_t *a = (const uint8_t *)left;
    const uint8_t *b = (const uint8_t *)right;
    while (length-- != 0U) {
        if (*a != *b) {
            return (int)*a - (int)*b;
        }
        ++a;
        ++b;
    }
    return 0;
}

/* GCC may lower aggregate copies/zero-initializers to the standard symbols. */
void *memcpy(void *destination, const void *source, size_t length) {
    return kb7_memcpy(destination, source, length);
}

void *memset(void *destination, int value, size_t length) {
    return kb7_memset(destination, value, length);
}

int memcmp(const void *left, const void *right, size_t length) {
    return kb7_memcmp(left, right, length);
}
