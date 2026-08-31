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
    require(pinmap["schema_version"] == 2,
            "pin-map schema must include the recovered PINCTRL model")
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

    pinmux = pinmap["pinmux_control_model"]
    require(pinmux["generic_per_pad_pinctrl_field"] is False,
            "do not model SYS0_PINCTRL as a generic per-pad field")
    require([item["version"] for item in pinmux["stock_releases"]] ==
            ["V1.22", "V1.24", "V1.33"],
            "pinmux evidence must retain all three stock releases")
    require([(item["core0_sha256"], item["core1_sha256"])
             for item in pinmux["stock_releases"]] == [
                ("d779faf9f591e71602e5f17e966ac366602699a83fb5e612534d694d3dafd153",
                 "b2869bc657ba896474e760f513e4514fac678a951364efc29cbf9b6bb5e2ba72"),
                ("79eb92bc73ddccbfff682927df7c951802fd64c9863cdeacd9b230642b5ca695",
                 "dcb06f976dcaff81d0c5ccd1fdfebcb5b6ca4ec3d7e003ad1e90f896a4139aa7"),
                ("30f791af363b39f472095152118413421e525a2ed09fef87b236f1a437e32cc6",
                 "d64df057dbdd125b12f156b57de5ad75a9a0d5804e30a16bb9ef1a56830d101f"),
            ], "stock pinmux evidence hashes changed")
    require([item["pinctrl_clear_routine_address"]
             for item in pinmux["stock_releases"]] ==
            ["0x00007018", "0x0000738c", "0x00003534"],
            "stock Core0 PINCTRL-clear addresses changed")
    require([item["timer6_pwm_route_rmw_address"]
             for item in pinmux["stock_releases"]] ==
            ["0x10008af4", "0x10008e64", "0x1000cc6c"],
            "stock PWM PINCTRL addresses changed")
    require({item["bit"] for item in pinmux["exceptional_selectors"]} ==
            {0, 1, 8, 17}, "recovered exceptional PINCTRL selectors changed")
    routes = {item["name"]: item for item in pinmux["kb7_default_routes"]}
    require(routes["lcd_rgb18"]["mode"] == 1 and
            routes["lcd_rgb18"]["required_exceptional_selector_bits_set"] == [],
            "LCD must remain on the default mode-1 group")
    require(routes["mcu2_spi0"]["mode"] == 4 and
            routes["mcu2_spi0"]["required_exceptional_selector_bits_set"] == [],
            "MCU2 must remain on the default SPI0 mode-4 group")
    require(routes["backlight_pwm"]["required_exceptional_selector_bits_set"] == [17],
            "backlight must retain the stock-proven PINCTRL bit 17")
    peer = pinmux["peer_mcu_spi3"]
    require(peer["part"] == "AT32F423" and
            peer["stock_firmware_sha256"] ==
            "8452e825bc71bda5696ecc8b33d3b31e1f7a8f0d4ed677985d2532768e92aa66",
            "unexpected MCU2 evidence identity")
    require([(pin["signal"], pin["pin"], pin["alternate_function"])
             for pin in peer["pins"]] ==
            [("CS", "PA15", 6), ("SCK", "PC10", 6),
             ("MISO", "PC11", 6), ("MOSI", "PC12", 6)],
            "AT32 SPI3 pin assignment changed")

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
            "MCU_RST must remain the RSTN lead-88 candidate")
    require(reset["continuity"] == "not_directly_measured" and
            reset["operational_status"] == "validated_for_external_spi_isolation",
            "retain the distinction between optional continuity and proven reset use")


def validate_stock_flash(stock: dict[str, object]) -> None:
    require(stock["schema_version"] == 8 and
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
            usb_write["exact_erase_granularity_proven_by_this_cycle"] is False and
            usb_write["f6_19_tested"] is False and
            usb_write["custom_firmware_booted"] is False,
            "retain the narrow USB-ISP proof boundary")

    granularity = stock["usb_isp_erase_granularity_validation"]
    require(granularity["device_count"] == 1 and
            granularity["loader_window_sha256"] ==
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56" and
            granularity["plan_sha256"] ==
            "a68642a348b18ee27a2f1cfdb6c8137aeff43c0ce14487f9c765c4c76e9be783",
            "unexpected guarded erase-footprint identity or plan")
    require(granularity["baseline_read_count"] == 2 and
            granularity["baseline_reads_bit_identical"] is True and
            granularity["baseline_size_bytes"] == 0x02000000 and
            granularity["baseline_sha256"] ==
            "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f" and
            granularity["baseline_manifest_region_checksums_passed"] is True,
            "guarded erase baseline evidence changed")
    require(granularity["target_sector_start"] == "0x000c6000" and
            granularity["target_sector_end_exclusive"] == "0x000c7000" and
            granularity["target_sector_size_bytes"] == 0x1000 and
            granularity["program_address_mode_command"] == "f6 18" and
            granularity["program_operation_count"] == 10 and
            granularity["program_block_size_bytes"] == 0x200 and
            granularity["target_program_block_count"] == 8 and
            granularity["guard_program_block_count"] == 2 and
            granularity["all_program_postimages_exact"] is True,
            "guarded erase preparation geometry changed")
    require(granularity["prepared_image_sha256"] ==
            "fdda369b75acc245efe119a165df7825649178af30c42096fcd4d2341547a3b7" and
            granularity["target_erase_address_mode_command"] == "f6 18" and
            granularity["target_erase_cdb"] ==
            "f6 15 00 06 30 00 00 00 00 00 00 00 00 00 00 00" and
            granularity["target_erased_image_sha256"] ==
            "0551c79084a3afd0eb7e21ec84b7c01ef74e0f35cc9da2a7b74f45c8cca74c03" and
            granularity["target_erased_bytes_verified"] == 0x1000,
            "guarded target-erase result changed")
    require(granularity["lower_guard_offset"] == "0x000c5e00" and
            granularity["upper_guard_offset"] == "0x000c7000" and
            granularity["lower_guard_survived_exactly"] is True and
            granularity["upper_guard_survived_exactly"] is True and
            granularity["observable_effect_start"] == "0x000c6000" and
            granularity["observable_effect_end_exclusive"] == "0x000c7000" and
            granularity[
                "observable_exact_4k_erase_footprint_proven_at_tested_target"
            ] is True,
            "observable 4-KiB erase-footprint evidence changed")
    require(granularity["lower_cleanup_cdb"] ==
            "f6 15 00 06 28 00 00 00 00 00 00 00 00 00 00 00" and
            granularity["lower_cleaned_image_sha256"] ==
            "b7959a78477eaa09c40a91692579a7735c812b1b078ccfacc94b21571fda52cb" and
            granularity["upper_cleanup_cdb"] ==
            "f6 15 00 06 38 00 00 00 00 00 00 00 00 00 00 00" and
            granularity["final_postflight_sha256"] ==
            granularity["baseline_sha256"] and
            granularity["final_postflight_matches_baseline"] is True and
            granularity["independent_final_usb_capture_size_bytes"] ==
            0x02000000 and
            granularity["independent_final_usb_capture_sha256"] ==
            granularity["baseline_sha256"] and
            granularity["independent_final_usb_capture_matches_baseline"] is True and
            granularity["state_cleared"] is True and
            granularity["post_test_cold_boot_and_normal_operation_owner_confirmed"]
            is True,
            "guarded erase cleanup or functional closure changed")
    require(granularity["f6_19_tested"] is False and
            granularity["above_16mib_mutation_tested"] is False and
            granularity["interruption_or_power_loss_tested"] is False and
            granularity["arbitrary_offsets_tested"] is False and
            granularity["custom_firmware_booted"] is False,
            "do not broaden the guarded erase-footprint proof boundary")

    restart = stock["usb_isp_scratch_restart_validation"]
    require(restart["device_count"] == 1 and
            restart["loader_window_sha256"] ==
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56" and
            restart["plan_sha256"] ==
            "d784f036e06a972d9688d15c76a41cbd7e90ca806d5ced1aeab5aae16745085b",
            "unexpected scratch-restart identity or fixed plan")
    require(restart["baseline_read_count"] == 2 and
            restart["baseline_reads_bit_identical"] is True and
            restart["baseline_size_bytes"] == 0x02000000 and
            restart["baseline_sha256"] ==
            "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f" and
            restart["baseline_manifest_region_checksums_passed"] is True,
            "scratch-restart baseline evidence changed")
    require(restart["containment_envelope_start"] == "0x000c0000" and
            restart["containment_envelope_end_exclusive"] == "0x00100000" and
            restart["containment_envelope_initially_erased"] is True and
            restart["lower_guard_offset"] == "0x000c4e00" and
            restart["work_a_sector_start"] == "0x000c5000" and
            restart["work_b_sector_start"] == "0x000c6000" and
            restart["upper_guard_offset"] == "0x000c7000",
            "scratch-restart containment geometry changed")
    require(restart["program_address_mode_command"] == "f6 18" and
            restart["program_operation_count"] == 18 and
            restart["program_block_size_bytes"] == 0x200 and
            restart["all_non_cut_program_postimages_exact"] is True and
            restart["prepare_a_image_sha256"] ==
            "ea8f9c343781027db13ad221a63784fe52e4689f1543f10562ff7504c8b6f7b6" and
            restart["program_cut_offset"] == "0x000c6000" and
            restart[
                "program_cut_completed_and_polled_without_immediate_readback"
            ] is True and
            restart["program_cut_reconciliation_read_count"] == 2 and
            restart["program_cut_reconciliation_reads_bit_identical"] is True and
            restart["program_cut_reconciliation_classification"] ==
            "exact_postimage_completed" and
            restart["program_cut_postimage_sha256"] ==
            "f67fb2f28944d13d82ffcc7f15514558c757db0e6e0a0f261866043093afa3e7" and
            restart["program_cut_automatic_retry"] is False and
            restart["fully_prepared_image_sha256"] ==
            "b7b27c2f6fa222fce47a5a2158836665ad2ad951d46b172a4c56215b06e77943",
            "scratch-restart program or reconciliation evidence changed")
    require(restart["erase_address_mode_command"] == "f6 18" and
            restart["erase_operation_count"] == 4 and
            restart["erase_a_cdb"] ==
            "f6 15 00 06 28 00 00 00 00 00 00 00 00 00 00 00" and
            restart[
                "erase_a_completed_and_polled_without_immediate_readback"
            ] is True and
            restart["erase_a_reconciliation_read_count"] == 2 and
            restart["erase_a_reconciliation_reads_bit_identical"] is True and
            restart["erase_a_reconciliation_classification"] ==
            "exact_postimage_completed" and
            restart["erase_a_postimage_sha256"] ==
            "ad1b1819bfbfdf0e74774674d3fd915694b231abf7e20808df940d42ef8be27f" and
            restart["erase_a_automatic_retry"] is False,
            "scratch-restart erase reconciliation evidence changed")
    require(restart["erase_b_cdb"] ==
            "f6 15 00 06 30 00 00 00 00 00 00 00 00 00 00 00" and
            restart["erase_b_postimage_sha256"] ==
            "7ca0d0f7fda30174863b378783f49cd97deef941c960772c75e856eee6283ff2" and
            restart["lower_cleanup_cdb"] ==
            "f6 15 00 06 20 00 00 00 00 00 00 00 00 00 00 00" and
            restart["lower_cleanup_postimage_sha256"] ==
            "a2bc397a329164f2740289563f862abe01d221b51a1ffb791ee3564fb50e5bc2" and
            restart["upper_cleanup_cdb"] ==
            "f6 15 00 06 38 00 00 00 00 00 00 00 00 00 00 00" and
            restart["final_stage_postimage_sha256"] ==
            restart["baseline_sha256"] and
            restart["final_stage_postimage_matches_baseline"] is True and
            restart["state_cleared"] is True,
            "scratch-restart cleanup evidence changed")
    require(restart["independent_final_usb_capture_size_bytes"] ==
            0x02000000 and
            restart["independent_final_usb_capture_sha256"] ==
            restart["baseline_sha256"] and
            restart["independent_final_usb_capture_matches_baseline"] is True and
            restart["independent_final_manifest_region_checksums_passed"] is True and
            restart["post_test_normal_5038_enumeration_owner_confirmed"] is True and
            restart["post_test_keyboard_working_owner_confirmed"] is True and
            restart[
                "separate_process_and_libusb_session_reconciliation_tested"
            ] is True,
            "scratch-restart independent closure changed")
    require(restart[
                "physical_usb_disconnect_while_markers_present_tested"
            ] is False and
            restart["mid_command_interruption_tested"] is False and
            restart["power_loss_during_mutation_tested"] is False and
            restart["arbitrary_torn_nor_recovery_tested"] is False and
            restart["automatic_retry_tested"] is False and
            restart["f6_19_tested"] is False and
            restart["above_16mib_mutation_tested"] is False and
            restart["firmware_region_mutation_tested"] is False and
            restart["custom_firmware_booted"] is False,
            "do not broaden the scratch-restart proof boundary")

    executor = stock["usb_updater_scratch_executor_validation"]
    require(executor["device_count"] == 1 and
            executor["manifest_header_version"] == "v1.0.00" and
            executor["loader_window_sha256"] ==
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56" and
            executor["fixed_plan_sha256"] ==
            "491b06c1beb66fa606639e1d420109dcf856c91b50ad02d5fbd0e6bafe1cc797" and
            executor["source_scratch_plan_sha256"] ==
            "d784f036e06a972d9688d15c76a41cbd7e90ca806d5ced1aeab5aae16745085b",
            "unexpected scratch-executor device, loader, or plan identity")
    require(executor["baseline_capture_count"] == 2 and
            executor["baseline_captures_bit_identical"] is True and
            executor["baseline_size_bytes"] == 0x02000000 and
            executor["baseline_sha256"] ==
            "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f" and
            executor["containment_envelope_start"] == "0x000c0000" and
            executor["containment_envelope_end_exclusive"] == "0x00100000",
            "scratch-executor baseline or containment evidence changed")
    require(executor["address_mode_command_before_each_mutation"] == "f6 18" and
            executor["operation_count"] == 22 and
            executor["program_operation_count"] == 18 and
            executor["erase_operation_count"] == 4 and
            executor["one_state_derived_operation_per_process"] is True and
            executor["all_operation_preflight_reads_exact"] is True and
            executor["all_operation_postflight_reads_exact"] is True and
            executor["automatic_retry"] is False,
            "scratch-executor fixed operation protocol changed")
    require(executor["initial_preflight_read_count"] == 2 and
            executor["initial_preflight_classification"] ==
            "exact_stock_or_complete" and
            executor["initial_boundary_index"] == 0 and
            executor["final_step_classification"] ==
            "exact_baseline_restored_pending_finalize" and
            executor["final_step_boundary_index"] == 22 and
            executor["final_step_sha256"] == executor["baseline_sha256"],
            "scratch-executor initial or final boundary evidence changed")
    require(executor["final_reconciliation_in_new_process"] is True and
            executor["final_reconciliation_read_count"] == 2 and
            executor["final_reconciliation_classification"] ==
            "exact_stock_or_complete" and
            executor["final_reconciliation_state_cleared"] is True and
            executor["active_intent_reconciliation_tested"] is False and
            executor["separate_post_cycle_verifier_capture_size_bytes"] ==
            0x02000000 and
            executor["separate_post_cycle_verifier_capture_sha256"] ==
            executor["baseline_sha256"] and
            executor["separate_post_cycle_verifier_capture_matches_baseline"] is True and
            executor["separate_post_cycle_manifest_region_checksums_passed"] is True and
            executor["post_test_normal_operation_owner_confirmed"] is True and
            executor["post_test_5038_enumeration_transcript_captured"] is False and
            executor["post_test_keyboard_working_owner_confirmed"] is True,
            "scratch-executor reconciliation or post-cycle closure changed")
    require(executor["physical_mid_command_interruption_tested"] is False and
            executor["power_loss_during_mutation_tested"] is False and
            executor["arbitrary_torn_nor_recovery_tested"] is False and
            executor["above_16mib_f6_17_mutation_path_tested"] is False and
            executor["f6_19_mutation_tested"] is False and
            executor["above_16mib_mutation_tested"] is False and
            executor["firmware_region_mutation_enabled"] is False and
            executor["firmware_region_mutation_tested"] is False and
            executor["production_updater_validated"] is False and
            executor["flash_approved"] is False and
            executor["custom_firmware_booted"] is False,
            "do not broaden the scratch-executor proof or authorization boundary")

    active = stock["usb_updater_scratch_active_intent_validation"]
    require(active["device_count"] == 1 and
            active["manifest_header_version"] == "v1.0.00" and
            active["loader_window_sha256"] ==
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56" and
            active["fixed_plan_sha256"] ==
            "f0a8acfcdc7ab5fb7a7dc2753ed8bdca0e381a9433f64fe311348442a8bbdb32" and
            active["source_scratch_plan_sha256"] ==
            "d784f036e06a972d9688d15c76a41cbd7e90ca806d5ced1aeab5aae16745085b",
            "unexpected active-intent executor device, loader, or plan identity")
    require(active["baseline_size_bytes"] == 0x02000000 and
            active["baseline_sha256"] ==
            "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f" and
            active["containment_envelope_start"] == "0x000c0000" and
            active["containment_envelope_end_exclusive"] == "0x00100000" and
            active["initial_preflight_read_count"] == 2 and
            active["initial_preflight_reads_bit_identical"] is True and
            active["initial_preflight_classification"] ==
            "exact_stock_or_complete" and
            active["initial_boundary_index"] == 0,
            "active-intent executor baseline or initial preflight changed")
    require(active["address_mode_command_before_each_mutation"] == "f6 18" and
            active["operation_count"] == 22 and
            active["program_operation_count"] == 18 and
            active["erase_operation_count"] == 4 and
            active["one_state_derived_operation_per_process"] is True,
            "active-intent executor fixed operation protocol changed")
    require(active["mandatory_checkpoint_operation"] == "program-09" and
            active["mandatory_checkpoint_input_boundary_index"] == 9 and
            active["mandatory_checkpoint_expected_post_boundary_index"] == 10 and
            active["mandatory_checkpoint_offset"] == "0x000c6000" and
            active["mandatory_checkpoint_length_bytes"] == 0x200 and
            active["mandatory_checkpoint_cdb"] ==
            "f6 06 00 60 0c 60 00 00 01 00 00 00 00 00 00 00" and
            active["mandatory_checkpoint_payload_sha256"] ==
            "ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380" and
            active["mandatory_checkpoint_operation_descriptor_sha256"] ==
            "dbba0199b94c9ee3fd8d50c9aaac37f33acead94d8ac299a793c3cc7f53d5455",
            "active-intent checkpoint command identity changed")
    require(active["mandatory_checkpoint_preimage_sha256"] ==
            "ea8f9c343781027db13ad221a63784fe52e4689f1543f10562ff7504c8b6f7b6" and
            active["mandatory_checkpoint_expected_postimage_sha256"] ==
            "f67fb2f28944d13d82ffcc7f15514558c757db0e6e0a0f261866043093afa3e7" and
            active["mandatory_checkpoint_intent_durable_before_command"] is True and
            active["mandatory_checkpoint_command_completed"] is True and
            active["mandatory_checkpoint_wip_poll_reported_ready"] is True and
            active["mandatory_checkpoint_same_session_postread_performed"] is False and
            active["mandatory_checkpoint_intent_left_active"] is True and
            active["mandatory_checkpoint_step_exit_code"] == 4,
            "active-intent checkpoint completion boundary changed")
    require(active["checkpoint_reconciliation_in_fresh_process"] is True and
            active["checkpoint_reconciliation_mutation_incapable_transport"] is True and
            active["checkpoint_reconciliation_read_count"] == 2 and
            active["checkpoint_reconciliation_reads_bit_identical"] is True and
            active["checkpoint_reconciliation_classification"] ==
            "exact_postimage_completed" and
            active["checkpoint_reconciliation_observed_sha256"] ==
            active["mandatory_checkpoint_expected_postimage_sha256"] and
            active["checkpoint_reconciliation_boundary_index"] == 10 and
            active["checkpoint_reconciliation_next_operation"] == "program-10" and
            active["checkpoint_automatic_retry"] is False and
            active["checkpoint_command_replayed_during_reconciliation"] is False and
            active["checkpoint_exact_preimage_reconciliation_branch_tested"] is False and
            active["execution_continued_from_boundary_10"] is True,
            "active-intent fresh-process reconciliation evidence changed")
    require(active["final_step_classification"] ==
            "exact_baseline_restored_pending_finalize" and
            active["final_step_boundary_index"] == 22 and
            active["final_step_sha256"] == active["baseline_sha256"] and
            active["final_reconciliation_in_new_process"] is True and
            active["final_reconciliation_read_count"] == 2 and
            active["final_reconciliation_classification"] ==
            "exact_stock_or_complete" and
            active["final_reconciliation_state_cleared"] is True,
            "active-intent executor completion or state closure changed")
    require(active["separate_post_cycle_verifier_capture_size_bytes"] ==
            0x02000000 and
            active["separate_post_cycle_verifier_capture_sha256"] ==
            active["baseline_sha256"] and
            active["separate_post_cycle_verifier_capture_matches_baseline"] is True and
            active["separate_post_cycle_manifest_region_checksums_passed"] is True and
            active["separate_post_cycle_manifest_region_checksums"] == [
                {
                    "index": 0,
                    "declared": "0xc3f43a6f",
                    "computed": "0xc3f43a6f",
                    "matches": True,
                },
                {
                    "index": 1,
                    "declared": "0xc8ed2815",
                    "computed": "0xc8ed2815",
                    "matches": True,
                },
                {
                    "index": 2,
                    "declared": "0xaa83e9a3",
                    "computed": "0xaa83e9a3",
                    "matches": True,
                },
            ] and
            active["post_test_normal_boot_owner_confirmed"] is True and
            active["post_test_keyboard_working_owner_confirmed"] is True and
            active["post_test_5038_enumeration_transcript_captured"] is False,
            "active-intent final verifier or functional closure changed")
    require(active["physical_mid_command_interruption_tested"] is False and
            active["physical_power_cut_during_mutation_tested"] is False and
            active["arbitrary_torn_nor_recovery_tested"] is False and
            active["full_chip_read_address_mode_command"] == "f6 17" and
            active["above_16mib_f6_17_mutation_path_tested"] is False and
            active["f6_19_mutation_tested"] is False and
            active["above_16mib_mutation_tested"] is False and
            active["firmware_region_mutation_enabled"] is False and
            active["firmware_region_mutation_tested"] is False and
            active["custom_firmware_booted"] is False and
            active["general_usb_updater_validated"] is False and
            active["flash_approved"] is False and
            active[
                "all_usb_byte_verification_used_same_preserved_loader_f6_05_read_path"
            ] is True and
            active["independent_electrical_flash_verification_performed"] is False and
            active["raw_images_or_transcripts_included"] is False,
            "do not broaden the active-intent executor proof boundary")

    terminated = stock["usb_updater_scratch_host_termination_validation"]
    require(terminated["observed_on"] == "2026-08-23" and
            terminated["device_count"] == 1 and
            terminated["manifest_header_version"] == "v1.0.00" and
            terminated["loader_window_sha256"] ==
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56" and
            terminated["fixed_plan_sha256"] ==
            "c1aa9348e74d6d4590b0e9666a9daf83e5544c3b23292b3df217c34038d5b653" and
            terminated["source_scratch_plan_sha256"] ==
            "d784f036e06a972d9688d15c76a41cbd7e90ca806d5ced1aeab5aae16745085b",
            "unexpected host-termination executor device, loader, or plan identity")
    require(terminated["baseline_capture_count"] == 2 and
            terminated["baseline_captures_bit_identical"] is True and
            terminated["baseline_size_bytes"] == 0x02000000 and
            terminated["baseline_sha256"] ==
            "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f" and
            terminated["containment_envelope_start"] == "0x000c0000" and
            terminated["containment_envelope_end_exclusive"] == "0x00100000" and
            terminated["initial_preflight_read_count"] == 2 and
            terminated["initial_preflight_reads_bit_identical"] is True and
            terminated["initial_preflight_classification"] ==
            "exact_stock_or_complete" and
            terminated["initial_boundary_index"] == 0,
            "host-termination baseline or initial preflight evidence changed")
    require(terminated["address_mode_command_before_each_mutation"] == "f6 18" and
            terminated["operation_count"] == 22 and
            terminated["program_operation_count"] == 18 and
            terminated["erase_operation_count"] == 4 and
            terminated["one_state_derived_operation_per_process"] is True,
            "host-termination fixed operation protocol changed")
    require(terminated["mandatory_checkpoint_operation"] == "program-09" and
            terminated["mandatory_checkpoint_input_boundary_index"] == 9 and
            terminated["mandatory_checkpoint_expected_post_boundary_index"] == 10 and
            terminated["mandatory_checkpoint_offset"] == "0x000c6000" and
            terminated["mandatory_checkpoint_length_bytes"] == 0x200 and
            terminated["mandatory_checkpoint_cdb"] ==
            "f6 06 00 60 0c 60 00 00 01 00 00 00 00 00 00 00" and
            terminated["mandatory_checkpoint_payload_sha256"] ==
            "ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380" and
            terminated["mandatory_checkpoint_operation_descriptor_sha256"] ==
            "dbba0199b94c9ee3fd8d50c9aaac37f33acead94d8ac299a793c3cc7f53d5455",
            "host-termination checkpoint command identity changed")
    require(terminated["mandatory_checkpoint_preimage_sha256"] ==
            "ea8f9c343781027db13ad221a63784fe52e4689f1543f10562ff7504c8b6f7b6" and
            terminated["mandatory_checkpoint_expected_postimage_sha256"] ==
            "f67fb2f28944d13d82ffcc7f15514558c757db0e6e0a0f261866043093afa3e7" and
            terminated["mandatory_checkpoint_intent_durable_before_backend_or_usb"] is True and
            terminated["mandatory_checkpoint_program_csw_validated"] is True and
            terminated[
                "mandatory_checkpoint_command_complete_state_durable_and_read_back"
            ] is True and
            terminated["mandatory_checkpoint_same_session_wip_poll_performed"] is False and
            terminated["mandatory_checkpoint_same_session_postread_performed"] is False and
            terminated["mandatory_checkpoint_explicit_usb_close_performed"] is False and
            terminated["mandatory_checkpoint_self_signal"] == 9 and
            terminated["mandatory_checkpoint_shell_status"] == 137 and
            terminated[
                "mandatory_checkpoint_shell_status_operator_observed_not_journal_bound"
            ] is True,
            "host-termination checkpoint boundary evidence changed")
    require(terminated["duplicate_checkpoint_step_rejected_before_usb"] is True and
            terminated["local_inspection_status"] ==
            "checkpoint_command_complete" and
            terminated["local_inspection_usb_opened"] is False,
            "host-termination duplicate-step or local-inspection gate changed")
    require(terminated["checkpoint_reconciliation_in_fresh_process"] is True and
            terminated[
                "checkpoint_reconciliation_mutation_incapable_transport"
            ] is True and
            terminated["checkpoint_reconciliation_wip_poll_completed"] is True and
            terminated["checkpoint_reconciliation_read_count"] == 2 and
            terminated["checkpoint_reconciliation_reads_bit_identical"] is True and
            terminated["checkpoint_reconciliation_classification"] ==
            "exact_postimage_completed" and
            terminated["checkpoint_reconciliation_observed_sha256"] ==
            terminated["mandatory_checkpoint_expected_postimage_sha256"] and
            terminated["checkpoint_reconciliation_boundary_index"] == 10 and
            terminated["checkpoint_reconciliation_next_operation"] == "program-10" and
            terminated["checkpoint_automatic_retry"] is False and
            terminated["checkpoint_command_replayed_during_reconciliation"] is False and
            terminated["checkpoint_exact_preimage_reconciliation_branch_tested"] is False and
            terminated["execution_continued_from_boundary_10"] is True,
            "host-termination fresh-process reconciliation evidence changed")
    require(terminated["final_step_classification"] ==
            "exact_baseline_restored_pending_finalize" and
            terminated["final_step_boundary_index"] == 22 and
            terminated["final_step_sha256"] == terminated["baseline_sha256"] and
            terminated["final_reconciliation_in_new_process"] is True and
            terminated["final_reconciliation_read_count"] == 2 and
            terminated["final_reconciliation_classification"] ==
            "exact_stock_or_complete" and
            terminated["final_reconciliation_wip_poll_completed"] is False and
            terminated["final_reconciliation_state_cleared"] is True,
            "host-termination completion or state closure changed")
    require(terminated["separate_post_cycle_verifier_capture_size_bytes"] ==
            0x02000000 and
            terminated["separate_post_cycle_verifier_capture_sha256"] ==
            terminated["baseline_sha256"] and
            terminated["separate_post_cycle_verifier_capture_matches_baseline"] is True and
            terminated["separate_post_cycle_manifest_region_checksums_passed"] is True and
            terminated["separate_post_cycle_manifest_region_checksums"] == [
                {
                    "index": 0,
                    "declared": "0xc3f43a6f",
                    "computed": "0xc3f43a6f",
                    "matches": True,
                },
                {
                    "index": 1,
                    "declared": "0xc8ed2815",
                    "computed": "0xc8ed2815",
                    "matches": True,
                },
                {
                    "index": 2,
                    "declared": "0xaa83e9a3",
                    "computed": "0xaa83e9a3",
                    "matches": True,
                },
            ] and
            terminated["post_test_normal_boot_owner_confirmed"] is True and
            terminated["post_test_5038_enumeration_owner_confirmed"] is True and
            terminated["post_test_5038_enumeration_transcript_captured"] is False and
            terminated["post_test_keyboard_working_owner_confirmed"] is True,
            "host-termination final verifier or functional closure changed")
    require(terminated["wip_busy_observed_at_termination"] is False and
            terminated["physical_usb_disconnect_during_checkpoint_tested"] is False and
            terminated["physical_mid_command_interruption_tested"] is False and
            terminated["physical_power_cut_during_mutation_tested"] is False and
            terminated["partial_cbw_or_data_out_interruption_tested"] is False and
            terminated["missing_or_interrupted_csw_tested"] is False and
            terminated["arbitrary_torn_nor_recovery_tested"] is False and
            terminated["full_chip_read_address_mode_command"] == "f6 17" and
            terminated["above_16mib_f6_17_mutation_path_tested"] is False and
            terminated["f6_19_mutation_tested"] is False and
            terminated["above_16mib_mutation_tested"] is False and
            terminated["firmware_region_mutation_enabled"] is False and
            terminated["firmware_region_mutation_tested"] is False and
            terminated["custom_firmware_booted"] is False and
            terminated["general_usb_updater_validated"] is False and
            terminated["flash_approved"] is False and
            terminated[
                "all_usb_byte_verification_used_same_preserved_loader_f6_05_read_path"
            ] is True and
            terminated["independent_electrical_flash_verification_performed"] is False and
            terminated["raw_images_or_transcripts_included"] is False,
            "do not broaden the host-termination proof boundary")

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


def validate_loader_reentry(evidence: dict[str, object]) -> None:
    require(evidence["schema"] ==
            "kb7.hardware.stock-loader-reentry-static-analysis" and
            evidence["schema_version"] == 5 and
            evidence["analyzed_on"] == "2026-08-23" and
            evidence["evidence_class"] == "firmware_recovery",
            "unexpected stock loader-reentry evidence identity")

    mailbox = evidence["mailbox"]
    require(mailbox == {
        "address": "0x20000ffc",
        "value": "0x73207320",
        "loader_clears_twice": True,
        "loader_verifies_clear": True,
    }, "stock loader mailbox semantics changed")

    relocation = evidence["stock_relocation"]
    require(relocation == {
        "source_start": "0x60001000",
        "destination_start": "0x00000000",
        "copy_bytes": 0x10000,
        "executes_outside_pram": True,
        "interrupts_disabled": True,
        "aircr_address": "0xe000ed0c",
        "aircr_expression": "(AIRCR & 0x00000700) | 0x05fa0004",
        "trampoline_bytes": 88,
        "trampoline_sha256":
            "570dc848c53aad3d18ae090580c2dd0687f7273c22693b4860e18dbf99a46315",
        "identical_in_all_analyzed_releases": True,
    }, "stock loader relocation semantics changed")

    releases = evidence["releases"]
    require(isinstance(releases, list) and len(releases) == 3,
            "loader-reentry evidence must retain three releases")
    require([
        (
            release["version"], release["core1_size_bytes"],
            release["core1_sha256"], release["loader_size_bytes"],
            release["loader_sha256"], release["request_handler_offset"],
            release["request_marker_write_offset"], release["marker_poll_offset"],
            release["relocation_wrapper_offset"], release["stock_trampoline_offset"],
            release["loader_marker_consumer_offset"],
            release["loader_marker_call_offset"],
            release["marker_updater_call_offset"],
            release["app_failure_updater_call_offset"],
            release["loader_updater_offset"],
        )
        for release in releases
    ] == [
        (
            "V1.22", 438632,
            "b2869bc657ba896474e760f513e4514fac678a951364efc29cbf9b6bb5e2ba72",
            61440,
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56",
            "0x000581fc", "0x00058230", "0x0004a740", "0x00019a98",
            "0x00059158", "0x000047ec", "0x00005922", "0x00005934",
            "0x0000594c", "0x0000a5c0",
        ),
        (
            "V1.24", 439372,
            "dcb06f976dcaff81d0c5ccd1fdfebcb5b6ca4ec3d7e003ad1e90f896a4139aa7",
            61440,
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56",
            "0x000584e0", "0x00058514", "0x0004a9dc", "0x00019cdc",
            "0x0005943c", "0x000047ec", "0x00005922", "0x00005934",
            "0x0000594c", "0x0000a5c0",
        ),
        (
            "V1.33", 487404,
            "d64df057dbdd125b12f156b57de5ad75a9a0d5804e30a16bb9ef1a56830d101f",
            61440,
            "453753e431609116e303a12548ec21c2efd500af4569034bd7947eb5bf43b298",
            "0x000626f8", "0x0006272c", "0x000545aa", "0x00022ee0",
            "0x00063a98", "0x000047ec", "0x00005922", "0x00005964",
            "0x0000597c", "0x0000a5f0",
        ),
    ], "loader-reentry release identity or offsets changed")

    proof = evidence["custom_offline_proof"]
    require(proof["feature_gate"] == "KB7_ENABLE_UNVERIFIED_LOADER_REENTRY" and
            proof["feature_gate_default"] is False and
            proof["proof_profile"] == "KB7_BUILD_LOADER_REENTRY_PROOF" and
            proof["proof_profile_default"] is False and
            proof["enters_before_application_main"] is True and
            proof["core1_started"] is False and
            proof["flash_mutation_code_reachable"] is False and
            proof["usb_device_init_code_reachable"] is False and
            proof["stackless_relocator_bytes"] == 84 and
            proof["stackless_relocator_sha256"] ==
            "a8c82aa423cc089a563fed7bf2f319f39b2945addf065b47849c04c4d7c793eb" and
            proof["stackless_relocator_modifies_sp"] is False and
            proof["linker_symbol_distance_uses_checked_integer_addresses"] is True and
            proof["trampoline_bytes"] == 72 and
            proof["trampoline_sha256"] ==
            "43bde11ee9089c930b8e67c6b7d569aec736d719f59f24c6b207d80309a2f539" and
            proof["allocated_code_relocation_count"] == 0 and
            proof["stack_reserve_bytes"] == 256 and
            proof["minimum_live_stack_gap_bytes"] == 64 and
            proof["mailbox_readback_before_relocation"] is True and
            proof["planner_balancing_required"] is True,
            "custom offline loader-reentry proof changed")
    require(proof["hardware_validated"] is False and
            proof["checksum_valid_custom_pair_booted"] is False and
            proof["preserved_loader_enumerated_from_custom_stage"] is False and
            proof["immutable_loader_readback_after_custom_install_verified"] is False and
            proof["paired_firmware_write_authorized"] is False and
            proof["flash_approved"] is False,
            "offline loader-reentry evidence must not authorize hardware")

    campaign = evidence["fixed_install_restore_campaign"]
    require(
        campaign["status"] ==
        "read_only_preflight_passed_fixed_proof_hardware_reauthorized_unrun" and
        campaign["campaign_tool"] ==
        "tools/flash-access/kb7-loader-reentry-campaign.py" and
        campaign["executor_tool"] ==
        "tools/flash-access/kb7-loader-reentry-executor.py" and
        campaign["campaign_format"] ==
        "KB7 V1.22 fixed loader-reentry proof campaign v1" and
        campaign["journal_schema"] ==
        "kb7-loader-reentry-proof-journal-v1" and
        campaign["expected_baseline_sha256"] ==
        "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f" and
        campaign["proof_core0_raw"] == {
            "entry": "0x00000175",
            "length": 1228,
            "sha256":
                "dde05f5274952a30afb0d315ab21628da8ab0361b17aab9906f84216d364656c",
        },
        "fixed proof campaign identity changed")
    require(campaign["stable_proof_target"] == {
        "core0": "checksum-valid minimal loader-reentry proof",
        "core1": "exact stock V1.22 Core1",
        "header_loader_manifest": "exact stock V1.22",
        "proof_full_sha256":
            "d08e8e32af512abf0d2a73248f88d08a5520348af64ad699a67194ee3db40bac",
        "core0_target_sha256":
            "e743e967cf33d6de25c5494693e61c2dd00ee19d5bf169edfefcb1b30f3d2fa2",
        "core0_envelope_sha256":
            "5b05b5e03d6c803d8b43d89d1a9f724f06b6e94d0c980d82df636c5684ff7b8a",
    }, "fixed proof stable target changed")
    require(campaign["mutation_domain"] == {
        "core0_envelope": ["0x00011000", "0x00021000"],
        "temporary_core1_barrier_sector_count": 1,
        "temporary_core1_barrier_sector": "0x00022000",
        "header_loader_manifest_operation_count": 0,
        "all_flash_after_core1_operation_count": 0,
    }, "fixed proof mutation domain changed")
    safety = campaign["safety_model"]
    require(all(safety[key] is True for key in (
        "core0_poisoned_before_core1",
        "opposite_core_checksum_invalid_during_staging",
        "core1_restored_exact_before_core0_commit",
        "one_operation_per_cli_invocation",
        "durable_terminal_intent_before_backend_or_usb",
        "two_exact_full_chip_reads_before_and_after_each_mutation",
        "strict_close_before_authorizing_publication",
        "reattach_not_found_or_busy_accepted_only_if_kernel_driver_is_active",
    )) and safety["final_core0_gate_rank"] == 32 and
        safety["automatic_retry"] is False and
        safety["ordinary_intent_usb_reconciliation"] is False and
        safety["read_only_preflight_transport_or_close_anomaly"] ==
        "no_flash_mutation_power_cycle_before_new_journal" and
        safety["read_only_preflight_image_verification_anomaly"] ==
        "external_spi_verify_no_automatic_write" and
        safety["post_intent_transport_or_verification_anomaly"] ==
        "external_spi_no_further_usb",
        "fixed proof safety policy changed")
    authorization = campaign["authorization"]
    require(
        authorization["live_read_only_preflight_enabled"] is True and
        authorization["live_proof_campaign_enabled"] is True and
        authorization["read_only_preflight_diagnostic_authorized"] is True and
        authorization["fixed_proof_hardware_test_authorized"] is True and
        authorization["execution_authorized"] is True and
        authorization["authorization_scope"] ==
        "one fixed proof install and exact stock restore" and
        authorization["expected_campaign_id"] ==
        "3fa076a69bb04ab2ef11c9369d80976e293d1d57a52ddeb63f9d8d71b004d82f" and
        authorization["owner_campaign_generated"] is True and
        authorization["owner_campaign_independently_reverified"] is True and
        authorization["two_owner_baselines_distinct_and_byte_identical"] is True and
        authorization["supporting_source_hashes_pinned"] is True and
        authorization["implementation_source_sha256"] == {
            "campaign":
                "085dd0c2087e258d880824f657e37ecde08f4fd05234ab14d948af245d8de765",
            "planner":
                "618bed76c236390c8203ef5395db2317dfce9cce620035bda05231fc05727d0a",
            "verifier":
                "9b19d393cf64c66168e08de2f3d4fe352a85a2fd69545e374dee0fa015dea338",
            "writer":
                "f706cb355297e4b010fd49f10a1c0e68834d73e99a33005780046ced4e1dc6e5",
        } and
        authorization["policy_sha256"] ==
        "8ba06722fdab35dc5cfa9f374518e51a5fa6b54444fc29d5b4ac376672a786ac" and
        authorization["executor_descriptor_sha256"] ==
        "47f643305883ef6341b12e7fd8878b46d54a76039601759b3a8fdd95b4d3c3ff" and
        authorization["executor_source_sha256"] ==
        "208f5773edca7caea9fe4b88e250f822f8af6c666dd82372ce7f52323ffb195c" and
        authorization["generic_firmware_executor_mutation_enabled"] is False and
        authorization["flash_approved"] is False,
        "fixed proof campaign authorization changed")
    offline = campaign["offline_validation"]
    require(offline["focused_campaign_and_executor_tests_passed"] == 38 and
            offline["exact_campaign_operation_count"] == 168 and
            offline["install_operation_count"] == 32 and
            offline["restore_operation_count"] == 136 and
            offline["program_operation_count"] == 148 and
            offline["erase_operation_count"] == 20 and
            offline["core1_barrier_operation_count"] == 20 and
            offline["preserved_boot_region_operation_count"] == 0 and
            offline["command_boundaries_checked"] == 169 and
            offline["modeled_byte_prefix_states_checked"] == 157528 and
            offline["opposite_barrier_prefix_states_checked"] == 154462 and
            offline["single_bit_poison_prefix_states_checked"] == 2044 and
            offline["sparse_gate_subset_proofs"] == 2 and
            offline["early_loader_valid_non_target_states"] == 0 and
            all(offline[key] is True for key in (
                "canonical_internal_cdbs_and_payload_hashes_reverified",
                "install_target_exact_proof_full_image",
                "install_then_restore_exact_full_baseline",
                "symbolic_poison_prefix_model",
                "opposite_core_barrier_prefix_model",
                "rank32_final_gate_subset_proof",
                "fault_and_atomic_journal_matrix",
                "private_artifact_publication_guards",
            )), "fixed proof offline validation changed")
    require(campaign["hardware_validation"] == {
        "read_only_preflight_attempt_count": 2,
        "read_only_preflight_attempted": True,
        "read_only_preflight_reached_boundary_zero": True,
        "read_only_preflight_reported_two_complete_full_chip_reads": True,
        "revised_read_only_preflight_passed": True,
        "revised_read_only_preflight_exact_baseline_verified": True,
        "revised_read_only_preflight_strict_close_passed": True,
        "revised_read_only_preflight_journal_status": "boundary_verified",
        "revised_read_only_preflight_boundary_index": 0,
        "revised_read_only_preflight_device_path": "3-2.2",
        "revised_read_only_preflight_usb_address": 9,
        "revised_read_only_preflight_executor_source_sha256":
            "e43f65a91755458b257230be042029fd0a7bf75eb7f9629a6986a5757f678dd3",
        "revised_read_only_preflight_descriptor_sha256":
            "bacdb380a9b49d25f314d4172813d0174d6a533e74bb0861304fde84f448a37a",
        "revised_read_only_preflight_loader_fingerprint_sha256":
            "99e75493ef2f627b072560ef7ee45f3c01648eca715ce03a4001727eace9e7c6",
        "revised_read_only_preflight_normal_5038_boot_confirmed": True,
        "revised_read_only_preflight_spi_required": False,
        "read_only_preflight_exact_failure_phase_observed": False,
        "read_only_preflight_underlying_error_observed": False,
        "preflight_terminal_marker_observed": True,
        "program_or_erase_command_possible_in_preflight": False,
        "kernel_disconnect_or_reenumeration_observed_during_preflight": False,
        "external_spi_full_chip_read_count_after_stop": 2,
        "external_spi_reads_match_each_other": True,
        "external_spi_reads_match_exact_baseline": True,
        "external_spi_write_required": False,
        "proof_install_attempted": False,
        "checksum_valid_proof_core0_booted": False,
        "preserved_loader_reenumerated": False,
        "proof_image_readback_verified": False,
        "stock_restore_attempted": False,
        "exact_full_baseline_restored": False,
        "normal_5038_keyboard_operation_restored": True,
        "old_preflight_root_cause_known": False,
        "leading_hypothesis": (
            "host-side strict-close or kernel-driver reattachment result; "
            "not proven"),
    }, "fixed proof campaign hardware incident status changed")

    require(evidence["planner_immutability"] == {
        "header": ["0x00000000", "0x00001000"],
        "loader": ["0x00001000", "0x00010000"],
        "manifest": ["0x00010000", "0x00011000"],
        "operation_count_over_all_three_regions": 0,
        "checked_at_every_modeled_operation_boundary": True,
    }, "preserved boot-region geometry changed")
    require(evidence["raw_vendor_bytes_included"] is False,
            "loader-reentry facts must not contain raw vendor bytes")


def main() -> int:
    try:
        validate_soc(load("snc7320-soc.json"))
        validate_pin_map(load("kb7-pin-map.json"))
        validate_stock_flash(load("kb7-stock-flash.json"))
        validate_loader_reentry(load("kb7-stock-loader-reentry.json"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"hardware facts check: {error}")
        return 1
    print("hardware facts check: SoC, IRQ, package, stock-flash, and "
          "loader-reentry mappings pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
