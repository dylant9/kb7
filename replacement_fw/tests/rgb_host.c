#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "kb7/drivers.h"
#include "kb7/regs.h"

#define TRANSACTION_MAX 32U
#define PACKET_MAX 194U

struct transaction {
    uint8_t bank;
    uint16_t length;
    uint8_t data[PACKET_MAX];
};

static struct transaction transactions[TRANSACTION_MAX];
static size_t transaction_count;
static int active_transaction = -1;
static uint32_t spi_control;
static uint32_t spi_status;

static void begin(uint8_t bank) {
    if (active_transaction >= 0 || transaction_count >= TRANSACTION_MAX) return;
    active_transaction = (int)transaction_count++;
    transactions[active_transaction].bank = bank;
    transactions[active_transaction].length = 0U;
}

static void end(uint8_t bank) {
    if (active_transaction >= 0 && transactions[active_transaction].bank == bank) {
        active_transaction = -1;
    }
}

uint32_t kb7_rgb_test_mmio_read(uintptr_t address) {
    if (address == SNC_SERIAL1_BASE) return spi_control;
    if (address == SNC_SERIAL1_BASE + 0x0cU) return spi_status;
    return 0U;
}

void kb7_rgb_test_mmio_write(uintptr_t address, uint32_t value) {
    if (address == SNC_SERIAL1_BASE) {
        const bool old_selected = (spi_control & KB7_BIT(19)) == 0U;
        const bool new_selected = (value & KB7_BIT(19)) == 0U;
        spi_control = value;
        if (!old_selected && new_selected) begin(1U);
        if (old_selected && !new_selected) end(1U);
    } else if (address == SNC_SERIAL1_BASE + 0x1cU && active_transaction >= 0) {
        struct transaction *current = &transactions[active_transaction];
        if (current->length < sizeof(current->data)) current->data[current->length++] = (uint8_t)value;
    }
}

uint32_t kb7_gpio_bank(uint8_t logical) { return logical / 16U; }
uint16_t kb7_gpio_mask(uint8_t logical) { return (uint16_t)(1U << (logical & 15U)); }
void kb7_gpio_configure(uint8_t logical, enum kb7_gpio_direction direction,
                        uint8_t function, enum kb7_gpio_pull pull) {
    (void)logical; (void)direction; (void)function; (void)pull;
}
void kb7_gpio_write(uint8_t logical, bool high) {
    if (logical != 35U) return;
    if (!high) begin(0U); else end(0U);
}
bool kb7_gpio_read(uint8_t logical) { (void)logical; return true; }
void kb7_delay_cycles(volatile uint32_t cycles) { (void)cycles; }
bool kb7_delay_us(uint32_t microseconds) { (void)microseconds; return true; }
bool kb7_delay_ms(uint32_t milliseconds) { (void)milliseconds; return true; }

static bool packet(size_t index, uint8_t bank, uint16_t length, uint8_t opcode) {
    return index < transaction_count && transactions[index].bank == bank &&
           transactions[index].length == length && transactions[index].data[0] == opcode;
}

int main(void) {
    spi_status = 0U;
    if (kb7_rgb_init()) return 1;

    memset(transactions, 0, sizeof(transactions));
    transaction_count = 0U;
    active_transaction = -1;
    spi_control = 0U;
    spi_status = KB7_BIT(0);
    if (!kb7_rgb_init() || transaction_count != 24U) return 2;
    if (!packet(0U, 0U, 3U, 0x23U) || transactions[0].data[1] != 0U ||
        transactions[0].data[2] != 0U) return 3;
    if (!packet(6U, 0U, 74U, 0x20U) || !packet(7U, 0U, 194U, 0x21U) ||
        !packet(8U, 0U, 14U, 0x24U) || !packet(10U, 0U, 26U, 0x20U)) return 4;
    if (!packet(11U, 1U, 3U, 0x23U) || !packet(17U, 1U, 74U, 0x20U) ||
        !packet(18U, 1U, 194U, 0x21U) || !packet(21U, 1U, 26U, 0x20U)) return 5;
    if (!packet(22U, 0U, 14U, 0x24U) || !packet(23U, 1U, 14U, 0x24U) ||
        transactions[22].data[2] != 102U) return 6;

    struct kb7_rgb colors[KB7_RGB_POSITION_COUNT];
    memset(colors, 0, sizeof(colors));
    colors[0] = (struct kb7_rgb){1U, 2U, 3U};
    colors[64] = (struct kb7_rgb){4U, 5U, 6U};
    colors[91] = (struct kb7_rgb){7U, 8U, 9U}; /* physically absent */
    kb7_rgb_show(colors);
    if (transaction_count != 26U || !packet(24U, 0U, 194U, 0x21U) ||
        !packet(25U, 1U, 146U, 0x21U)) return 7;
    if (transactions[24].data[2] != 1U || transactions[24].data[18] != 2U ||
        transactions[24].data[34] != 3U) return 8;
    if (transactions[25].data[2] != 4U || transactions[25].data[18] != 5U ||
        transactions[25].data[34] != 6U) return 9;
    if (kb7_rgb_present(91U) || !kb7_rgb_present(90U) || kb7_rgb_present(112U)) return 10;
    return 0;
}
