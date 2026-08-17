#include "kb7/drivers.h"

#define KB7_FLASH_XIP_BASE UINT32_C(0x60000000)
#define KB7_FLASH_SIZE UINT32_C(0x02000000)

int32_t kb7_flash_read(uint32_t offset, void *data, uint32_t length) {
    if (data == NULL || offset > KB7_FLASH_SIZE || length > KB7_FLASH_SIZE - offset) {
        return -1;
    }
    kb7_memcpy(data, (const void *)(uintptr_t)(KB7_FLASH_XIP_BASE + offset), length);
    return 0;
}

int32_t kb7_flash_erase_4k(uint32_t offset) {
    (void)offset;
    /* Fail closed until controller command/timing is passively validated. */
    return -1;
}

int32_t kb7_flash_program(uint32_t offset, const void *data, uint32_t length) {
    (void)offset;
    (void)data;
    (void)length;
    /* Fail closed: no unvalidated flash mutation in the first engineering image. */
    return -1;
}
