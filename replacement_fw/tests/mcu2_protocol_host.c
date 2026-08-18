#include <stdint.h>

#include "kb7/mcu2_protocol.h"

int main(void) {
    uint8_t request[KB7_MCU2_FRAME_SIZE];
    kb7_mcu2_build_request(0xa3U, 0U, 0U, request);
    if (!kb7_mcu2_request_valid(request) || request[0] != 0xa5U ||
        request[1] != 0xa3U || request[78] != 0U || request[79] != 0xaaU ||
        request[83] != 0xeeU) return 1;
    request[1] = 0xd0U;
    if (kb7_mcu2_request_valid(request)) return 2;
    request[1] = 0xa3U;
    request[83] = 0U;
    if (kb7_mcu2_request_valid(request)) return 3;
    kb7_mcu2_build_request(0xa3U, 0U, 0U, request);
    uint8_t response[KB7_MCU2_FRAME_SIZE] = {0};
    if (kb7_mcu2_exchange(request, response) != KB7_MCU2_UNSUPPORTED) return 4;

    uint8_t values[KB7_HALL_KEY_COUNT];
    kb7_memset(values, 0x55, sizeof(values));
    response[0] = 0xa2U;
    if (kb7_mcu2_decode_normalized(response, values) != KB7_MCU2_BUSY ||
        values[0] != 0x55U) return 5;
    response[0] = 0x00U;
    if (kb7_mcu2_decode_normalized(response, values) != KB7_MCU2_BAD_FRAME) return 6;
    response[0] = 0xaaU;
    if (kb7_mcu2_decode_normalized(response, values) != KB7_MCU2_BUSY) return 7;
    response[0] = 0xa3U;
    response[1] = 1U;
    if (kb7_mcu2_decode_normalized(response, values) != KB7_MCU2_BUSY) return 8;
    response[1] = 0U;
    for (uint8_t index = 0U; index < KB7_HALL_KEY_COUNT; ++index) {
        response[index + 2U] = (uint8_t)(255U - index);
    }
    if (kb7_mcu2_decode_normalized(response, values) != KB7_MCU2_OK) return 9;
    if (values[0] != 255U || values[81] != 174U) return 10;
    return 0;
}
