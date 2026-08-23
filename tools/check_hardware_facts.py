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
