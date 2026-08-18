#include "kb7/drivers.h"
#include "kb7/platform_boot.h"
#include "kb7/regs.h"
#include "kb7/storage.h"

#define KB7_FLASH_XIP_BASE UINT32_C(0x60000000)
#define KB7_FLASH_SIZE UINT32_C(0x02000000)
#define KB7_FLASH_SECTOR_SIZE UINT32_C(0x1000)
#define KB7_FLASH_PAGE_SIZE UINT32_C(0x100)
#define KB7_FLASH_WAIT_LIMIT UINT32_C(4000000)
#define KB7_FLASH_STATUS_WIP KB7_BIT(0)
#define KB7_FLASH_STATUS_BP_MASK UINT32_C(0x3c)
#define KB7_SHARED_SRAM_BASE UINT32_C(0x18000000)
#define KB7_SHARED_SRAM_END UINT32_C(0x18040000)

/* Mutation is compiled but unreachable in public builds until explicitly gated. */
#ifndef KB7_ENABLE_FLASH_MUTATION
#define KB7_ENABLE_FLASH_MUTATION 0
#endif

static bool flash_range_valid(uint32_t offset, uint32_t length) {
    if (length == 0U) return offset <= KB7_FLASH_SIZE;
    return offset < KB7_FLASH_SIZE && length <= KB7_FLASH_SIZE - offset;
}

bool kb7_flash_range_mutable(uint32_t offset, uint32_t length) {
    if (length == 0U) {
        return false;
    }
    const uint32_t starts[] = {
        KB7_STORAGE_SCREEN_A, KB7_STORAGE_SCREEN_B,
        KB7_STORAGE_PROFILE_A, KB7_STORAGE_PROFILE_B,
    };
    const uint32_t sizes[] = {
        KB7_STORAGE_SCREEN_SLOT_BYTES, KB7_STORAGE_SCREEN_SLOT_BYTES,
        KB7_STORAGE_PROFILE_SLOT_BYTES, KB7_STORAGE_PROFILE_SLOT_BYTES,
    };
    for (size_t slot = 0U; slot < KB7_ARRAY_LEN(starts); ++slot) {
        if (offset >= starts[slot] && offset < starts[slot] + sizes[slot] &&
            length <= starts[slot] + sizes[slot] - offset) {
            return true;
        }
    }
    return false;
}

#if KB7_ENABLE_FLASH_MUTATION
static bool wait_command_clear(uint32_t mask) {
    uint32_t timeout = KB7_FLASH_WAIT_LIMIT;
    while ((KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_COMMAND_CONTROL) & mask) != 0U) {
        if (timeout == 0U) {
            return false;
        }
        --timeout;
    }
    return true;
}

static bool flash_status(uint8_t command, uint8_t *result) {
    if (result == NULL) {
        return false;
    }
    KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_COMMAND) = command;
    KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_COMMAND_CONTROL) |= KB7_BIT(11);
    if (!wait_command_clear(KB7_BIT(11))) {
        return false;
    }
    KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_COMMAND_CONTROL) |= KB7_BIT(14);
    if (!wait_command_clear(KB7_BIT(14))) {
        return false;
    }
    *result = (uint8_t)KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_STATUS);
    return true;
}

static bool flash_wait_idle(uint8_t *final_status) {
    uint32_t timeout = KB7_FLASH_WAIT_LIMIT;
    uint8_t status;
    for (;;) {
        if (!flash_status(UINT8_C(0x05), &status)) {
            return false;
        }
        if ((status & KB7_FLASH_STATUS_WIP) == 0U) {
            if (final_status != NULL) {
                *final_status = status;
            }
            return true;
        }
        if (timeout == 0U) {
            return false;
        }
        --timeout;
    }
}

static bool flash_unprotected_and_idle(void) {
    uint8_t status;
    return flash_wait_idle(&status) && (status & KB7_FLASH_STATUS_BP_MASK) == 0U;
}

static bool flash_erase_controller(uint32_t offset) {
    const uint32_t word_address = offset >> 1U;
    KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_ADDRESS_HIGH) = word_address >> 16U;
    KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_ADDRESS_LOW) = word_address & UINT32_C(0xffff);
    KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_COMMAND_CONTROL) |= KB7_BIT(10);
    if (!wait_command_clear(KB7_BIT(10)) || !wait_command_clear(KB7_BIT(2))) {
        return false;
    }
    return flash_wait_idle(NULL);
}

static bool flash_program_controller(uint32_t offset, const uint8_t *data,
                                     uint32_t length) {
    uint32_t control = KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_CONTROL);
    KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_CONTROL) =
        (control & ~UINT32_C(0x0f)) | KB7_BIT(0);
    KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_DMA_CONTROL) = 0U;
    KB7_MMIO32(SNC_SPI_NOR_BASE + SNC_SFC_COMMAND) = 0U;
    KB7_MMIO32(SNC_SPI_NOR_DMA_BASE + SNC_DMA_PERIPHERAL_ADDRESS) =
        KB7_FLASH_XIP_BASE + offset;
    KB7_MMIO32(SNC_SPI_NOR_DMA_BASE + SNC_DMA_MEMORY_ADDRESS) =
        (uint32_t)(uintptr_t)data;
    KB7_MMIO32(SNC_SPI_NOR_DMA_BASE + SNC_DMA_LENGTH) = length;
    uint32_t dma_control = KB7_MMIO32(SNC_SPI_NOR_DMA_BASE + SNC_DMA_CONTROL);
    dma_control = (dma_control & ~UINT32_C(3)) | KB7_BIT(0);
    KB7_MMIO32(SNC_SPI_NOR_DMA_BASE + SNC_DMA_CONTROL) = dma_control;

    uint32_t timeout = KB7_FLASH_WAIT_LIMIT;
    while ((KB7_MMIO32(SNC_SPI_NOR_DMA_BASE + SNC_DMA_CONTROL) & KB7_BIT(0)) != 0U) {
        if (timeout == 0U) {
            return false;
        }
        --timeout;
    }
    return flash_wait_idle(NULL);
}
#endif

bool kb7_flash_sync_xip(uint32_t offset, uint32_t length) {
    if (!flash_range_valid(offset, length)) {
        return false;
    }
#if KB7_ENABLE_FLASH_MUTATION
    if (!flash_wait_idle(NULL)) {
        return false;
    }
#endif
    /* Cortex-M3 has no D-cache. The SoC I-cache maps 0x10000000, not SFC XIP. */
    kb7_dsb();
    kb7_isb();
    if (length != 0U) {
        volatile const uint8_t *const xip =
            (volatile const uint8_t *)(uintptr_t)(KB7_FLASH_XIP_BASE + offset);
        (void)xip[0];
        (void)xip[length - 1U];
    }
    kb7_dsb();
    return true;
}

int32_t kb7_flash_read(uint32_t offset, void *data, uint32_t length) {
    if (data == NULL || !flash_range_valid(offset, length) ||
        !kb7_flash_sync_xip(offset, length)) {
        return -1;
    }
    kb7_memcpy(data, (const void *)(uintptr_t)(KB7_FLASH_XIP_BASE + offset), length);
    return 0;
}

int32_t kb7_flash_erase_4k(uint32_t offset) {
#if KB7_ENABLE_FLASH_MUTATION
    if ((offset & (KB7_FLASH_SECTOR_SIZE - 1U)) != 0U ||
        !flash_range_valid(offset, KB7_FLASH_SECTOR_SIZE) ||
        !kb7_flash_range_mutable(offset, KB7_FLASH_SECTOR_SIZE) ||
        !flash_unprotected_and_idle() || !flash_erase_controller(offset) ||
        !kb7_flash_sync_xip(offset, KB7_FLASH_SECTOR_SIZE)) {
        return -1;
    }
    volatile const uint8_t *const bytes =
        (volatile const uint8_t *)(uintptr_t)(KB7_FLASH_XIP_BASE + offset);
    for (uint32_t index = 0U; index < KB7_FLASH_SECTOR_SIZE; ++index) {
        if (bytes[index] != UINT8_C(0xff)) {
            return -1;
        }
    }
    return 0;
#else
    (void)offset;
    return -1;
#endif
}

int32_t kb7_flash_program(uint32_t offset, const void *data, uint32_t length) {
#if KB7_ENABLE_FLASH_MUTATION
    const uintptr_t source_address = (uintptr_t)data;
    if (data == NULL || !flash_range_valid(offset, length) ||
        !kb7_flash_range_mutable(offset, length) ||
        source_address < KB7_SHARED_SRAM_BASE || source_address >= KB7_SHARED_SRAM_END ||
        length > KB7_SHARED_SRAM_END - source_address ||
        !flash_unprotected_and_idle()) {
        return -1;
    }
    const uint8_t *source = (const uint8_t *)data;
    volatile const uint8_t *destination =
        (volatile const uint8_t *)(uintptr_t)(KB7_FLASH_XIP_BASE + offset);
    for (uint32_t index = 0U; index < length; ++index) {
        if ((source[index] | destination[index]) != destination[index]) {
            return -1;
        }
    }

    uint32_t cursor = 0U;
    while (cursor < length) {
        const uint32_t page_remaining =
            KB7_FLASH_PAGE_SIZE - ((offset + cursor) & (KB7_FLASH_PAGE_SIZE - 1U));
        uint32_t count = length - cursor;
        if (count > page_remaining) {
            count = page_remaining;
        }
        if (!flash_program_controller(offset + cursor, source + cursor, count)) {
            return -1;
        }
        cursor += count;
    }
    if (!kb7_flash_sync_xip(offset, length)) {
        return -1;
    }
    destination = (volatile const uint8_t *)(uintptr_t)(KB7_FLASH_XIP_BASE + offset);
    for (uint32_t index = 0U; index < length; ++index) {
        if (destination[index] != source[index]) {
            return -1;
        }
    }
    return 0;
#else
    (void)offset;
    (void)data;
    (void)length;
    return -1;
#endif
}
