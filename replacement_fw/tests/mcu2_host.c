#define _GNU_SOURCE
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "kb7/drivers.h"
#include "kb7/mcu2_protocol.h"
#include "kb7/regs.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

int main(void) {
    uint8_t response[KB7_MCU2_FRAME_SIZE] = {0};
    uint8_t values[KB7_HALL_KEY_COUNT] = {0};
    response[0] = 0xa3U;
    response[1] = 0U;
    for (uint8_t index = 0U; index < KB7_HALL_KEY_COUNT; ++index) {
        response[index + 2U] = (uint8_t)(index * 3U + 1U);
    }
    /* The final five bytes are samples, not the request's AA..EE trailer. */
    if (kb7_mcu2_decode_normalized(response, values) != KB7_MCU2_OK) return 1;
    for (uint8_t index = 0U; index < KB7_HALL_KEY_COUNT; ++index) {
        if (values[index] != response[index + 2U]) return 2;
    }
    response[1] = 1U;
    if (kb7_mcu2_decode_normalized(response, values) != KB7_MCU2_BUSY) return 3;
    response[0] = 0U;
    if (kb7_mcu2_decode_normalized(response, values) != KB7_MCU2_BAD_FRAME) return 4;

    void *mapping = mmap((void *)(uintptr_t)SNC_MCU2_SERIAL_BASE, 4096U,
                         PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (mapping == MAP_FAILED) return 77;
    uint8_t request[KB7_MCU2_FRAME_SIZE] = {0};
    request[0] = 0xa5U;
    request[1] = 0xa3U;
    const uint8_t trailer[] = {0xaaU, 0xbbU, 0xccU, 0xddU, 0xeeU};
    memcpy(&request[79], trailer, sizeof(trailer));
    /* With the recovered block enabled, an idle-zero status register must
     * fail closed at the finite timeout instead of hanging or returning data. */
    if (kb7_mcu2_exchange(request, response) != KB7_MCU2_IO) return 5;
    return 0;
}
