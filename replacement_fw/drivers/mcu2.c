#include "kb7/drivers.h"
#include "kb7/regs.h"

/* Physical binding is inferred from the SNC transfer closure; keep centralized. */
#define KB7_MCU2_CONTROLLER SNC_MCU2_LINK_BASE
#define MCU2_STATUS 0x5cU
#define MCU2_FIFO 0x78U
#define MCU2_FIFO_STATUS 0x7cU
#define MCU2_LENGTH 0x04U
#define MCU2_LAUNCH 0x38U
#define MCU2_CONTROL 0x00U
#define MCU2_TIMEOUT UINT32_C(800000)

static const uint8_t trailer[5] = {0xaaU, 0xbbU, 0xccU, 0xddU, 0xeeU};

bool kb7_mcu2_init(void) {
    KB7_MMIO32(KB7_MCU2_CONTROLLER + MCU2_CONTROL) = 0U;
    KB7_MMIO32(KB7_MCU2_CONTROLLER + 0x34U) = 0U;
    KB7_MMIO32(KB7_MCU2_CONTROLLER + 0x40U) = 4U;
    KB7_MMIO32(KB7_MCU2_CONTROLLER + 0x48U) = 0U;
    KB7_MMIO32(KB7_MCU2_CONTROLLER + 0x4cU) = 0U;
    KB7_MMIO32(KB7_MCU2_CONTROLLER + 0x50U) = 0U;
    KB7_MMIO32(KB7_MCU2_CONTROLLER + MCU2_CONTROL) = 1U;
    kb7_dsb();
    return true;
}

enum kb7_mcu2_result kb7_mcu2_exchange(const uint8_t request[KB7_MCU2_FRAME_SIZE],
                                       uint8_t response[KB7_MCU2_FRAME_SIZE]) {
    if (request == NULL || response == NULL || request[0] != 0xa5U ||
        kb7_memcmp(&request[79], trailer, sizeof(trailer)) != 0) {
        return KB7_MCU2_BAD_FRAME;
    }
    KB7_MMIO32(KB7_MCU2_CONTROLLER + MCU2_LENGTH) = KB7_MCU2_FRAME_SIZE;
    for (size_t index = 0U; index < KB7_MCU2_FRAME_SIZE; ++index) {
        uint32_t timeout = MCU2_TIMEOUT;
        while ((KB7_MMIO32(KB7_MCU2_CONTROLLER + MCU2_FIFO_STATUS) & 1U) == 0U &&
               timeout-- != 0U) {
        }
        if (timeout == 0U) {
            return KB7_MCU2_IO;
        }
        KB7_MMIO32(KB7_MCU2_CONTROLLER + MCU2_FIFO) = request[index];
    }
    KB7_MMIO32(KB7_MCU2_CONTROLLER + MCU2_LAUNCH) = 1U;
    uint32_t timeout = MCU2_TIMEOUT;
    while ((KB7_MMIO32(KB7_MCU2_CONTROLLER + MCU2_STATUS) & 1U) == 0U && timeout-- != 0U) {
    }
    if (timeout == 0U) {
        return KB7_MCU2_IO;
    }
    for (size_t index = 0U; index < KB7_MCU2_FRAME_SIZE; ++index) {
        response[index] = (uint8_t)KB7_MMIO32(KB7_MCU2_CONTROLLER + MCU2_FIFO);
    }
    if (kb7_memcmp(&response[79], trailer, sizeof(trailer)) != 0) {
        return KB7_MCU2_BAD_FRAME;
    }
    return KB7_MCU2_OK;
}

enum kb7_mcu2_result kb7_mcu2_read_normalized(uint8_t values[KB7_HALL_KEY_COUNT]) {
    uint8_t request[KB7_MCU2_FRAME_SIZE];
    uint8_t response[KB7_MCU2_FRAME_SIZE];
    kb7_memset(request, 0, sizeof(request));
    request[0] = 0xa5U;
    request[1] = 0xa3U;
    kb7_memcpy(&request[79], trailer, sizeof(trailer));
    const enum kb7_mcu2_result result = kb7_mcu2_exchange(request, response);
    if (result != KB7_MCU2_OK) {
        return result;
    }
    if (response[0] != 0xa3U || response[1] != 0U) {
        return KB7_MCU2_BUSY;
    }
    kb7_memcpy(values, &response[2], KB7_HALL_KEY_COUNT);
    return KB7_MCU2_OK;
}
