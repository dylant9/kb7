#define _GNU_SOURCE
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#include "kb7/drivers.h"
#include "kb7/platform_boot.h"
#include "kb7/regs.h"
#include "kb7/storage.h"

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

static bool map_register_page(uintptr_t address) {
    void *result = mmap((void *)address, 4096U, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    return result != MAP_FAILED;
}

int main(void) {
    if (kb7_bitfield_insert(UINT32_C(0xffffffff), 15U, 8U, UINT32_C(0x42)) !=
        UINT32_C(0xffff42ff)) return 1;
    if (kb7_bitfield_insert(UINT32_C(0x12345678), 2U, 3U, 0U) !=
        UINT32_C(0x12345678)) return 2;
    if (kb7_clock_hz_for_state(1U, 0U, KB7_PLL_CLOCK_HZ) !=
        KB7_IHRC_CLOCK_HZ) return 3;
    if (kb7_clock_hz_for_state(3U, 0U, KB7_PLL_CLOCK_HZ) !=
        KB7_ILRC_CLOCK_HZ) return 4;
    if (kb7_clock_hz_for_state(4U, 1U, KB7_PLL_CLOCK_HZ) !=
        KB7_PLL_CLOCK_HZ / 4U) return 5;
    if (kb7_clock_hz_for_state(0U, 0U, KB7_PLL_CLOCK_HZ) != 0U) return 6;
    if (kb7_systick_reload(KB7_CORE_CLOCK_HZ) != UINT32_C(98999)) return 7;

    if (kb7_clock_rom_result_ok(0U) ||
        kb7_clock_rom_result_ok(UINT32_C(0x00ffffff)) ||
        !kb7_clock_rom_result_ok(UINT32_C(1))) return 8;
    const uint32_t sfc = kb7_clock_control_for_state(0U, 4U);
    if ((sfc & UINT32_C(0xb000)) != UINT32_C(0xb000)) return 9;

    if (kb7_gpio_bank(0U) != SNC_GPIO_A_BASE ||
        kb7_gpio_bank(79U) != SNC_GPIO_E_BASE || kb7_gpio_bank(80U) != 0U ||
        kb7_gpio_mask(31U) != UINT16_C(0x8000)) return 10;
    if (!kb7_gpio_pinmux_known(6U, 7U) || kb7_gpio_pinmux_known(7U, 7U) ||
        !kb7_gpio_pinmux_known(31U, 0U) ||
        !kb7_gpio_pinmux_known(36U, 1U) ||
        !kb7_gpio_pinmux_known(57U, 1U) || kb7_gpio_pinmux_known(58U, 1U) ||
        !kb7_gpio_pinmux_known(14U, 4U) ||
        !kb7_gpio_pinmux_known(17U, 4U) || kb7_gpio_pinmux_known(18U, 4U)) return 11;

    if (!map_register_page(SNC_GPIO_A_BASE) || !map_register_page(SNC_GPIO_C_BASE) ||
        !map_register_page(SNC_SYS0_BASE)) {
        return 77;
    }
    KB7_MMIO32(SNC_GPIO_A_BASE + SNC_GPIO_PIN_CONFIG) = UINT32_C(0xa5a5a5a5);
    kb7_gpio_configure(6U, KB7_GPIO_OUTPUT, 7U, KB7_GPIO_PULL_UP);
    if ((KB7_MMIO32(SNC_GPIO_A_BASE + SNC_GPIO_DIRECTION) & KB7_BIT(6)) != 0U ||
        KB7_MMIO32(SNC_GPIO_A_BASE + SNC_GPIO_PIN_CONFIG) != UINT32_C(0xa5a5a5a5) ||
        (KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PINCTRL) &
         SNC_PINCTRL_TIMER6_PWM1_ROUTE) == 0U) return 12;

    KB7_MMIO32(SNC_GPIO_C_BASE + SNC_GPIO_DIRECTION) = UINT32_C(0x00100000);
    KB7_MMIO32(SNC_GPIO_C_BASE + SNC_GPIO_PIN_CONFIG) = UINT32_C(0x5a5a5a5a);
    kb7_gpio_configure(36U, KB7_GPIO_OUTPUT, 1U, KB7_GPIO_FLOATING);
    if (KB7_MMIO32(SNC_GPIO_C_BASE + SNC_GPIO_DIRECTION) != UINT32_C(0x00100000) ||
        KB7_MMIO32(SNC_GPIO_C_BASE + SNC_GPIO_PIN_CONFIG) != UINT32_C(0x5a5a5a5a) ||
        (KB7_MMIO32(SNC_SYS0_BASE + SNC_SYS0_PINCTRL) &
         SNC_PINCTRL_LCD_ALT_GROUP) != 0U) return 12;

    if (kb7_pwm_compare(UINT32_C(1980000), 1023U, 0U) != UINT32_C(1980000) ||
        kb7_pwm_compare(UINT32_C(1980000), 1023U, 1023U) != 0U) return 13;
    if (!kb7_delay_us(1U) || !kb7_delay_us(0U) ||
        kb7_delay_us(UINT32_C(10000001))) return 14;

    if (!kb7_flash_range_mutable(KB7_STORAGE_SCREEN_A, UINT32_C(1)) ||
        !kb7_flash_range_mutable(KB7_STORAGE_SCREEN_B,
                                 KB7_STORAGE_SCREEN_SLOT_BYTES) ||
        kb7_flash_range_mutable(KB7_STORAGE_SCREEN_A - 1U, UINT32_C(1)) ||
        kb7_flash_range_mutable(KB7_STORAGE_SCREEN_B +
                                    KB7_STORAGE_SCREEN_SLOT_BYTES - 1U,
                                UINT32_C(2)) ||
        !kb7_flash_range_mutable(KB7_STORAGE_PROFILE_A,
                                 KB7_STORAGE_PROFILE_SLOT_BYTES) ||
        !kb7_flash_range_mutable(KB7_STORAGE_PROFILE_B,
                                 KB7_STORAGE_PROFILE_SLOT_BYTES) ||
        kb7_flash_range_mutable(KB7_STORAGE_SCREEN_A +
                                    KB7_STORAGE_SCREEN_SLOT_BYTES - 1U,
                                2U) ||
        kb7_flash_range_mutable(KB7_STORAGE_PROFILE_A +
                                    KB7_STORAGE_PROFILE_SLOT_BYTES - 1U,
                                2U) ||
        kb7_flash_range_mutable(KB7_STORAGE_STOCK_LEGACY_START, UINT32_C(1)) ||
        kb7_flash_range_mutable(KB7_STORAGE_STOCK_CONFIG_START, UINT32_C(1)) ||
        kb7_flash_range_mutable(KB7_STORAGE_STOCK_UPLOAD_START, UINT32_C(1)) ||
        kb7_flash_range_mutable(UINT32_C(0x01c70000), UINT32_C(1)) ||
        kb7_flash_range_mutable(UINT32_C(0x01fe0000), UINT32_C(1)) ||
        kb7_flash_range_mutable(KB7_STORAGE_SCREEN_A, 0U)) return 15;
    if (!map_register_page(UINT32_C(0x60000000))) return 77;
    uint8_t *xip = (uint8_t *)(uintptr_t)UINT32_C(0x60000000);
    uint8_t copied[32];
    for (size_t index = 0U; index < sizeof(copied); ++index) {
        xip[index] = (uint8_t)(index ^ UINT8_C(0xa5));
    }
    if (kb7_flash_read(0U, copied, sizeof(copied)) != 0 ||
        memcmp(copied, xip, sizeof(copied)) != 0 ||
        kb7_flash_read(UINT32_C(0x02000000), copied, 1U) == 0) return 16;
    return 0;
}
