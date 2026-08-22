#!/usr/bin/env python3
"""Inspect a complete 32-MiB KB7 SPI-NOR read without modifying it.

The report deliberately contains hashes, offsets, lengths, and parsed framing
facts rather than proprietary payload bytes, so it can be retained alongside
the clean-room firmware sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any

FLASH_BYTES = 0x02000000
FLASH_XIP_BASE = 0x60000000
SECTOR_BYTES = 0x1000
MANIFEST_OFFSET = 0x10000
MANIFEST_MAGIC = b"SN_FWIN\0v1.0.00\0"
MANIFEST_ENTRY_OFFSET = 0x20
MANIFEST_ENTRY_COUNT = 4
MANIFEST_ENTRY = struct.Struct("<IIII")
CONFIG_BANKS = (0x01800000, 0x01A00000)
BOOT_CONFIGURATION_OFFSET = 0x200


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def vendor_checksum(data: bytes) -> int:
    """Recovered manifest checksum: sum of CRC-32 for each 64-KiB chunk."""

    return sum(zlib.crc32(data[offset:offset + 0x10000]) & 0xFFFFFFFF
               for offset in range(0, len(data), 0x10000)) & 0xFFFFFFFF


def hex32(value: int) -> str:
    return f"0x{value:08x}"


def manifest_report(image: bytes) -> dict[str, Any]:
    manifest = image[MANIFEST_OFFSET:MANIFEST_OFFSET + SECTOR_BYTES]
    if manifest[:len(MANIFEST_MAGIC)] != MANIFEST_MAGIC:
        raise ValueError("SN_FWIN v1.0.00 manifest not found at flash offset 0x10000")
    entries = []
    for index in range(MANIFEST_ENTRY_COUNT):
        entry_offset = MANIFEST_ENTRY_OFFSET + index * MANIFEST_ENTRY.size
        load, storage, length, stored_checksum = MANIFEST_ENTRY.unpack_from(
            manifest, entry_offset)
        if length == 0:
            continue
        if not FLASH_XIP_BASE <= storage < FLASH_XIP_BASE + FLASH_BYTES:
            raise ValueError(f"manifest region {index} has an invalid storage address")
        flash_offset = storage - FLASH_XIP_BASE
        if length > FLASH_BYTES - flash_offset:
            raise ValueError(f"manifest region {index} extends beyond the flash")
        payload = image[flash_offset:flash_offset + length]
        calculated = vendor_checksum(payload)
        entries.append({
            "index": index,
            "load_address": hex32(load),
            "storage_address": hex32(storage),
            "flash_offset": hex32(flash_offset),
            "length": hex32(length),
            "end_exclusive": hex32(flash_offset + length),
            "stored_checksum": hex32(stored_checksum),
            "calculated_checksum": hex32(calculated),
            "checksum_matches": calculated == stored_checksum,
            "sha256": sha256(payload),
        })
    return {
        "offset": hex32(MANIFEST_OFFSET),
        "sha256": sha256(manifest),
        "format": manifest[:16].rstrip(b"\0").decode("ascii"),
        "entries": entries,
    }


def boot_configuration_report(image: bytes) -> dict[str, Any]:
    header = image[BOOT_CONFIGURATION_OFFSET:BOOT_CONFIGURATION_OFFSET + 16]
    primary, secondary = struct.unpack_from("<II", header, 8)
    return {
        "offset": hex32(BOOT_CONFIGURATION_OFFSET),
        "magic": header[:8].rstrip(b"\0").decode("ascii", errors="replace"),
        "primary_manifest_address": hex32(primary),
        "primary_manifest_flash_offset":
            hex32(primary - FLASH_XIP_BASE)
            if FLASH_XIP_BASE <= primary < FLASH_XIP_BASE + FLASH_BYTES else None,
        "secondary_manifest_address": hex32(secondary),
    }


def non_erased_ranges(image: bytes, start: int = 0, end: int = FLASH_BYTES) -> list[dict[str, Any]]:
    if start % SECTOR_BYTES or end % SECTOR_BYTES:
        raise ValueError("sector scan range must be 4-KiB aligned")
    ranges: list[dict[str, Any]] = []
    run_start: int | None = None
    for offset in range(start, end, SECTOR_BYTES):
        programmed = image[offset:offset + SECTOR_BYTES] != b"\xff" * SECTOR_BYTES
        if programmed and run_start is None:
            run_start = offset
        if not programmed and run_start is not None:
            ranges.append({
                "start": hex32(run_start),
                "end_exclusive": hex32(offset),
                "sector_count": (offset - run_start) // SECTOR_BYTES,
            })
            run_start = None
    if run_start is not None:
        ranges.append({
            "start": hex32(run_start),
            "end_exclusive": hex32(end),
            "sector_count": (end - run_start) // SECTOR_BYTES,
        })
    return ranges


def additive_u16_valid(record: bytes) -> bool:
    if len(record) < 2:
        return False
    return (sum(record[:-2]) & 0xFFFF) == int.from_bytes(record[-2:], "little")


def configuration_bank_report(image: bytes, base: int) -> dict[str, Any]:
    header = image[base:base + 32]
    result: dict[str, Any] = {
        "offset": hex32(base),
        "header_sha256": sha256(header),
        "header_magic": header[:2].hex(),
        "header_checksum_valid": additive_u16_valid(header),
    }
    if header[:2] == b"\xf5\x10":
        result.update({
            "header_version": header[2],
            "active_profile": header[3],
            "profile_count": header[4],
        })

    sectors = []
    for sector_index in range(1, 16):
        offset = base + sector_index * SECTOR_BYTES
        sector = image[offset:offset + SECTOR_BYTES]
        if sector == b"\xff" * SECTOR_BYTES:
            sectors.append({"index": sector_index, "offset": hex32(offset),
                            "state": "erased"})
            continue
        if sector == b"\0" * SECTOR_BYTES:
            sectors.append({"index": sector_index, "offset": hex32(offset),
                            "state": "zero-filled"})
            continue

        records = []
        cursor = 0
        # Stock has two closely related record headers. If the first record's
        # bytes 1..2 encode a size above 255, byte 3 is the profile index. For
        # smaller records byte 1 is the size and byte 2 is the profile index.
        # Infer the variant once from record zero; interpreting each later
        # profile header independently would mistake profile 1 for size +0x100.
        wide_length = int.from_bytes(sector[1:3], "little")
        if 0x100 <= wide_length <= SECTOR_BYTES:
            length = wide_length
            profile_byte = 3
        else:
            length = sector[1]
            profile_byte = 2
        while length >= 6 and cursor + length <= SECTOR_BYTES:
            remaining = sector[cursor:]
            if remaining == b"\xff" * len(remaining) or remaining == b"\0" * len(remaining):
                break
            record = sector[cursor:cursor + length]
            if record[0] != sector[0] or record[1] != sector[1]:
                break
            records.append({
                "offset_in_sector": hex32(cursor),
                "type": f"0x{record[0]:02x}",
                "length": length,
                "profile_index": record[profile_byte],
                "trailing_additive_checksum_matches": additive_u16_valid(record),
            })
            cursor += length
        sectors.append({
            "index": sector_index,
            "offset": hex32(offset),
            "state": "records" if records else "programmed-unparsed",
            "sha256": sha256(sector),
            "records": records,
        })
    result["sectors"] = sectors
    type20 = image[base + SECTOR_BYTES:base + 2 * SECTOR_BYTES]
    if type20[:2] == b"\x20\x5c":
        usages = [type20[index * 0x5c + 5:index * 0x5c + 90]
                  for index in range(5)]
        if all(len(item) == 85 for item in usages):
            result["type20_usage_table"] = {
                "entry_count": 85,
                "profile_copies": 5,
                "identical_across_profiles": len(set(usages)) == 1,
                "sha256": sha256(usages[0]),
            }

    # Active type-0x30 records are 8-byte headers, an 85-entry little-endian
    # u16 permutation, and a trailing additive checksum.  Preserve the naming
    # boundary here: the structure proves per-profile index remapping, but not
    # that the header's fourth byte is the MCU2 physical-layout selector.
    type30 = image[base + 9 * SECTOR_BYTES:base + 10 * SECTOR_BYTES]
    if type30[:2] == b"\x30\xb4":
        mappings = []
        for profile_index in range(5):
            record = type30[profile_index * 0xb4:(profile_index + 1) * 0xb4]
            if (len(record) != 0xb4 or record[:2] != b"\x30\xb4" or
                    record[2] != profile_index or
                    not additive_u16_valid(record)):
                mappings = []
                break
            values = [int.from_bytes(record[8 + index * 2:10 + index * 2], "little")
                      for index in range(85)]
            mappings.append({
                "profile_index": profile_index,
                "header_variant_byte": record[3],
                "is_permutation_0_through_84": sorted(values) == list(range(85)),
                "is_identity": values == list(range(85)),
                "changed_entries": [
                    {"index": index, "value": value}
                    for index, value in enumerate(values) if value != index
                ],
            })
        if mappings:
            result["type30_u16_permutation"] = {
                "entry_count": 85,
                "entry_width_bytes": 2,
                "profile_copies": 5,
                "mappings": mappings,
                "semantic_boundary":
                    "per-profile index remap; header byte 3 is not assumed to be "
                    "the MCU2 route-layout selector",
            }
    return result


def difference_ranges(left: bytes, right: bytes, base: int = 0) -> list[dict[str, Any]]:
    if len(left) != len(right):
        raise ValueError("comparison ranges must have equal lengths")
    ranges = []
    start: int | None = None
    for index, (a, b) in enumerate(zip(left, right, strict=True)):
        if a != b and start is None:
            start = index
        if a == b and start is not None:
            ranges.append({"start": hex32(base + start),
                           "end_exclusive": hex32(base + index),
                           "byte_count": index - start})
            start = None
    if start is not None:
        ranges.append({"start": hex32(base + start),
                       "end_exclusive": hex32(base + len(left)),
                       "byte_count": len(left) - start})
    return ranges


def reference_comparison_report(actual: bytes, reference: bytes, base: int,
                                stored_checksum: int) -> dict[str, Any]:
    ranges = difference_ranges(actual, reference, base)
    differing_indexes = [index for index, (actual_byte, reference_byte) in
                         enumerate(zip(actual, reference, strict=True))
                         if actual_byte != reference_byte]
    reference_checksum = vendor_checksum(reference)
    return {
        "reference_sha256": sha256(reference),
        "reference_vendor_checksum": hex32(reference_checksum),
        "reference_checksum_matches_manifest": reference_checksum == stored_checksum,
        "bit_identical": not ranges,
        "differing_byte_count": len(differing_indexes),
        "installed_differing_bytes_are_all_zero":
            all(actual[index] == 0 for index in differing_indexes),
        "difference_ranges": ranges,
    }


def inspect_image(image: bytes) -> dict[str, Any]:
    if len(image) != FLASH_BYTES:
        raise ValueError(f"expected exactly {FLASH_BYTES} bytes, got {len(image)}")
    return {
        "schema": "kb7-stock-flash-inspection-v1",
        "size": len(image),
        "sha256": sha256(image),
        "boot_header_magic": image[:8].decode("ascii", errors="replace"),
        "boot_configuration": boot_configuration_report(image),
        "manifest": manifest_report(image),
        "programmed_sector_ranges": non_erased_ranges(image),
        "configuration_banks": [configuration_bank_report(image, base)
                                for base in CONFIG_BANKS],
    }


def load_image(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) != FLASH_BYTES:
        raise ValueError(f"{path.name}: expected exactly {FLASH_BYTES} bytes, got {len(data)}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="complete 32-MiB SPI-NOR read")
    parser.add_argument("--compare", type=Path,
                        help="second complete read; fails if it is not byte-identical")
    parser.add_argument("--region2-reference", type=Path,
                        help="reference full image used only to compare manifest region 2")
    parser.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    args = parser.parse_args()

    image = load_image(args.image)
    report = inspect_image(image)
    report["source_name"] = args.image.name
    if args.compare is not None:
        comparison = load_image(args.compare)
        report["duplicate_read"] = {
            "source_name": args.compare.name,
            "sha256": sha256(comparison),
            "bit_identical": image == comparison,
        }
        if image != comparison:
            raise ValueError("the two complete flash reads are not byte-identical")

    if args.region2_reference is not None:
        region2 = next((entry for entry in report["manifest"]["entries"]
                        if entry["index"] == 2), None)
        if region2 is None:
            raise ValueError("manifest has no region 2")
        offset = int(region2["flash_offset"], 16)
        length = int(region2["length"], 16)
        reference = args.region2_reference.read_bytes()
        if len(reference) == length:
            reference_region = reference
        elif len(reference) >= offset + length:
            reference_region = reference[offset:offset + length]
        else:
            raise ValueError("region-2 reference is too short")
        actual_region = image[offset:offset + length]
        comparison = reference_comparison_report(
            actual_region, reference_region, offset,
            int(region2["stored_checksum"], 16))
        comparison["source_name"] = args.region2_reference.name
        report["region2_reference_comparison"] = comparison

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
