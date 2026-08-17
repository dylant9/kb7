#include "kb7/drivers.h"
#include "kb7/regs.h"

#define TOUCH_SCL 0U
#define TOUCH_SDA 1U
#define TOUCH_IRQ 12U
#define TOUCH_RESET 26U
#define TOUCH_ADDRESS_WRITE 0xaaU
#define TOUCH_ADDRESS_READ 0xabU

static void i2c_delay(void) { kb7_delay_cycles(32U); }

static void sda_release(void) {
    kb7_gpio_configure(TOUCH_SDA, KB7_GPIO_INPUT, 0U, KB7_GPIO_PULL_UP);
}

static void sda_low(void) {
    kb7_gpio_write(TOUCH_SDA, false);
    kb7_gpio_configure(TOUCH_SDA, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
}

static void i2c_start(void) {
    sda_release();
    kb7_gpio_write(TOUCH_SCL, true);
    i2c_delay();
    sda_low();
    i2c_delay();
    kb7_gpio_write(TOUCH_SCL, false);
}

static void i2c_stop(void) {
    sda_low();
    kb7_gpio_write(TOUCH_SCL, true);
    i2c_delay();
    sda_release();
    i2c_delay();
}

static bool i2c_write(uint8_t value) {
    for (uint8_t mask = 0x80U; mask != 0U; mask >>= 1U) {
        if ((value & mask) != 0U) {
            sda_release();
        } else {
            sda_low();
        }
        kb7_gpio_write(TOUCH_SCL, true);
        i2c_delay();
        kb7_gpio_write(TOUCH_SCL, false);
    }
    sda_release();
    kb7_gpio_write(TOUCH_SCL, true);
    i2c_delay();
    const bool ack = !kb7_gpio_read(TOUCH_SDA);
    kb7_gpio_write(TOUCH_SCL, false);
    return ack;
}

static uint8_t i2c_read(bool acknowledge) {
    uint8_t value = 0U;
    sda_release();
    for (uint8_t bit = 0U; bit < 8U; ++bit) {
        value <<= 1U;
        kb7_gpio_write(TOUCH_SCL, true);
        i2c_delay();
        value |= kb7_gpio_read(TOUCH_SDA) ? 1U : 0U;
        kb7_gpio_write(TOUCH_SCL, false);
    }
    if (acknowledge) {
        sda_low();
    }
    kb7_gpio_write(TOUCH_SCL, true);
    i2c_delay();
    kb7_gpio_write(TOUCH_SCL, false);
    sda_release();
    return value;
}

static bool touch_read_register(uint16_t address, uint8_t *data, size_t length) {
    i2c_start();
    if (!i2c_write(TOUCH_ADDRESS_WRITE) || !i2c_write((uint8_t)(address >> 8U)) ||
        !i2c_write((uint8_t)address)) {
        i2c_stop();
        return false;
    }
    i2c_stop();
    i2c_start();
    if (!i2c_write(TOUCH_ADDRESS_READ)) {
        i2c_stop();
        return false;
    }
    for (size_t index = 0; index < length; ++index) {
        data[index] = i2c_read(index + 1U != length);
    }
    i2c_stop();
    return true;
}

bool kb7_touch_init(void) {
    kb7_gpio_configure(TOUCH_SCL, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
    kb7_gpio_configure(TOUCH_IRQ, KB7_GPIO_INPUT, 0U, KB7_GPIO_PULL_UP);
    kb7_gpio_configure(TOUCH_RESET, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
    sda_release();
    kb7_gpio_write(TOUCH_SCL, true);
    kb7_gpio_write(TOUCH_RESET, false);
    kb7_delay_cycles(50000U);
    kb7_gpio_write(TOUCH_RESET, true);
    kb7_delay_cycles(300000U);
    uint8_t identity = 0U;
    return touch_read_register(0x00f4U, &identity, 1U) && identity != 0U && identity != 0xffU;
}

bool kb7_touch_read(struct kb7_touch_frame *frame) {
    if (frame == NULL) {
        return false;
    }
    frame->count = 0U;
    if (kb7_gpio_read(TOUCH_IRQ)) {
        return true;
    }
    for (uint8_t slot = 0U; slot < 10U; ++slot) {
        uint8_t record[7];
        if (!touch_read_register((uint16_t)(0x14U + slot * 7U), record, sizeof(record))) {
            frame->count = 0U;
            return false;
        }
        if ((record[0] & 0x80U) == 0U) {
            continue;
        }
        const uint16_t x = (uint16_t)(((uint16_t)(record[0] & 0x3fU) << 8U) | record[1]);
        const uint16_t y = (uint16_t)(((uint16_t)(record[2] & 0x3fU) << 8U) | record[3]);
        if (x >= KB7_DISPLAY_WIDTH || y >= KB7_DISPLAY_HEIGHT) {
            continue;
        }
        struct kb7_touch_point *point = &frame->points[frame->count++];
        point->x = x;
        point->y = y;
        point->id = slot;
        point->pressure = record[4];
    }
    return true;
}
