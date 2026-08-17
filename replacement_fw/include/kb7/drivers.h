#ifndef KB7_DRIVERS_H
#define KB7_DRIVERS_H

#include "kb7/platform.h"

enum kb7_gpio_direction { KB7_GPIO_INPUT = 0, KB7_GPIO_OUTPUT = 1 };
enum kb7_gpio_pull { KB7_GPIO_FLOATING = 0, KB7_GPIO_PULL_UP = 1, KB7_GPIO_PULL_DOWN = 2 };

uint32_t kb7_gpio_bank(uint8_t logical);
uint16_t kb7_gpio_mask(uint8_t logical);
void kb7_gpio_configure(uint8_t logical, enum kb7_gpio_direction direction,
                        uint8_t function, enum kb7_gpio_pull pull);
void kb7_gpio_write(uint8_t logical, bool high);
bool kb7_gpio_read(uint8_t logical);

void kb7_delay_cycles(volatile uint32_t cycles);
void kb7_backlight_init(void);
void kb7_backlight_set(uint16_t duty);

bool kb7_clock_init(void);
bool kb7_dram_init_and_train(void);
bool kb7_dram_march_test(uintptr_t address, size_t bytes);

int32_t kb7_flash_read(uint32_t offset, void *data, uint32_t length);
int32_t kb7_flash_erase_4k(uint32_t offset);
int32_t kb7_flash_program(uint32_t offset, const void *data, uint32_t length);

void kb7_panel_init(void);
bool kb7_lcdc_init(uintptr_t framebuffer);
void kb7_lcdc_set_framebuffer(uintptr_t framebuffer);
void kb7_lcdc_fill(uintptr_t framebuffer, uint16_t color);

struct kb7_touch_point { uint16_t x; uint16_t y; uint8_t id; uint8_t pressure; };
struct kb7_touch_frame { uint8_t count; struct kb7_touch_point points[10]; };
bool kb7_touch_init(void);
bool kb7_touch_read(struct kb7_touch_frame *frame);

#define KB7_RGB_POSITION_COUNT 112U
#define KB7_RGB_ACTIVE_COUNT 101U
struct kb7_rgb { uint8_t red; uint8_t green; uint8_t blue; };
bool kb7_rgb_init(void);
void kb7_rgb_set_brightness(uint8_t percent);
bool kb7_rgb_present(uint16_t position);
void kb7_rgb_show(const struct kb7_rgb colors[KB7_RGB_POSITION_COUNT]);

#define KB7_MCU2_FRAME_SIZE 84U
#define KB7_HALL_KEY_COUNT 82U
enum kb7_mcu2_result { KB7_MCU2_OK = 0, KB7_MCU2_BUSY = -1, KB7_MCU2_BAD_FRAME = -2,
                       KB7_MCU2_IO = -3, KB7_MCU2_UNSUPPORTED = -4 };
bool kb7_mcu2_init(void);
enum kb7_mcu2_result kb7_mcu2_exchange(const uint8_t request[KB7_MCU2_FRAME_SIZE],
                                       uint8_t response[KB7_MCU2_FRAME_SIZE]);
enum kb7_mcu2_result kb7_mcu2_read_normalized(uint8_t values[KB7_HALL_KEY_COUNT]);

struct kb7_hall_config {
    uint8_t actuation;
    uint8_t rapid_press_delta;
    uint8_t rapid_release_delta;
    bool rapid_trigger;
};
struct kb7_hall_state { bool pressed; uint8_t peak; uint8_t valley; };
void kb7_hall_reset(struct kb7_hall_state state[KB7_HALL_KEY_COUNT]);
bool kb7_hall_update(struct kb7_hall_state *state, uint8_t sample,
                     const struct kb7_hall_config *config);

enum kb7_encoder_event { KB7_ENCODER_NONE = 0, KB7_ENCODER_CW = 1, KB7_ENCODER_CCW = -1 };
void kb7_encoder_init(void);
enum kb7_encoder_event kb7_encoder_poll(void);

bool kb7_usb_init(void);
void kb7_usb_poll(void);
int32_t kb7_usb_send(uint8_t endpoint, const void *data, uint16_t length);
void kb7_usb_keyboard_report(const uint8_t bits[19], uint8_t modifiers);
void kb7_usb_consumer_usage(uint16_t usage);

void kb7_enter_loader(void) KB7_NORETURN;

#endif
