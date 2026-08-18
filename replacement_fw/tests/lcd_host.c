#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "kb7/drivers.h"
#include "kb7/regs.h"

#define FRAME_MAX 512U
#define DELAY_MAX 16U

struct panel_frame { bool data; uint8_t value; };
static struct panel_frame frames[FRAME_MAX];
static size_t frame_count;
static uint16_t shift;
static uint8_t shift_count;
static bool panel_selected;
static bool panel_data;
static bool reset_levels[8];
static size_t reset_count;
static uint32_t delays[DELAY_MAX];
static size_t delay_count;
static uint32_t registers[0x100U / sizeof(uint32_t)];
static bool table_busy;
static uint8_t pixel_mux_count;
static bool pixel_pinmux_known;

uint32_t kb7_lcd_test_mmio_read(uintptr_t address) {
    if (address < SNC_LCDC_BASE || address >= SNC_LCDC_BASE + sizeof(registers)) return 0U;
    const size_t index = (size_t)(address - SNC_LCDC_BASE) / sizeof(uint32_t);
    if (address == SNC_LCDC_BASE + 0x54U && table_busy) {
        table_busy = false;
        registers[index] &= ~KB7_BIT(15);
    }
    return registers[index];
}

void kb7_lcd_test_mmio_write(uintptr_t address, uint32_t value) {
    if (address < SNC_LCDC_BASE || address >= SNC_LCDC_BASE + sizeof(registers)) return;
    const size_t index = (size_t)(address - SNC_LCDC_BASE) / sizeof(uint32_t);
    registers[index] = value;
    if (address == SNC_LCDC_BASE + 0x54U && (value & KB7_BIT(15)) != 0U) table_busy = true;
}

uint32_t kb7_gpio_bank(uint8_t logical) { return logical / 16U; }
uint16_t kb7_gpio_mask(uint8_t logical) { return (uint16_t)(1U << (logical & 15U)); }
void kb7_gpio_configure(uint8_t logical, enum kb7_gpio_direction direction,
                        uint8_t function, enum kb7_gpio_pull pull) {
    (void)direction; (void)pull;
    if (logical >= 36U && logical <= 57U && function == 1U) ++pixel_mux_count;
}
void kb7_gpio_write(uint8_t logical, bool high) {
    if (logical == 4U && reset_count < sizeof(reset_levels)) reset_levels[reset_count++] = high;
    if (logical == 5U) panel_data = high;
    if (logical == 67U) {
        panel_selected = !high;
        if (panel_selected) { shift = 0U; shift_count = 0U; }
    }
    if (logical == 66U && high && panel_selected) {
        shift = (uint16_t)((shift << 1U) | (panel_data ? 1U : 0U));
        ++shift_count;
        if (shift_count == 9U && frame_count < FRAME_MAX) {
            frames[frame_count].data = (shift & 0x100U) != 0U;
            frames[frame_count].value = (uint8_t)shift;
            ++frame_count;
        }
    }
}
bool kb7_gpio_read(uint8_t logical) { (void)logical; return false; }
bool kb7_gpio_pinmux_known(uint8_t logical, uint8_t function) {
    return pixel_pinmux_known && logical >= 36U && logical <= 57U && function == 1U;
}
void kb7_delay_cycles(volatile uint32_t cycles) { (void)cycles; }
bool kb7_delay_us(uint32_t microseconds) { (void)microseconds; return true; }
bool kb7_delay_ms(uint32_t milliseconds) {
    if (delay_count < DELAY_MAX) delays[delay_count++] = milliseconds;
    return true;
}

int main(void) {
    kb7_panel_init();
    const uint32_t expected_delays[] = {100U, 120U, 120U, 100U, 120U, 20U};
    if (delay_count != sizeof(expected_delays) / sizeof(expected_delays[0]) ||
        memcmp(delays, expected_delays, sizeof(expected_delays)) != 0) return 1;
    if (reset_count != 3U || !reset_levels[0] || reset_levels[1] || !reset_levels[2]) return 2;
    if (frame_count != 415U) return 3;
    const struct panel_frame tail[] = {
        {false, 0x35U}, {true, 0x00U}, {false, 0x62U},
        {true, 0x00U}, {false, 0x11U}, {false, 0x29U},
    };
    for (size_t index = 0U; index < sizeof(tail) / sizeof(tail[0]); ++index) {
        if (frames[frame_count - 6U + index].data != tail[index].data ||
            frames[frame_count - 6U + index].value != tail[index].value) return 4;
    }

    if (kb7_lcdc_init(KB7_FRAMEBUFFER_A) || pixel_mux_count != 0U ||
        registers[0x00U / 4U] != 0U) return 5;
    pixel_pinmux_known = true;
    if (!kb7_lcdc_init(KB7_FRAMEBUFFER_A) || pixel_mux_count != 22U) return 10;
    if (registers[0x20U / 4U] != (KB7_FRAMEBUFFER_A & 0xffffU) ||
        registers[0x24U / 4U] != (KB7_FRAMEBUFFER_A >> 16U)) return 6;
    if (registers[0xe8U / 4U] != KB7_DISPLAY_WIDTH ||
        registers[0xecU / 4U] != KB7_DISPLAY_HEIGHT) return 7;
    if ((registers[0x00U / 4U] & (KB7_BIT(0) | KB7_BIT(4))) == 0U ||
        (registers[0xb0U / 4U] & 3U) != 3U) return 8;
    kb7_lcdc_set_framebuffer(UINT32_C(0x30000000));
    if (registers[0x20U / 4U] != (KB7_FRAMEBUFFER_A & 0xffffU)) return 9;
    return 0;
}
