from __future__ import annotations

import importlib.util
import struct
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "inspect_stock_flash", ROOT / "tools/inspect_stock_flash.py")
assert SPEC is not None and SPEC.loader is not None
INSPECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSPECTOR)


class StockFlashInspectorTests(unittest.TestCase):
    def test_vendor_checksum_is_chunk_crc_sum(self) -> None:
        data = bytes(range(256)) * 300
        expected = ((zlib.crc32(data[:0x10000]) & 0xFFFFFFFF) +
                    (zlib.crc32(data[0x10000:]) & 0xFFFFFFFF)) & 0xFFFFFFFF
        self.assertEqual(INSPECTOR.vendor_checksum(data), expected)

    def test_manifest_and_five_profile_header_are_parsed(self) -> None:
        image = bytearray(b"\xff" * INSPECTOR.FLASH_BYTES)
        image[:8] = b"SNC7320A"
        image[INSPECTOR.BOOT_CONFIGURATION_OFFSET:
              INSPECTOR.BOOT_CONFIGURATION_OFFSET + 16] = (
                  b"SN_BCFG\0" + struct.pack("<II", 0x60010000, 0))
        manifest = INSPECTOR.MANIFEST_OFFSET
        image[manifest:manifest + INSPECTOR.SECTOR_BYTES] = b"\0" * INSPECTOR.SECTOR_BYTES
        image[manifest:manifest + len(INSPECTOR.MANIFEST_MAGIC)] = INSPECTOR.MANIFEST_MAGIC
        payload = b"test-payload"
        offset = 0x11000
        image[offset:offset + len(payload)] = payload
        struct.pack_into("<IIII", image, manifest + INSPECTOR.MANIFEST_ENTRY_OFFSET,
                         0, INSPECTOR.FLASH_XIP_BASE + offset, len(payload),
                         INSPECTOR.vendor_checksum(payload))

        header_offset = 0x1A00000
        header = bytearray(32)
        header[:5] = bytes((0xF5, 0x10, 1, 4, 5))
        header[-2:] = (sum(header[:-2]) & 0xFFFF).to_bytes(2, "little")
        image[header_offset:header_offset + len(header)] = header

        report = INSPECTOR.inspect_image(bytes(image))
        self.assertEqual(report["boot_configuration"]["primary_manifest_flash_offset"],
                         "0x00010000")
        entry = report["manifest"]["entries"][0]
        self.assertTrue(entry["checksum_matches"])
        bank = report["configuration_banks"][1]
        self.assertTrue(bank["header_checksum_valid"])
        self.assertEqual((bank["active_profile"], bank["profile_count"]), (4, 5))

    def test_difference_ranges_are_contiguous_and_absolute(self) -> None:
        ranges = INSPECTOR.difference_ranges(b"abcdefghi", b"abXXefgYY", 0x100)
        self.assertEqual(ranges, [
            {"start": "0x00000102", "end_exclusive": "0x00000104", "byte_count": 2},
            {"start": "0x00000107", "end_exclusive": "0x00000109", "byte_count": 2},
        ])

    def test_reference_comparison_checks_manifest_and_zeroed_differences(self) -> None:
        reference = b"\x01\x02\x03\x04"
        actual = b"\x00\x02\x00\x04"
        report = INSPECTOR.reference_comparison_report(
            actual, reference, 0x200, INSPECTOR.vendor_checksum(reference))
        self.assertTrue(report["reference_checksum_matches_manifest"])
        self.assertTrue(report["installed_differing_bytes_are_all_zero"])
        self.assertEqual(report["differing_byte_count"], 2)
        self.assertEqual(report["difference_ranges"], [
            {"start": "0x00000200", "end_exclusive": "0x00000201", "byte_count": 1},
            {"start": "0x00000202", "end_exclusive": "0x00000203", "byte_count": 1},
        ])

    def test_type30_five_profile_permutations_are_parsed(self) -> None:
        image = bytearray(b"\xff" * INSPECTOR.FLASH_BYTES)
        base = 0x1A00000 + 9 * INSPECTOR.SECTOR_BYTES
        for profile_index in range(5):
            record = bytearray(180)
            record[:8] = bytes((0x30, 0xB4, profile_index,
                                1 if profile_index == 0 else 0, 0, 0, 0, 0))
            values = list(range(85))
            if profile_index == 0:
                values[6], values[22] = values[22], values[6]
            for index, value in enumerate(values):
                struct.pack_into("<H", record, 8 + index * 2, value)
            record[-2:] = (sum(record[:-2]) & 0xFFFF).to_bytes(2, "little")
            start = base + profile_index * len(record)
            image[start:start + len(record)] = record

        bank = INSPECTOR.configuration_bank_report(bytes(image), 0x1A00000)
        mapping = bank["type30_u16_permutation"]
        self.assertEqual((mapping["entry_count"], mapping["profile_copies"]), (85, 5))
        self.assertEqual(mapping["mappings"][0]["changed_entries"], [
            {"index": 6, "value": 22},
            {"index": 22, "value": 6},
        ])
        self.assertTrue(all(item["is_identity"]
                            for item in mapping["mappings"][1:]))


if __name__ == "__main__":
    unittest.main()
