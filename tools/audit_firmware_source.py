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
    for setting in ("DRAM_INIT", "DISPLAY", "TOUCH", "RGB", "MCU2", "ENCODER"):
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
        failures.append("core0 no longer defines all 79 vector words")
    if "SIZEOF(.isr_vector) == 79 * 4" not in linker:
        failures.append("linker no longer enforces the vector-table size")

    usb = source("core0/usb.c")
    if "bool kb7_usb_init(void) {\n    return false;" not in usb or "return -2;" not in usb:
        failures.append("public USB transport no longer fails closed")
    flash = source("drivers/flash.c")
    if flash.count("return -1;") < 3:
        failures.append("public NOR mutation stubs no longer fail closed")

    makefile = source("Makefile")
    if "OBJCOPY" in makefile or "exit 2" not in makefile:
        failures.append("public build can emit a flashable binary/bundle")
    if "-mcpu=cortex-m3" not in makefile or "-mcpu=cortex-m4" in makefile:
        failures.append("firmware compiler target is not Cortex-M3")

    regs = source("include/kb7/regs.h")
    required_bases = {
        "SNC_SPI_NOR_BASE": "0x40022000",
        "SNC_SD0_BASE": "0x40023000",
        "SNC_SDIO_BASE": "0x40024000",
    }
    for name, value in required_bases.items():
        if f"#define {name} UINT32_C({value})" not in regs:
            failures.append(f"datasheet-corroborated base {name} is not {value}")

    if failures:
        for failure in failures:
            print(f"firmware safety audit: {failure}", file=sys.stderr)
        return 1
    print("firmware safety audit: public hardware boundary and regressions pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
