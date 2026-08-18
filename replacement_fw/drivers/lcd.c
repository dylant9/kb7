#include "kb7/drivers.h"
#include "kb7/platform_boot.h"
#include "kb7/regs.h"

/* KB7 panel side-band wiring recovered independently from the stock image. */
#define PANEL_RESET 4U
#define PANEL_DATA 5U
#define PANEL_CLOCK 66U
#define PANEL_CHIP_SELECT 67U

#define PPU_BUILD_TIMEOUT UINT32_C(100000)

#ifdef KB7_HOST_TEST
uint32_t kb7_lcd_test_mmio_read(uintptr_t address);
void kb7_lcd_test_mmio_write(uintptr_t address, uint32_t value);
#define LCD_READ(address) kb7_lcd_test_mmio_read(address)
#define LCD_WRITE(address, value) kb7_lcd_test_mmio_write((address), (value))
#else
#define LCD_READ(address) KB7_MMIO32(address)
#define LCD_WRITE(address, value) (KB7_MMIO32(address) = (value))
#endif

struct panel_command {
    uint8_t opcode;
    uint8_t length;
    const uint8_t *payload;
};

static bool panel_ready;

static const uint8_t command_99_a[] = {0x71U, 0x02U, 0xa2U};
static const uint8_t command_99_b[] = {0x71U, 0x02U, 0xa3U};
static const uint8_t command_99_c[] = {0x71U, 0x02U, 0xa4U};
static const uint8_t command_b0[] = {0x22U, 0x57U, 0x1eU, 0x61U, 0x2fU, 0x57U, 0x61U};
static const uint8_t command_b7[] = {0x64U, 0x64U};
static const uint8_t command_bf[] = {0xb4U, 0xb4U};
static const uint8_t command_c8_a[] = {
    0x00U,0x00U,0x0fU,0x1cU,0x34U,0x00U,0x60U,0x03U,0xa0U,0x06U,
    0x10U,0xfeU,0x06U,0x74U,0x03U,0x21U,0xc4U,0x00U,0x08U,0x00U,
    0x22U,0x46U,0x0fU,0x8fU,0x0aU,0x32U,0xf2U,0x0cU,0x42U,0x0cU,
    0xf3U,0x80U,0x00U,0xabU,0xc0U,0x03U,0xc4U,
};
static const uint8_t command_c8_b[] = {
    0x00U,0x00U,0x13U,0x24U,0x44U,0x00U,0x74U,0x03U,0xb8U,0x04U,
    0x11U,0x16U,0x08U,0x86U,0x04U,0x21U,0xd3U,0x02U,0x10U,0x0fU,
    0x22U,0x4dU,0x0eU,0x90U,0x09U,0x32U,0xf0U,0x0bU,0x40U,0x0eU,
    0xf3U,0x7dU,0x0eU,0xa9U,0xbfU,0x03U,0xc4U,
};
static const uint8_t command_d7[] = {0x10U,0x0cU,0x36U,0x19U,0x90U,0x90U};
static const uint8_t command_a3[] = {
    0x51U,0x03U,0x80U,0xcfU,0x44U,0x00U,0x00U,0x00U,0x00U,0x04U,
    0x78U,0x78U,0x00U,0x1aU,0x00U,0x45U,0x05U,0x00U,0x00U,0x00U,
    0x00U,0x46U,0x00U,0x00U,0x02U,0x20U,0x52U,0x00U,0x05U,0x00U,
    0x00U,0xffU,
};
static const uint8_t command_a6[] = {
    0x02U,0x00U,0x24U,0x55U,0x35U,0x00U,0x38U,0x00U,0x78U,0x78U,
    0x00U,0x24U,0x55U,0x36U,0x00U,0x37U,0x00U,0x78U,0x78U,0x02U,
    0xacU,0x51U,0x3aU,0x00U,0x00U,0x00U,0x78U,0x78U,0x03U,0xacU,
    0x21U,0x00U,0x04U,0x00U,0x00U,0x78U,0x78U,0x3eU,0x00U,0x06U,
    0x00U,0x00U,0x00U,0x00U,
};
static const uint8_t command_a7[] = {
    0x19U,0x19U,0x00U,0x64U,0x40U,0x07U,0x16U,0x40U,0x00U,0x04U,
    0x03U,0x78U,0x78U,0x00U,0x64U,0x40U,0x25U,0x34U,0x00U,0x00U,
    0x02U,0x01U,0x78U,0x78U,0x00U,0x64U,0x40U,0x4bU,0x5aU,0x00U,
    0x00U,0x02U,0x01U,0x78U,0x78U,0x00U,0x24U,0x40U,0x69U,0x78U,
    0x00U,0x00U,0x00U,0x00U,0x78U,0x78U,0x00U,0x44U,
};
static const uint8_t command_ac[] = {
    0x08U,0x0aU,0x11U,0x00U,0x13U,0x03U,0x1bU,0x18U,0x06U,0x1aU,
    0x19U,0x1bU,0x1bU,0x1bU,0x18U,0x1bU,0x09U,0x0bU,0x10U,0x02U,
    0x12U,0x01U,0x1bU,0x18U,0x06U,0x1aU,0x19U,0x1bU,0x1bU,0x1bU,
    0x18U,0x1bU,0xffU,0x67U,0xffU,0x67U,0x00U,
};
static const uint8_t command_ad[] = {0xccU,0x40U,0x46U,0x11U,0x04U,0x78U,0x78U};
static const uint8_t command_e8[] = {
    0x30U,0x07U,0x00U,0x94U,0x94U,0x9cU,0x00U,0xe2U,
    0x04U,0x00U,0x00U,0x00U,0x00U,0xefU,
};
static const uint8_t command_e7[] = {
    0x8bU,0x3cU,0x00U,0x0cU,0xf0U,0x5dU,0x00U,0x5dU,0x00U,0x5dU,
    0x00U,0x5dU,0x00U,0xffU,0x00U,0x08U,0x7bU,0x00U,0x00U,0xc8U,
    0x6aU,0x5aU,0x08U,0x1aU,0x3cU,0x00U,0x81U,0x01U,0xccU,0x01U,
    0x7fU,0xf0U,0x22U,
};

static const struct panel_command initialization_commands[] = {
    {0x10U, 0U, NULL}, {0x28U, 0U, NULL},
    {0x99U, sizeof(command_99_a), command_99_a},
    {0x99U, sizeof(command_99_b), command_99_b},
    {0x99U, sizeof(command_99_c), command_99_c},
    {0xb0U, sizeof(command_b0), command_b0},
    {0xb7U, sizeof(command_b7), command_b7},
    {0xbfU, sizeof(command_bf), command_bf},
    {0xc8U, sizeof(command_c8_a), command_c8_a},
    {0xc9U, sizeof(command_c8_a), command_c8_a},
    {0xc8U, sizeof(command_c8_b), command_c8_b},
    {0xc9U, sizeof(command_c8_b), command_c8_b},
    {0xd7U, sizeof(command_d7), command_d7},
    {0xa3U, sizeof(command_a3), command_a3},
    {0xa6U, sizeof(command_a6), command_a6},
    {0xa7U, sizeof(command_a7), command_a7},
    {0xacU, sizeof(command_ac), command_ac},
    {0xadU, sizeof(command_ad), command_ad},
    {0xe8U, sizeof(command_e8), command_e8},
    {0xe7U, sizeof(command_e7), command_e7},
};

static bool framebuffer_valid(uintptr_t framebuffer) {
    return framebuffer == KB7_FRAMEBUFFER_A || framebuffer == KB7_FRAMEBUFFER_B;
}

static void panel_bit(bool high) {
    kb7_gpio_write(PANEL_CLOCK, false);
    kb7_gpio_write(PANEL_DATA, high);
    kb7_delay_cycles(4U);
    kb7_gpio_write(PANEL_CLOCK, true);
}

static void panel_write(bool data, uint8_t value) {
    kb7_gpio_write(PANEL_CHIP_SELECT, false);
    panel_bit(data);
    for (uint8_t bit = 0U; bit < 8U; ++bit) {
        panel_bit((value & 0x80U) != 0U);
        value <<= 1U;
    }
    kb7_gpio_write(PANEL_CLOCK, false);
    kb7_gpio_write(PANEL_CHIP_SELECT, true);
}

static void panel_command(const struct panel_command *command) {
    panel_write(false, command->opcode);
    for (uint8_t index = 0U; index < command->length; ++index) {
        panel_write(true, command->payload[index]);
    }
}

void kb7_panel_init(void) {
    panel_ready = false;
    kb7_gpio_configure(PANEL_RESET, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
    kb7_gpio_configure(PANEL_DATA, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
    kb7_gpio_configure(PANEL_CLOCK, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
    kb7_gpio_configure(PANEL_CHIP_SELECT, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
    kb7_gpio_write(PANEL_CHIP_SELECT, true);
    kb7_gpio_write(PANEL_RESET, true);
    if (!kb7_delay_ms(100U)) return;
    kb7_gpio_write(PANEL_RESET, false);
    if (!kb7_delay_ms(120U)) return;
    kb7_gpio_write(PANEL_RESET, true);
    if (!kb7_delay_ms(120U)) return;

    for (size_t index = 0U; index < KB7_ARRAY_LEN(initialization_commands); ++index) {
        panel_command(&initialization_commands[index]);
    }

    /* Stock waits before TE/configuration, then performs sleep-out and display-on. */
    if (!kb7_delay_ms(100U)) return;
    static const uint8_t zero = 0U;
    const struct panel_command tearing = {0x35U, 1U, &zero};
    const struct panel_command vendor = {0x62U, 1U, &zero};
    panel_command(&tearing);
    panel_command(&vendor);
    panel_write(false, 0x11U);
    if (!kb7_delay_ms(120U)) return;
    panel_write(false, 0x29U);
    if (!kb7_delay_ms(20U)) return;
    panel_ready = true;
}

void kb7_lcdc_set_framebuffer(uintptr_t framebuffer) {
    if (!framebuffer_valid(framebuffer)) return;
    LCD_WRITE(SNC_LCDC_BASE + 0x20U, (uint32_t)framebuffer & UINT32_C(0xffff));
    LCD_WRITE(SNC_LCDC_BASE + 0x24U, (uint32_t)framebuffer >> 16U);
    kb7_dsb();
}

static bool build_line_tables(uintptr_t framebuffer) {
    for (uint32_t offset = 0U; offset <= UINT32_C(0x1600); offset += UINT32_C(0x200)) {
        LCD_WRITE(SNC_LCDC_BASE + 0x58U, (uint32_t)framebuffer & UINT32_C(0xffff));
        LCD_WRITE(SNC_LCDC_BASE + 0x5cU, (uint32_t)framebuffer >> 16U);
        LCD_WRITE(SNC_LCDC_BASE + 0x60U, offset);
        LCD_WRITE(SNC_LCDC_BASE + 0x64U, UINT32_C(0x4005));
        LCD_WRITE(SNC_LCDC_BASE + 0x68U, UINT32_C(0xff));
        LCD_WRITE(SNC_LCDC_BASE + 0x54U, LCD_READ(SNC_LCDC_BASE + 0x54U) | KB7_BIT(15));
        uint32_t timeout = PPU_BUILD_TIMEOUT;
        while ((LCD_READ(SNC_LCDC_BASE + 0x54U) & KB7_BIT(15)) != 0U) {
            if (timeout == 0U) return false;
            --timeout;
        }
    }
    return true;
}

bool kb7_lcdc_init(uintptr_t framebuffer) {
    if (!panel_ready || !framebuffer_valid(framebuffer)) return false;

    /* P2.4..P3.9 form the datasheet-defined 18-bit TFT bus in pinmux mode 1. */
    for (uint8_t pin = 36U; pin <= 57U; ++pin) {
        if (!kb7_gpio_pinmux_known(pin, 1U)) return false;
    }
    for (uint8_t pin = 36U; pin <= 57U; ++pin) {
        kb7_gpio_configure(pin, KB7_GPIO_OUTPUT, 1U, KB7_GPIO_FLOATING);
    }

    LCD_WRITE(SNC_LCDC_BASE + 0x00U,
              LCD_READ(SNC_LCDC_BASE + 0x00U) | KB7_BIT(7) | KB7_BIT(9));
    LCD_WRITE(SNC_LCDC_BASE + 0xacU, 0U);
    uint32_t bus = LCD_READ(SNC_LCDC_BASE + 0xb8U);
    bus &= ~(KB7_BIT(0) | UINT32_C(0x000006c0));
    bus |= UINT32_C(0x0000f800);
    LCD_WRITE(SNC_LCDC_BASE + 0xb8U, bus);
    LCD_WRITE(SNC_LCDC_BASE + 0xbcU, 5U);
    LCD_WRITE(SNC_LCDC_BASE + 0x94U, UINT32_C(0x10));
    LCD_WRITE(SNC_LCDC_BASE + 0x98U, 0U);
    LCD_WRITE(SNC_LCDC_BASE + 0x9cU, UINT32_C(0x0a));
    LCD_WRITE(SNC_LCDC_BASE + 0xa0U, UINT32_C(0x118));
    LCD_WRITE(SNC_LCDC_BASE + 0xa4U, 4U);
    LCD_WRITE(SNC_LCDC_BASE + 0xa8U, UINT32_C(0x26c0));
    LCD_WRITE(SNC_LCDC_BASE + 0xe8U, KB7_DISPLAY_WIDTH);
    LCD_WRITE(SNC_LCDC_BASE + 0xecU, KB7_DISPLAY_HEIGHT);
    LCD_WRITE(SNC_LCDC_BASE + 0x04U, 0U);
    LCD_WRITE(SNC_LCDC_BASE + 0x08U, 0U);
    LCD_WRITE(SNC_LCDC_BASE + 0xd8U, 0U);
    LCD_WRITE(SNC_LCDC_BASE + 0xdcU, 0U);
    LCD_WRITE(SNC_LCDC_BASE + 0xe0U, UINT32_MAX);
    LCD_WRITE(SNC_LCDC_BASE + 0xe4U, UINT32_MAX);
    LCD_WRITE(SNC_LCDC_BASE + 0x70U, UINT32_C(0xffff));
    LCD_WRITE(SNC_LCDC_BASE + 0x14U, UINT32_C(0x40051400));
    LCD_WRITE(SNC_LCDC_BASE + 0x18U, SNC_LCDC_TABLE_A);
    uint32_t format = LCD_READ(SNC_LCDC_BASE + 0x10U);
    format = (format & ~UINT32_C(0x300)) | UINT32_C(0x209);
    LCD_WRITE(SNC_LCDC_BASE + 0x10U, format);
    uint32_t channel = LCD_READ(SNC_LCDC_BASE + 0x34U);
    LCD_WRITE(SNC_LCDC_BASE + 0x34U, (channel & ~UINT32_C(0x300)) | UINT32_C(0x200));
    kb7_lcdc_set_framebuffer(framebuffer);
    if (!build_line_tables(framebuffer)) return false;
    LCD_WRITE(SNC_LCDC_BASE + 0x54U, LCD_READ(SNC_LCDC_BASE + 0x54U) | 1U);
    LCD_WRITE(SNC_LCDC_BASE + 0x90U, LCD_READ(SNC_LCDC_BASE + 0x90U) | UINT32_C(0x30));
    LCD_WRITE(SNC_LCDC_BASE + 0xb0U,
              LCD_READ(SNC_LCDC_BASE + 0xb0U) | KB7_BIT(0) | KB7_BIT(1));
    LCD_WRITE(SNC_LCDC_BASE + 0x00U,
              LCD_READ(SNC_LCDC_BASE + 0x00U) | KB7_BIT(0) | KB7_BIT(4));
    kb7_dsb();
    return true;
}

void kb7_lcdc_fill(uintptr_t framebuffer, uint16_t color) {
    if (!framebuffer_valid(framebuffer)) return;
    volatile uint16_t *const pixels = (volatile uint16_t *)framebuffer;
    for (uint32_t y = 0U; y < KB7_DISPLAY_HEIGHT; ++y) {
        const uint32_t row = y * KB7_FRAMEBUFFER_STRIDE_PIXELS;
        for (uint32_t x = 0U; x < KB7_FRAMEBUFFER_STRIDE_PIXELS; ++x) {
            pixels[row + x] = x < KB7_DISPLAY_WIDTH ? color : 0U;
        }
    }
    kb7_dsb();
}
