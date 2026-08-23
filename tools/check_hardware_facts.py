#!/usr/bin/env python3
"""Validate the derived SNC7320 and KB7 machine-readable hardware facts."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_HASH = "d360aca16c2695f12edf91d263b2994b36edf5ad6faf130547a9220dfaca94b4"


def load(name: str) -> dict[str, object]:
    path = ROOT / "hardware" / name
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_soc(soc: dict[str, object]) -> None:
    source = soc["source"]
    require(isinstance(source, dict), "SoC source metadata must be an object")
    require(source["sha256"] == EXPECTED_SOURCE_HASH, "unexpected SoC source hash")
    require(source["pages"] == 94, "unexpected datasheet page count")

    blocks = soc["mmio_blocks"]
    require(isinstance(blocks, list), "MMIO blocks must be a list")
    names = {block["name"]: block["base"] for block in blocks}
    require(len(names) == len(blocks), "duplicate MMIO block name")
    require(len(set(names.values())) == len(names), "duplicate MMIO block base")
    expected = {
        "WDT": "0x40008000",
        "SPI1": "0x4000f000",
        "SFC_SPI_NOR": "0x40022000",
        "SD0_NAND": "0x40023000",
        "SD1_SDIO": "0x40024000",
        "ICACHE": "0x4002f000",
        "DRAM_OPI": "0x40040000",
        "PPU_TFT_8080": "0x40050000",
        "USB_DEVICE": "0x40100000",
        "SYS0": "0x45000000",
        "SYS1": "0x45000100",
        "PMU": "0x45000300",
    }
    for name, base in expected.items():
        require(names.get(name) == base, f"{name} must remain at {base}")

    interrupts = soc["interrupts"]
    require(isinstance(interrupts, list), "interrupts must be a list")
    require([item["irq"] for item in interrupts] == list(range(57)),
            "interrupt list must cover IRQ0 through IRQ56 exactly once")
    for item in interrupts:
        irq = item["irq"]
        require(item["vector_index"] == irq + 16, f"IRQ{irq} vector index mismatch")
        expected_offset = f"0x{(irq + 16) * 4:03x}"
        require(item["vector_offset"] == expected_offset,
                f"IRQ{irq} vector offset must be {expected_offset}")

    vector = soc["vector_requirements"]
    require(vector["datasheet_minimum_words_through_last_index"] == 73,
            "datasheet vector span must remain 73 words")
    require(vector["public_table_words"] >= 73, "public vector table is too short")

    dma = soc["dma_channels"]
    require(dma["datasheet_table_row_count"] == len(dma["channels"]) == 18,
            "preserve the documented 19-versus-18 DMA inconsistency")


def lead_for_pad(gpio_leads: dict[str, list[int]], pad: str) -> int:
    port, bit_text = pad.split(".")
    return gpio_leads[port][int(bit_text)]


def validate_pin_map(pinmap: dict[str, object]) -> None:
    datasheet = pinmap["source"]["datasheet"]
    require(datasheet["sha256"] == EXPECTED_SOURCE_HASH, "pin-map source hash mismatch")

    gpio_leads = pinmap["gpio_package_leads"]
    require(set(gpio_leads) == {"P0", "P1", "P2", "P3", "P4"},
            "pin map must contain GPIO ports P0 through P4")
    flattened: list[int] = []
    for port, leads in gpio_leads.items():
        require(len(leads) == 16, f"{port} must contain 16 bit positions")
        require(all(isinstance(lead, int) and 1 <= lead <= 128 for lead in leads),
                f"{port} contains an invalid package lead")
        flattened.extend(leads)
    require(len(flattened) == 80 and len(set(flattened)) == 80,
            "all 80 GPIO package leads must be unique")

    seen_logical: set[int] = set()
    for entry in pinmap["kb7_signals"]:
        logical = entry["logical_gpio"]
        if logical is None:
            continue
        require(logical not in seen_logical, f"duplicate logical GPIO {logical}")
        seen_logical.add(logical)
        expected_pad = f"P{logical >> 4}.{logical & 15}"
        require(entry["soc_pad"] == expected_pad,
                f"logical GPIO {logical} must map to {expected_pad}")
        require(entry["package_lead"] == lead_for_pad(gpio_leads, expected_pad),
                f"logical GPIO {logical} has the wrong package lead")

    for interface in pinmap["interface_groups"].values():
        for field in ("signals", "control"):
            for signal in interface.get(field, []):
                pad = signal.get("pad")
                if pad is not None:
                    require(signal["lead"] == lead_for_pad(gpio_leads, pad),
                            f"{pad} interface lead mismatch")

    reset = next(entry for entry in pinmap["kb7_signals"]
                 if entry["function"] == "MCU_RST board pad candidate")
    require(reset["soc_pad"] == "RSTN" and reset["package_lead"] == 88,
            "MCU_RST must remain an unverified candidate for RSTN lead 88")
    require(reset["continuity"] == "unverified",
            "do not mark MCU_RST continuity as verified without a measurement record")


def validate_stock_flash(stock: dict[str, object]) -> None:
    require(stock["schema_version"] == 3 and
            stock["updated_on"] == "2026-08-23",
            "stock-flash evidence schema must describe the recovery and USB-ISP results")
    acquisition = stock["acquisition"]
    require(acquisition["read_count"] == 2 and acquisition["bit_identical"] is True,
            "stock flash must retain the two-read evidence boundary")
    require(acquisition["size_bytes"] == 0x02000000,
            "stock flash size must remain 32 MiB")
    require(acquisition["sha256"] ==
            "c3c4125b8c42019bac65be8cb71ee1d8b9f91dd32c1f8cc918b34454d9bb7027",
            "unexpected stock flash hash")
    require(acquisition["programmer_cs_logic_high_v"] == 5.0 and
            acquisition["programmer_voltage_safe_for_target"] is False,
            "retain the unsafe CH341 CS-voltage observation")
    require(acquisition["acquisition_programmer_write_tested"] is False,
            "the CH341 acquisition setup was not write-qualified")

    recovery = stock["recovery_validation"]
    require(recovery["stock_repair_write_and_boot_observed"] is True,
            "retain the observed external stock-repair result")
    require(recovery["full_chip_bit_identical_restore_proven"] is True and
            recovery["post_restore_usb_read_count"] == 2 and
            recovery["post_restore_usb_reads_bit_identical"] is True and
            recovery["post_restore_usb_read_size_bytes"] == 0x02000000 and
            recovery["post_restore_usb_sha256"] ==
            "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f" and
            recovery["custom_firmware_booted"] is False,
            "retain the demonstrated rollback boundary without promoting custom firmware")

    usb_write = stock["usb_isp_write_validation"]
    require(usb_write["target_offset"] == "0x0008e000" and
            usb_write["program_length_bytes"] == 512 and
            usb_write["program_address_mode_command"] == "f6 18" and
            usb_write["erase_address_mode_command"] == "f6 18",
            "unexpected bounded USB-ISP target or address-mode sequence")
    require(usb_write["program_cdb"] ==
            "f6 06 00 60 08 e0 00 00 01 00 00 00 00 00 00 00" and
            usb_write["erase_cdb"] ==
            "f6 15 00 04 70 00 00 00 00 00 00 00 00 00 00 00",
            "unexpected bounded USB-ISP mutation CDB")
    require(usb_write["complete_postimages_exact"] is True and
            usb_write["exact_erase_granularity_proven"] is False and
            usb_write["f6_19_tested"] is False and
            usb_write["custom_firmware_booted"] is False,
            "retain the narrow USB-ISP proof boundary")

    regions = stock["manifest"]["regions"]
    require([region["index"] for region in regions] == [0, 1, 2],
            "stock manifest region indices changed")
    require([region["checksum_matches"] for region in regions] == [True, True, False],
            "preserve the unresolved installed region-2 checksum anomaly")

    partitions = stock["stock_tail_partitions"]
    require([(part["start"], part["end_exclusive"]) for part in partitions] == [
        ("0x01800000", "0x01a00000"),
        ("0x01a00000", "0x01c00000"),
        ("0x01f00000", "0x02000000"),
    ], "stock tail ownership boundaries changed")
    require(partitions[0]["header_profile_count"] == 5 and
            partitions[1]["header_profile_count"] == 5,
            "stock configuration must retain five-profile evidence")

    custom = stock["custom_mutable_slots"]
    require(custom == [
        ["screen_a", "0x01570000", "0x016b0000"],
        ["screen_b", "0x016b0000", "0x017f0000"],
        ["profile_a", "0x01c00000", "0x01c38000"],
        ["profile_b", "0x01c38000", "0x01c70000"],
    ], "custom slots no longer match the full-flash-derived safe map")


def main() -> int:
    try:
        validate_soc(load("snc7320-soc.json"))
        validate_pin_map(load("kb7-pin-map.json"))
        validate_stock_flash(load("kb7-stock-flash.json"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"hardware facts check: {error}")
        return 1
    print("hardware facts check: SoC, IRQ, package, and stock-flash mappings pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
