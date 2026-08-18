#include "kb7/drivers.h"
#include "kb7/regs.h"

/*
 * Two 192-channel LED drivers share SPI1.  The first has a software-controlled
 * active-low select on P2.3; the second uses SPI1's active-low select bit.
 * P2.0/P2.1 and P3.10 reproduce the reset/power sequencing observed at boot.
 */
#define RGB_CONTROL0 32U
#define RGB_CONTROL1 33U
#define RGB_BANK0_SELECT 35U
#define RGB_POWER_RESET 58U
#define RGB_BANK1_SELECT 60U

#define RGB_SPI_CONTROL UINT32_C(0x00)
#define RGB_SPI_DIVISOR UINT32_C(0x08)
#define RGB_SPI_STATUS UINT32_C(0x0c)
#define RGB_SPI_DATA UINT32_C(0x1c)
#define RGB_SPI_BANK1_SELECT KB7_BIT(19)
#define RGB_SPI_READY KB7_BIT(0)
#define RGB_SPI_BUSY KB7_BIT(4)
#define RGB_TIMEOUT UINT32_C(100000)
#define RGB_MAX_PACKET 194U

#ifdef KB7_HOST_TEST
uint32_t kb7_rgb_test_mmio_read(uintptr_t address);
void kb7_rgb_test_mmio_write(uintptr_t address, uint32_t value);
#define RGB_READ(address) kb7_rgb_test_mmio_read(address)
#define RGB_WRITE(address, value) kb7_rgb_test_mmio_write((address), (value))
#else
#define RGB_READ(address) KB7_MMIO32(address)
#define RGB_WRITE(address, value) (KB7_MMIO32(address) = (value))
#endif

static bool rgb_ready;
static uint8_t brightness_percent = 40U;

/* 0xfe marks driver outputs which have no populated RGB package. */
static const uint8_t topology_bank0[64] = {
    1,3,4,5,6,8,9,10,11,12,13,14,14,14,1,2,
    3,4,5,6,7,8,9,10,11,12,13,14,1,2,3,4,
    5,6,7,8,9,10,11,12,13,14,1,2,3,4,5,6,
    7,8,9,10,11,12,13,14,0,1,2,3,4,5,6,7,
};
static const uint8_t topology_bank1[48] = {
    8,9,10,11,12,13,16,0,1,2,3,6,8,9,10,11,
    12,13,15,16,18,3,4,7,9,10,11,0xfe,0xfe,0xfe,0xfe,0xfe,
    0,1,3,5,7,10,11,13,15,18,0xfe,0xfe,0xfe,0xfe,0xfe,0xfe,
};

static bool spi_wait(uint32_t mask, bool set) {
    uint32_t timeout = RGB_TIMEOUT;
    while (((RGB_READ(SNC_SERIAL1_BASE + RGB_SPI_STATUS) & mask) != 0U) != set) {
        if (timeout == 0U) return false;
        --timeout;
    }
    return true;
}

static bool spi_byte(uint8_t byte) {
    if (!spi_wait(RGB_SPI_READY, true)) return false;
    RGB_WRITE(SNC_SERIAL1_BASE + RGB_SPI_DATA, byte);
    return true;
}

static void select_bank(uint8_t bank, bool selected) {
    if (bank == 0U) {
        kb7_gpio_write(RGB_BANK0_SELECT, !selected);
        return;
    }
    uint32_t control = RGB_READ(SNC_SERIAL1_BASE + RGB_SPI_CONTROL);
    if (selected) {
        control &= ~RGB_SPI_BANK1_SELECT;
    } else {
        control |= RGB_SPI_BANK1_SELECT;
    }
    RGB_WRITE(SNC_SERIAL1_BASE + RGB_SPI_CONTROL, control);
}

static bool send_bank(uint8_t bank, const uint8_t *bytes, size_t length) {
    if (bank > 1U || bytes == NULL || length == 0U || length > RGB_MAX_PACKET) {
        return false;
    }
    select_bank(bank, true);
    for (size_t index = 0U; index < length; ++index) {
        if (!spi_byte(bytes[index])) {
            select_bank(bank, false);
            return false;
        }
    }
    const bool complete = spi_wait(RGB_SPI_READY, true) && spi_wait(RGB_SPI_BUSY, false);
    select_bank(bank, false);
    return complete;
}

static bool register_write(uint8_t bank, uint8_t address, uint8_t value) {
    const uint8_t command[] = {0x23U, address, value};
    return send_bank(bank, command, sizeof(command));
}

static bool clear_command(uint8_t bank, uint8_t opcode, size_t length) {
    uint8_t packet[RGB_MAX_PACKET];
    if (length < 2U || length > sizeof(packet)) return false;
    kb7_memset(packet, 0, length);
    packet[0] = opcode;
    return send_bank(bank, packet, length);
}

static bool enable_channels(uint8_t bank) {
    uint8_t command[26];
    command[0] = 0x20U;
    command[1] = 0U;
    kb7_memset(&command[2], 0xff, sizeof(command) - 2U);
    return send_bank(bank, command, sizeof(command));
}

static bool initialize_bank(uint8_t bank) {
    return register_write(bank, 0x00U, 0x00U) &&
           register_write(bank, 0x13U, 0xaaU) &&
           register_write(bank, 0x14U, 0x00U) &&
           register_write(bank, 0x15U, 0x04U) &&
           register_write(bank, 0x16U, 0xc0U) &&
           register_write(bank, 0x1aU, 0x00U) &&
           clear_command(bank, 0x20U, 74U) &&
           clear_command(bank, 0x21U, 194U) &&
           clear_command(bank, 0x24U, 14U) &&
           register_write(bank, 0x00U, 0x01U) &&
           enable_channels(bank);
}

bool kb7_rgb_present(uint16_t position) {
    if (position < 64U) return topology_bank0[position] != 0xfeU;
    if (position < KB7_RGB_POSITION_COUNT) {
        return topology_bank1[position - 64U] != 0xfeU;
    }
    return false;
}

bool kb7_rgb_init(void) {
    rgb_ready = false;
    kb7_gpio_configure(RGB_POWER_RESET, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_PULL_UP);
    kb7_gpio_configure(RGB_BANK0_SELECT, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_PULL_UP);
    kb7_gpio_configure(RGB_BANK1_SELECT, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_PULL_UP);
    kb7_gpio_configure(RGB_CONTROL0, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_PULL_UP);
    kb7_gpio_configure(RGB_CONTROL1, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_PULL_UP);

    kb7_gpio_write(RGB_BANK0_SELECT, true);
    kb7_gpio_write(RGB_POWER_RESET, false);
    if (!kb7_delay_ms(10U)) return false;
    kb7_gpio_write(RGB_CONTROL0, true);
    kb7_gpio_write(RGB_CONTROL1, false);
    if (!kb7_delay_ms(2U)) return false;
    kb7_gpio_write(RGB_CONTROL1, true);
    if (!kb7_delay_ms(2U)) return false;
    kb7_gpio_write(RGB_CONTROL0, false);
    if (!kb7_delay_ms(2U)) return false;
    kb7_gpio_write(RGB_CONTROL0, true);
    if (!kb7_delay_ms(30U)) return false;

    /* Reconstructed final register state of the stock SPI1 configuration. */
    RGB_WRITE(SNC_SERIAL1_BASE + RGB_SPI_CONTROL, UINT32_C(0x000c07c5));
    RGB_WRITE(SNC_SERIAL1_BASE + RGB_SPI_DIVISOR, 39U);
    select_bank(0U, false);
    select_bank(1U, false);

    if (!initialize_bank(0U) || !kb7_delay_ms(100U) || !initialize_bank(1U)) {
        return false;
    }
    rgb_ready = true;
    kb7_rgb_set_brightness(brightness_percent);
    return true;
}

void kb7_rgb_set_brightness(uint8_t percent) {
    brightness_percent = percent > 100U ? 100U : percent;
    if (!rgb_ready) return;

    uint8_t command[14] = {0x24U, 0x00U};
    const uint8_t scaled = (uint8_t)(((uint16_t)brightness_percent * 255U + 50U) / 100U);
    for (size_t index = 2U; index < sizeof(command); ++index) command[index] = scaled;
    if (brightness_percent == 100U) {
        for (size_t index = 8U; index < sizeof(command); ++index) command[index] = 0xffU;
    }
    if (!send_bank(0U, command, sizeof(command)) ||
        !send_bank(1U, command, sizeof(command))) {
        rgb_ready = false;
    }
}

void kb7_rgb_show(const struct kb7_rgb colors[KB7_RGB_POSITION_COUNT]) {
    if (!rgb_ready || colors == NULL) return;

    uint8_t packet[RGB_MAX_PACKET];
    packet[0] = 0x21U;
    packet[1] = 0x00U;
    for (uint8_t bank = 0U; bank < 2U; ++bank) {
        const uint16_t count = bank == 0U ? 64U : 48U;
        kb7_memset(&packet[2], 0, (size_t)count * 3U);
        for (uint16_t position = 0U; position < count; ++position) {
            const uint16_t global = (uint16_t)(position + (bank == 0U ? 0U : 64U));
            if (!kb7_rgb_present(global)) continue;
            const uint16_t base = (uint16_t)(2U + (position / 16U) * 48U);
            const uint16_t lane = position & 15U;
            packet[base + lane] = colors[global].red;
            packet[base + 16U + lane] = colors[global].green;
            packet[base + 32U + lane] = colors[global].blue;
        }
        if (!send_bank(bank, packet, (size_t)(2U + count * 3U))) {
            rgb_ready = false;
            return;
        }
    }
}
