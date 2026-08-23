#!/usr/bin/env python3
"""Fail-closed regression checks for the public firmware safety boundary."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    firmware = root / "replacement_fw"
    failures: list[str] = []

    def source(relative: str) -> str:
        return (firmware / relative).read_text(encoding="utf-8")

    config = source("include/kb7/config.h")
    for setting in ("DRAM_INIT", "RECOVERY_CHORD", "DISPLAY", "TOUCH", "RGB", "MCU2",
                    "ENCODER", "ACTION_BAR"):
        pattern = rf"#define KB7_ENABLE_(?:UNVERIFIED_)?{setting} 0\b"
        if re.search(pattern, config) is None:
            failures.append(f"public default KB7_ENABLE_{setting} is not zero")

    combined = "\n".join(path.read_text(encoding="utf-8") for path in firmware.rglob("*.c"))
    if re.search(r"\btimeout\s*--", combined):
        failures.append("post-decrement timeout condition reintroduced")
    if "report[0] = 0x03" in combined or "{0x03U," in combined:
        failures.append("undeclared legacy report ID 0x03 reintroduced")
    if "kb7_gpio_write(TOUCH_SCL, true)" in source("drivers/touch.c"):
        failures.append("touch SCL is driven high instead of released")

    reports = source("include/kb7/reports.h")
    identifiers = re.findall(r"#define KB7_REPORT_ID_\w+\s+(0x[0-9a-f]+)U", reports)
    if len(identifiers) != 4 or len(set(identifiers)) != len(identifiers):
        failures.append("report identifiers are missing or non-unique")

    startup = source("core0/startup.c")
    linker = source("linker/core0.ld")
    if "vectors[79]" not in startup or "[16 ... 78]" not in startup:
        if "[16 ... 21]" not in startup or "[22] = kb7_usb_irq_handler" not in startup or \
                "[23 ... 78]" not in startup:
            failures.append("core0 no longer defines all 79 vectors with USB IRQ6")
    if "SIZEOF(.isr_vector) == 79 * 4" not in linker:
        failures.append("linker no longer enforces the vector-table size")
    runtime = source("include/kb7/runtime.h")
    pair_header = source("include/kb7/build_pair.h")
    core0_main = source("core0/main.c")
    core1_startup = source("core1/startup.c")
    core1_linker = source("linker/core1.ld")
    if "#define KB7_RUNTIME_ABI_VERSION 2U" not in runtime or \
            "build_pair_id[KB7_BUILD_PAIR_ID_BYTES]" not in runtime:
        failures.append("paired-region runtime ABI guard is missing")
    for marker in ("KB7_CORE0_BUILD_PAIR_ADDRESS UINT32_C(0x00000140)",
                   "KB7_CORE1_BUILD_PAIR_ADDRESS UINT32_C(0x10000100)"):
        if marker not in pair_header:
            failures.append(f"fixed build-pair marker is missing: {marker}")
    if "kb7_build_pair_marker_valid" not in core0_main or \
            core0_main.find("kb7_build_pair_marker_valid") > core0_main.find("kb7_usb_init"):
        failures.append("Core 0 does not reject a mismatched region pair before USB")
    if "kb7_build_pair_ids_equal" not in core1_startup or \
            core1_startup.find("kb7_build_pair_ids_equal") > \
            core1_startup.find("uint32_t *source = &__data_load_start__"):
        failures.append("region-1 entry does not reject a mismatched pair before data init")
    if "core0 build-pair marker moved" not in linker or \
            "core0 image overlaps updater fixup reserve" not in linker or \
            "core1 build-pair marker moved" not in core1_linker or \
            "core1 image overlaps updater fixup reserve" not in core1_linker:
        failures.append("linkers no longer reserve the paired updater metadata")

    usb = source("core0/usb.c")
    usb_profile = source("include/kb7/usb_device.h")
    if "#define KB7_USB_VENDOR_ID 0U" not in usb_profile or \
            "#define KB7_USB_PRODUCT_ID 0U" not in usb_profile or \
            "#define KB7_USB_BOARD_PROFILE_VERIFIED 0" not in usb_profile:
        failures.append("public USB identity/board profile no longer defaults fail closed")
    if "KB7_USB_BOARD_PROFILE_VERIFIED != 1" not in usb or \
            "KB7_HOST_MAILBOX_FULL" not in usb or "KB7_BIT(6)" not in usb:
        failures.append("USB board gate, mailbox, or IRQ6 integration is missing")
    flash = source("drivers/flash.c")
    if "#define KB7_ENABLE_FLASH_MUTATION 0" not in flash or \
            "kb7_flash_range_mutable" not in flash or \
            "KB7_STORAGE_PROFILE_A" not in flash or "KB7_STORAGE_SCREEN_A" not in flash:
        failures.append("NOR mutation gate or storage-only allow-list is missing")
    mcu2 = source("drivers/mcu2.c")
    mcu2_profile = source("include/kb7/mcu2_protocol.h")
    if "#define KB7_MCU2_BOARD_PROFILE_VERIFIED 0" not in mcu2_profile or \
            "KB7_ENABLE_MCU2 && KB7_MCU2_BOARD_PROFILE_VERIFIED" not in mcu2:
        failures.append("MCU2 board profile no longer defaults non-transmitting")
    main_source = source("core1/main.c")
    if "#define KB7_ACTION_BAR_BOARD_PROFILE_VERIFIED 0" not in config or \
            "KB7_ENABLE_ACTION_BAR && KB7_ACTION_BAR_BOARD_PROFILE_VERIFIED" not in main_source:
        failures.append("action-bar board profile no longer defaults non-sampling")
    recovery = source("drivers/recovery.c")
    if "SNC_SCB_AIRCR" in recovery or "0x05fa0004" in recovery:
        failures.append("software reset was reintroduced as a false loader-entry path")
    if "kb7_disable_irq();" not in recovery or "SNC_SYST_CSR) = 0U" not in recovery:
        failures.append("unproven loader request no longer parks fail closed")

    makefile = source("Makefile")
    if "OBJCOPY" in makefile or "exit 2" not in makefile:
        failures.append("ordinary firmware Makefile can emit an installable bundle")
    if "-mcpu=cortex-m3" not in makefile or "-mcpu=cortex-m4" in makefile:
        failures.append("firmware compiler target is not Cortex-M3")

    regs = source("include/kb7/regs.h")
    required_bases = {
        "SNC_SPI_NOR_BASE": "0x40022000",
        "SNC_SD0_BASE": "0x40023000",
        "SNC_SDIO_BASE": "0x40024000",
        "SNC_SERIAL0_BASE": "0x4000e000",
        "SNC_USB_BASE": "0x40100000",
    }
    for name, value in required_bases.items():
        if f"#define {name} UINT32_C({value})" not in regs:
            failures.append(f"datasheet-corroborated base {name} is not {value}")

    gpio = source("drivers/gpio.c")
    for marker in ("SNC_PINCTRL_LCD_ALT_GROUP KB7_BIT(1)",
                   "SNC_PINCTRL_SPI0DMA_ALT_GROUP KB7_BIT(8)",
                   "SNC_PINCTRL_TIMER6_PWM1_ROUTE KB7_BIT(17)"):
        if marker not in regs:
            failures.append(f"recovered PINCTRL model is missing: {marker}")
    for marker in ("function == 1U && logical >= 36U && logical <= 57U",
                   "function == 4U && logical >= 14U && logical <= 17U"):
        if marker not in gpio:
            failures.append(f"stock default peripheral route is missing: {marker}")
    if "if (function == 0U)" not in gpio or \
            gpio.find("SNC_GPIO_PIN_CONFIG") < gpio.find("if (function == 0U)"):
        failures.append("alternate-function pads are rewritten as GPIO")

    storage = source("include/kb7/storage.h")
    for marker in ("KB7_STORAGE_PROFILE_A", "KB7_STORAGE_PROFILE_B",
                   "KB7_STORAGE_PROFILE_SLOT_BYTES"):
        if marker not in storage:
            failures.append(f"persistent profile slot marker {marker} is missing")
    safe_storage_markers = {
        "KB7_STORAGE_SCREEN_A": "0x01570000",
        "KB7_STORAGE_SCREEN_B": "0x016b0000",
        "KB7_STORAGE_SCREEN_SLOT_BYTES": "0x00140000",
        "KB7_STORAGE_PROFILE_A": "0x01c00000",
        "KB7_STORAGE_PROFILE_B": "0x01c38000",
        "KB7_STORAGE_STOCK_UPLOAD_START": "0x01f00000",
    }
    for name, value in safe_storage_markers.items():
        if f"#define {name} UINT32_C({value})" not in storage:
            failures.append(f"full-flash-derived storage marker {name} is not {value}")

    input_profiles = source("include/kb7/input_profiles.h")
    if "#define KB7_INPUT_PROFILE_SLOT_COUNT 5U" not in input_profiles:
        failures.append("runtime profile count no longer matches the five-slot stock evidence")

    profile = source("core1/profile_blob.c")
    if "KB7_PROFILE_RECORD_SIZE" not in profile or "kb7_input_profile_valid" not in profile:
        failures.append("KBP1 parser no longer validates fixed records and runtime profiles")

    if failures:
        for failure in failures:
            print(f"firmware safety audit: {failure}", file=sys.stderr)
        return 1
    print("firmware safety audit: public hardware boundary and regressions pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
