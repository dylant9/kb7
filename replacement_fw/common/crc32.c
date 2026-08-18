#include "kb7/platform.h"

uint32_t kb7_crc32_begin(void) {
    return UINT32_C(0xffffffff);
}

uint32_t kb7_crc32_extend(uint32_t crc, const void *data, size_t length) {
    const uint8_t *cursor = (const uint8_t *)data;
    while (length-- != 0U) {
        crc ^= *cursor++;
        for (uint32_t bit = 0; bit < 8U; ++bit) {
            const uint32_t mask = (uint32_t)-(int32_t)(crc & 1U);
            crc = (crc >> 1U) ^ (UINT32_C(0xedb88320) & mask);
        }
    }
    return crc;
}

uint32_t kb7_crc32_finish(uint32_t state) {
    return ~state;
}

uint32_t kb7_crc32(const void *data, size_t length) {
    return kb7_crc32_finish(kb7_crc32_extend(kb7_crc32_begin(), data, length));
}
