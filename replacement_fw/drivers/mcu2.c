#include "kb7/mcu2_protocol.h"
#include "kb7/config.h"
#include "kb7/platform_boot.h"
#include "kb7/regs.h"

#define MCU2_CONTROL UINT32_C(0x00)
#define MCU2_CONFIGURATION UINT32_C(0x04)
#define MCU2_DIVISOR UINT32_C(0x08)
#define MCU2_STATUS UINT32_C(0x0c)
#define MCU2_DATA UINT32_C(0x1c)
#define MCU2_AUX_CONTROL UINT32_C(0x20)
#define MCU2_TIMEOUT UINT32_C(800000)

#define MCU2_CS 14U
#define MCU2_CLOCK 15U
#define MCU2_MISO 16U
#define MCU2_MOSI 17U
#define MCU2_READY_STATUS 19U
#define MCU2_PIN_FUNCTION 4U

static const uint8_t trailer[5] = {0xaaU, 0xbbU, 0xccU, 0xddU, 0xeeU};

bool kb7_mcu2_command_supported(uint8_t command) {
    switch (command) {
    case 0xa0U:
    case 0xa1U:
    case 0xa2U:
    case 0xa3U:
    case 0xb0U:
    case 0xb1U:
    case 0xb2U:
    case 0xc0U:
    case 0xc1U:
    case 0xc2U:
        return true;
    default:
        return false;
    }
}

void kb7_mcu2_build_request(uint8_t command, uint8_t subcommand, uint8_t argument,
                            uint8_t request[KB7_MCU2_FRAME_SIZE]) {
    if (request == NULL) return;
    kb7_memset(request, 0, KB7_MCU2_FRAME_SIZE);
    request[0] = 0xa5U;
    request[1] = command;
    request[2] = subcommand;
    request[3] = argument;
    kb7_memcpy(&request[79], trailer, sizeof(trailer));
}

bool kb7_mcu2_request_valid(const uint8_t request[KB7_MCU2_FRAME_SIZE]) {
    return request != NULL && request[0] == 0xa5U &&
           kb7_mcu2_command_supported(request[1]) &&
           kb7_memcmp(&request[79], trailer, sizeof(trailer)) == 0;
}

#if KB7_ENABLE_MCU2 && KB7_MCU2_BOARD_PROFILE_VERIFIED
static bool wait_status(uint32_t mask, bool set, uint32_t *budget) {
    while (((KB7_MMIO32(SNC_MCU2_SERIAL_BASE + MCU2_STATUS) & mask) != 0U) != set) {
        if (budget == NULL || *budget == 0U) return false;
        --*budget;
    }
    return true;
}

static void finish_exchange(void) {
    const uintptr_t base = SNC_MCU2_SERIAL_BASE;
    uint32_t control = KB7_MMIO32(base + MCU2_CONTROL);
    control = (control & ~UINT32_C(0xc0)) | UINT32_C(0xc0);
    control |= KB7_BIT(19);
    KB7_MMIO32(base + MCU2_CONTROL) = control;
    kb7_dsb();
}
#endif

bool kb7_mcu2_init(void) {
#if KB7_ENABLE_MCU2 && KB7_MCU2_BOARD_PROFILE_VERIFIED
    const uintptr_t base = SNC_MCU2_SERIAL_BASE;
    if (!kb7_gpio_pinmux_known(MCU2_CS, MCU2_PIN_FUNCTION) ||
        !kb7_gpio_pinmux_known(MCU2_CLOCK, MCU2_PIN_FUNCTION) ||
        !kb7_gpio_pinmux_known(MCU2_MISO, MCU2_PIN_FUNCTION) ||
        !kb7_gpio_pinmux_known(MCU2_MOSI, MCU2_PIN_FUNCTION)) {
        return false;
    }
    kb7_gpio_configure(MCU2_CS, KB7_GPIO_OUTPUT, MCU2_PIN_FUNCTION,
                       KB7_GPIO_FLOATING);
    kb7_gpio_configure(MCU2_CLOCK, KB7_GPIO_OUTPUT, MCU2_PIN_FUNCTION,
                       KB7_GPIO_FLOATING);
    kb7_gpio_configure(MCU2_MISO, KB7_GPIO_INPUT, MCU2_PIN_FUNCTION,
                       KB7_GPIO_FLOATING);
    kb7_gpio_configure(MCU2_MOSI, KB7_GPIO_OUTPUT, MCU2_PIN_FUNCTION,
                       KB7_GPIO_FLOATING);
    kb7_gpio_configure(MCU2_READY_STATUS, KB7_GPIO_INPUT, 0U, KB7_GPIO_FLOATING);
    KB7_MMIO32(base + MCU2_DIVISOR) = 7U;
    uint32_t control = KB7_MMIO32(base + MCU2_CONTROL);
    control |= KB7_BIT(18);
    control &= ~(KB7_BIT(4) | KB7_BIT(3) | UINT32_C(0x0003ff00));
    control |= UINT32_C(0x000007c1);
    KB7_MMIO32(base + MCU2_CONTROL) = control;
    uint32_t configuration = KB7_MMIO32(base + MCU2_CONFIGURATION);
    configuration = (configuration & ~UINT32_C(0x07)) | UINT32_C(0x06);
    KB7_MMIO32(base + MCU2_CONFIGURATION) = configuration;
    KB7_MMIO32(base + MCU2_AUX_CONTROL) = 0U;
    kb7_dsb();
    const uint32_t control_mask = KB7_BIT(18) | UINT32_C(0x0003ff00) |
                                  KB7_BIT(4) | KB7_BIT(3) | UINT32_C(0xc1);
    const uint32_t expected_control = KB7_BIT(18) | UINT32_C(0x000007c1);
    return (KB7_MMIO32(base + MCU2_CONTROL) & control_mask) == expected_control &&
           (KB7_MMIO32(base + MCU2_CONFIGURATION) & UINT32_C(0x07)) == 6U &&
           KB7_MMIO32(base + MCU2_DIVISOR) == 7U &&
           KB7_MMIO32(base + MCU2_AUX_CONTROL) == 0U;
#else
    return false;
#endif
}

enum kb7_mcu2_result kb7_mcu2_exchange(const uint8_t request[KB7_MCU2_FRAME_SIZE],
                                       uint8_t response[KB7_MCU2_FRAME_SIZE]) {
    if (!kb7_mcu2_request_valid(request) || response == NULL) {
        return KB7_MCU2_BAD_FRAME;
    }
#if KB7_ENABLE_MCU2 && KB7_MCU2_BOARD_PROFILE_VERIFIED
    const uintptr_t base = SNC_MCU2_SERIAL_BASE;
    uint32_t budget = MCU2_TIMEOUT;
    uint32_t control = KB7_MMIO32(base + MCU2_CONTROL) & ~KB7_BIT(19);
    KB7_MMIO32(base + MCU2_CONTROL) = control;
    for (size_t index = 0U; index < KB7_MCU2_FRAME_SIZE; ++index) {
        if (!wait_status(KB7_BIT(0), true, &budget)) {
            finish_exchange();
            return KB7_MCU2_IO;
        }
        KB7_MMIO32(base + MCU2_DATA) = request[index];
        if (!wait_status(KB7_BIT(4), false, &budget) ||
            !wait_status(KB7_BIT(0), true, &budget) ||
            !wait_status(KB7_BIT(2), false, &budget)) {
            finish_exchange();
            return KB7_MCU2_IO;
        }
        response[index] = (uint8_t)KB7_MMIO32(base + MCU2_DATA);
    }
    finish_exchange();
    return KB7_MCU2_OK;
#else
    (void)response;
    return KB7_MCU2_UNSUPPORTED;
#endif
}

enum kb7_mcu2_result kb7_mcu2_decode_normalized(
    const uint8_t response[KB7_MCU2_FRAME_SIZE], uint8_t values[KB7_HALL_KEY_COUNT]) {
    if (response == NULL || values == NULL) return KB7_MCU2_BAD_FRAME;
    if (response[0] != 0xa3U) {
        return kb7_mcu2_command_supported(response[0]) || response[0] == 0xa5U ||
               response[0] == 0xaaU || response[0] == 0xffU
                   ? KB7_MCU2_BUSY : KB7_MCU2_BAD_FRAME;
    }
    if (response[1] != 0U) return KB7_MCU2_BUSY;
    kb7_memcpy(values, &response[2], KB7_HALL_KEY_COUNT);
    return KB7_MCU2_OK;
}

enum kb7_mcu2_result kb7_mcu2_read_normalized(uint8_t values[KB7_HALL_KEY_COUNT]) {
    uint8_t request[KB7_MCU2_FRAME_SIZE];
    uint8_t response[KB7_MCU2_FRAME_SIZE];
    kb7_mcu2_build_request(0xa3U, 0U, 0U, request);
    const enum kb7_mcu2_result result = kb7_mcu2_exchange(request, response);
    if (result != KB7_MCU2_OK) return result;
    return kb7_mcu2_decode_normalized(response, values);
}
