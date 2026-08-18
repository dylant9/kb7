#include "kb7/drivers.h"
#include "kb7/config.h"
#include "kb7/regs.h"

#define TOUCH_SCL 0U
#define TOUCH_SDA 1U
#define TOUCH_IRQ 12U
#define TOUCH_RESET 26U
#define TOUCH_ADDRESS_WRITE 0xaaU
#define TOUCH_ADDRESS_READ 0xabU
#define TOUCH_STRETCH_TIMEOUT UINT32_C(10000)
#define TOUCH_MAX_CONTACTS 10U

bool kb7_touch_geometry_supported(uint16_t maximum_x, uint16_t maximum_y) {
    /* No rotation/mirroring transform is yet proven, so accept portrait only. */
    return (maximum_x == KB7_DISPLAY_WIDTH || maximum_x + 1U == KB7_DISPLAY_WIDTH) &&
           (maximum_y == KB7_DISPLAY_HEIGHT || maximum_y + 1U == KB7_DISPLAY_HEIGHT);
}

bool kb7_touch_decode_records(const uint8_t *records, uint8_t contacts,
                              struct kb7_touch_frame *frame) {
    if (records == NULL || frame == NULL || contacts == 0U || contacts > TOUCH_MAX_CONTACTS) {
        return false;
    }
    frame->count = 0U;
    for (uint8_t slot = 0U; slot < contacts; ++slot) {
        const uint8_t *const record = &records[(size_t)slot * 7U];
        if ((record[0] & 0x80U) == 0U) continue;
        const uint16_t x = (uint16_t)(((uint16_t)(record[0] & 0x3fU) << 8U) | record[1]);
        const uint16_t y = (uint16_t)(((uint16_t)(record[2] & 0x3fU) << 8U) | record[3]);
        if (x >= KB7_DISPLAY_WIDTH || y >= KB7_DISPLAY_HEIGHT) continue;
        struct kb7_touch_point *point = &frame->points[frame->count++];
        point->x = x;
        point->y = y;
        point->id = slot;
        point->pressure = record[5];
    }
    return true;
}

#if KB7_ENABLE_TOUCH
static uint8_t touch_max_contacts;

static bool i2c_delay(void) { return kb7_delay_us(2U); }

static void sda_release(void) {
    kb7_gpio_configure(TOUCH_SDA, KB7_GPIO_INPUT, 0U, KB7_GPIO_PULL_UP);
}

static void sda_low(void) {
    kb7_gpio_write(TOUCH_SDA, false);
    kb7_gpio_configure(TOUCH_SDA, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
}

static void scl_low(void) {
    kb7_gpio_write(TOUCH_SCL, false);
    kb7_gpio_configure(TOUCH_SCL, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
}

static bool scl_release(void) {
    kb7_gpio_configure(TOUCH_SCL, KB7_GPIO_INPUT, 0U, KB7_GPIO_PULL_UP);
    uint32_t timeout = TOUCH_STRETCH_TIMEOUT;
    while (!kb7_gpio_read(TOUCH_SCL)) {
        if (timeout == 0U) {
            return false;
        }
        --timeout;
    }
    return true;
}

static bool i2c_start(void) {
    sda_release();
    if (!scl_release()) return false;
    if (!i2c_delay()) return false;
    sda_low();
    if (!i2c_delay()) return false;
    scl_low();
    return true;
}

static bool i2c_stop(void) {
    sda_low();
    if (!scl_release()) {
        sda_release();
        return false;
    }
    if (!i2c_delay()) return false;
    sda_release();
    if (!i2c_delay()) return false;
    return true;
}

static bool i2c_write(uint8_t value) {
    for (uint8_t mask = 0x80U; mask != 0U; mask >>= 1U) {
        if ((value & mask) != 0U) {
            sda_release();
        } else {
            sda_low();
        }
        if (!scl_release()) return false;
        if (!i2c_delay()) return false;
        scl_low();
        if (!i2c_delay()) return false;
    }
    sda_release();
    if (!scl_release()) return false;
    if (!i2c_delay()) return false;
    const bool ack = !kb7_gpio_read(TOUCH_SDA);
    scl_low();
    if (!i2c_delay()) return false;
    return ack;
}

static bool i2c_read(bool acknowledge, uint8_t *result) {
    uint8_t value = 0U;
    sda_release();
    for (uint8_t bit = 0U; bit < 8U; ++bit) {
        value <<= 1U;
        if (!scl_release()) return false;
        if (!i2c_delay()) return false;
        value |= kb7_gpio_read(TOUCH_SDA) ? 1U : 0U;
        scl_low();
        if (!i2c_delay()) return false;
    }
    if (acknowledge) {
        sda_low();
    }
    if (!scl_release()) return false;
    if (!i2c_delay()) return false;
    scl_low();
    sda_release();
    if (!i2c_delay()) return false;
    *result = value;
    return true;
}

static bool i2c_recover(void) {
    sda_release();
    if (!scl_release()) return false;
    for (uint8_t pulse = 0U; pulse < 9U && !kb7_gpio_read(TOUCH_SDA); ++pulse) {
        scl_low();
        if (!i2c_delay() || !scl_release() || !i2c_delay()) return false;
    }
    if (!kb7_gpio_read(TOUCH_SDA)) return false;
    return i2c_stop();
}

static bool touch_read_register(uint16_t address, uint8_t *data, size_t length) {
    if (!i2c_start()) return false;
    if (!i2c_write(TOUCH_ADDRESS_WRITE) || !i2c_write((uint8_t)(address >> 8U)) ||
        !i2c_write((uint8_t)address)) {
        (void)i2c_stop();
        return false;
    }
    if (!i2c_stop() || !i2c_start()) return false;
    if (!i2c_write(TOUCH_ADDRESS_READ)) {
        (void)i2c_stop();
        return false;
    }
    for (size_t index = 0; index < length; ++index) {
        if (!i2c_read(index + 1U != length, &data[index])) {
            (void)i2c_stop();
            return false;
        }
    }
    return i2c_stop();
}

bool kb7_touch_init(void) {
    touch_max_contacts = 0U;
    kb7_gpio_configure(TOUCH_IRQ, KB7_GPIO_INPUT, 0U, KB7_GPIO_PULL_UP);
    kb7_gpio_configure(TOUCH_RESET, KB7_GPIO_OUTPUT, 0U, KB7_GPIO_FLOATING);
    sda_release();
    if (!i2c_recover()) return false;
    kb7_gpio_write(TOUCH_RESET, false);
    if (!kb7_delay_ms(10U)) return false;
    kb7_gpio_write(TOUCH_RESET, true);
    if (!kb7_delay_ms(110U)) return false;

    uint8_t identity = 0U;
    uint8_t maximum = 0U;
    uint8_t status = 0U;
    uint8_t geometry[4];
    if (!touch_read_register(0x00f4U, &identity, 1U) || identity == 0U || identity == 0xffU ||
        !touch_read_register(0x0009U, &maximum, 1U) || maximum == 0U ||
        maximum > TOUCH_MAX_CONTACTS ||
        !touch_read_register(0x0001U, &status, 1U) ||
        !touch_read_register(0x0005U, geometry, sizeof(geometry))) {
        return false;
    }
    const uint16_t maximum_x = (uint16_t)(((uint16_t)geometry[0] << 8U) | geometry[1]);
    const uint16_t maximum_y = (uint16_t)(((uint16_t)geometry[2] << 8U) | geometry[3]);
    if (!kb7_touch_geometry_supported(maximum_x, maximum_y)) {
        return false;
    }
    (void)status; /* A successful status transaction is the recovered health check. */
    touch_max_contacts = maximum;
    return true;
}

bool kb7_touch_read(struct kb7_touch_frame *frame) {
    if (frame == NULL) {
        return false;
    }
    frame->count = 0U;
    if (kb7_gpio_read(TOUCH_IRQ)) {
        return true;
    }
    if (touch_max_contacts == 0U) return false;
    uint8_t records[TOUCH_MAX_CONTACTS * 7U];
    const size_t length = (size_t)touch_max_contacts * 7U;
    if (!touch_read_register(0x0014U, records, length)) return false;
    return kb7_touch_decode_records(records, touch_max_contacts, frame);
}
#else
bool kb7_touch_init(void) {
    return false;
}

bool kb7_touch_read(struct kb7_touch_frame *frame) {
    if (frame != NULL) frame->count = 0U;
    return false;
}
#endif
