#!/usr/bin/env python3
"""Build a legacy split-bundle audit artifact from the named ELFs.

The tool never creates a whole-flash image.  It preserves a hash-pinned stock
header/loader, changes only the two manifest checksum words, and emits an exact
sector plan which excludes the recovery and asset regions.  That manifest-last
model is superseded and MUST NOT be executed.  Use the offline-only
flash-access/kb7-updater-plan.py for the current manifest-preserving design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path


class BundleError(ValueError):
    pass


STOCK_FILES = {
    "header": ("KB7_V1.22-header_0x0-0x1000.bin", "70d8c190dabfeab8ff75395131dc2ae89c279d95c967bfc9102f961f79a68af3"),
    "loader": ("KB7_V1.22-loader.bin", "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56"),
    "manifest": ("KB7_V1.22-manifest_0x10000-0x11000.bin", "a945368195d825160ebfdd49e5f96581334da3205e0c3bd924e17fb5a7940590"),
    "core0": ("KB7_V1.22-core0.bin", "d779faf9f591e71602e5f17e966ac366602699a83fb5e612534d694d3dafd153"),
    "core1": ("KB7_V1.22-core1.bin", "b2869bc657ba896474e760f513e4514fac678a951364efc29cbf9b6bb5e2ba72"),
}
FLASH_BASE = 0x60000000
MANIFEST_OFFSET = 0x10000
REGION2_START = 0x100000
REGION2_END = 0x156AF8C
CORE0_VMA = 0x00000000
CORE1_VMA = 0x10000000
CORE0_STACK = 0x1803F5C0


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BundleError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fwin_checksum(data: bytes) -> int:
    return sum(zlib.crc32(data[pos:pos + 0x10000]) & 0xFFFFFFFF
               for pos in range(0, len(data), 0x10000)) & 0xFFFFFFFF


def run(arguments: list[str]) -> str:
    result = subprocess.run(arguments, text=True, capture_output=True, check=False)
    require(result.returncode == 0,
            f"command failed ({result.returncode}): {' '.join(arguments)}\n{result.stderr}")
    return result.stdout


def validate_load_ranges(program_headers: str, expected_vma: int,
                         maximum: int) -> int:
    """Validate every file-backed LOAD range used by objcopy's binary image.

    ELF data sections may run from SRAM while loading from the image region, so
    the physical/load address is the relevant address for split-flash layout.
    """
    pattern = re.compile(
        r"^\s*LOAD\s+0x[0-9a-fA-F]+\s+"
        r"(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+"
        r"(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)", re.MULTILINE)
    ranges: list[tuple[int, int]] = []
    for match in pattern.finditer(program_headers):
        _virtual, physical, file_size, memory_size = (
            int(value, 16) for value in match.groups())
        require(file_size <= memory_size, "ELF LOAD file size exceeds memory size")
        if file_size == 0:
            continue
        end = physical + file_size
        require(end > physical and expected_vma <= physical and
                end <= expected_vma + maximum,
                "ELF has file-backed LOAD bytes outside its manifest region")
        ranges.append((physical, end))
    require(ranges, "ELF has no file-backed LOAD segment")
    ranges.sort()
    require(ranges[0][0] == expected_vma,
            "ELF's lowest file-backed LOAD address does not equal its manifest VMA")
    for previous, current in zip(ranges, ranges[1:]):
        require(previous[1] <= current[0], "ELF file-backed LOAD ranges overlap")
    return max(end for _, end in ranges) - expected_vma


def load_stock(directory: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for role, (name, expected) in STOCK_FILES.items():
        path = directory / name
        require(path.is_file(), f"missing hash-pinned stock {role}: {path}")
        data = path.read_bytes()
        require(digest(data) == expected, f"stock {role} SHA-256 does not match V1.22 anchor")
        result[role] = data
    require(len(result["header"]) == 0x1000 and result["header"][:8] == b"SNC7320A",
            "invalid stock boot header")
    require(len(result["loader"]) == 0xF000, "invalid stock loader length")
    require(len(result["manifest"]) == 0x1000 and result["manifest"][:8] == b"SN_FWIN\0",
            "invalid stock manifest")
    return result


def manifest_regions(manifest: bytes) -> list[dict[str, int]]:
    regions = []
    for index, offset in enumerate((0x20, 0x30, 0x40, 0x50)):
        load, store, length, checksum = struct.unpack_from("<IIII", manifest, offset)
        regions.append({"index": index, "load": load, "store": store,
                        "length": length, "checksum": checksum})
    require(regions[0]["load"] == CORE0_VMA and regions[0]["store"] == 0x60011000,
            "unexpected core0 manifest mapping")
    require(regions[1]["load"] == CORE1_VMA and regions[1]["store"] == 0x60021000,
            "unexpected core1 manifest mapping")
    require(regions[2]["load"] == 0x60100000 and regions[2]["store"] == 0x60100000 and
            regions[2]["length"] == REGION2_END - REGION2_START,
            "unexpected asset-region mapping")
    require(regions[3]["length"] == 0, "manifest terminator is not empty")
    return regions


def inspect_and_extract(elf: Path, expected_vma: int, maximum: int,
                        objcopy: str, readelf: str, nm: str, destination: Path) -> dict[str, object]:
    require(elf.is_file(), f"missing ELF: {elf}")
    header = run([readelf, "-h", str(elf)])
    require("Machine:" in header and "ARM" in header, f"not an ARM ELF: {elf}")
    entry_line = next((line for line in header.splitlines() if "Entry point address:" in line), "")
    require(entry_line, f"ELF has no entry point: {elf}")
    entry = int(entry_line.rsplit(maxsplit=1)[1], 16)
    require(expected_vma <= (entry & ~1) < expected_vma + maximum,
            f"ELF entry is outside its manifest region: {elf}")
    require("There are no relocations" in run([readelf, "-r", str(elf)]),
            f"ELF contains relocations: {elf}")
    require(not run([nm, "-u", str(elf)]).strip(), f"ELF contains undefined symbols: {elf}")
    expected_raw_length = validate_load_ranges(
        run([readelf, "-lW", str(elf)]), expected_vma, maximum)
    run([objcopy, "-O", "binary", str(elf), str(destination)])
    raw = destination.read_bytes()
    require(raw and len(raw) == expected_raw_length and len(raw) <= maximum,
            f"ELF binary extent does not match its LOAD addresses: {elf}")
    return {"entry": f"0x{entry:08x}", "raw_length": len(raw),
            "elf_sha256": digest(elf.read_bytes()), "raw_sha256": digest(raw)}


def bounded_operation(offset: int, length: int) -> bool:
    end = offset + length
    if length <= 0 or end <= offset or end > 0x2000000:
        return False
    return not (offset < 0x10000 and 0 < end) and not (offset < REGION2_END and REGION2_START < end)


def sector_erase(offset: int, payload_length: int) -> dict[str, object]:
    require(offset % 0x1000 == 0 and payload_length > 0,
            "erase source range must start on a sector boundary and be non-empty")
    end = (offset + payload_length + 0xFFF) & ~0xFFF
    length = end - offset
    require(length % 0x1000 == 0 and bounded_operation(offset, length),
            "sector erase intersects a prohibited range")
    return {"operation": "erase", "offset": f"0x{offset:08x}", "length": length,
            "sector_size": 0x1000}


def build(stock_dir: Path, core0_elf: Path, core1_elf: Path, output: Path,
          prefix: str) -> dict[str, object]:
    require(output.parent.is_dir(), f"output parent does not exist: {output.parent}")
    require(not output.exists(), f"refusing to replace existing output: {output}")
    stock = load_stock(stock_dir)
    regions = manifest_regions(stock["manifest"])
    require(len(stock["core0"]) == regions[0]["length"] and
            fwin_checksum(stock["core0"]) == regions[0]["checksum"],
            "stock core0 does not match its manifest")
    require(len(stock["core1"]) == regions[1]["length"] and
            fwin_checksum(stock["core1"]) == regions[1]["checksum"],
            "stock core1 does not match its manifest")

    names = {name: shutil.which(f"{prefix}{name}") for name in ("objcopy", "readelf", "nm")}
    require(all(names.values()), f"missing ARM binutils for prefix {prefix!r}")
    with tempfile.TemporaryDirectory(prefix="kb7-bundle-", dir=output.parent) as temporary:
        work = Path(temporary)
        raw0_path = work / "core0.raw.bin"
        raw1_path = work / "core1.raw.bin"
        elf0 = inspect_and_extract(core0_elf, CORE0_VMA, regions[0]["length"],
                                   names["objcopy"] or "", names["readelf"] or "",
                                   names["nm"] or "", raw0_path)
        elf1 = inspect_and_extract(core1_elf, CORE1_VMA, regions[1]["length"],
                                   names["objcopy"] or "", names["readelf"] or "",
                                   names["nm"] or "", raw1_path)
        raw0 = raw0_path.read_bytes()
        raw1 = raw1_path.read_bytes()
        require(len(raw0) >= 79 * 4, "core0 binary is shorter than its complete vector table")
        stack, reset = struct.unpack_from("<II", raw0)
        require(stack == CORE0_STACK, "core0 initial stack pointer changed")
        require((reset & 1) == 1 and (reset & ~1) < len(raw0), "core0 reset vector is invalid")
        require(reset == int(str(elf0["entry"]), 0),
                "core0 reset vector does not equal the ELF entry point")
        require(int(str(elf1["entry"]), 0) == CORE1_VMA + 1,
                "core1 ELF entry must be exactly 0x10000001")

        core0 = raw0 + b"\xff" * (regions[0]["length"] - len(raw0))
        core1 = raw1 + b"\xff" * (regions[1]["length"] - len(raw1))
        checksums = (fwin_checksum(core0), fwin_checksum(core1))
        manifest = bytearray(stock["manifest"])
        struct.pack_into("<I", manifest, 0x2C, checksums[0])
        struct.pack_into("<I", manifest, 0x3C, checksums[1])
        changed = [i for i, pair in enumerate(zip(stock["manifest"], manifest)) if pair[0] != pair[1]]
        require(set(changed) <= set(range(0x2C, 0x30)) | set(range(0x3C, 0x40)),
                "manifest changed outside core checksum words")
        require(bytes(manifest[0x40:0x50]) == stock["manifest"][0x40:0x50],
                "asset manifest entry changed")

        files = {
            "preserved-header.bin": stock["header"],
            "preserved-loader.bin": stock["loader"],
            "replacement-manifest.bin": bytes(manifest),
            "replacement-core0.bin": core0,
            "replacement-core1.bin": core1,
        }
        for name, data in files.items():
            (work / name).write_bytes(data)

        program = [
            {"offset": "0x00011000", "length": len(core0), "source": "replacement-core0.bin"},
            {"offset": "0x00021000", "length": len(core1), "source": "replacement-core1.bin"},
            {"offset": "0x00010000", "length": len(manifest), "source": "replacement-manifest.bin"},
        ]
        require(all(bounded_operation(int(item["offset"], 0), int(item["length"])) for item in program),
                "generated flash plan intersects a prohibited range")
        erase = [sector_erase(int(item["offset"], 0), int(item["length"]))
                 for item in program]
        operations: list[dict[str, object]] = []
        for erase_item, program_item in zip(erase, program):
            operations.append(erase_item)
            operations.append({"operation": "program", **program_item})
            operations.append({
                "operation": "readback_sha256", "offset": program_item["offset"],
                "length": program_item["length"],
                "sha256": digest(files[str(program_item["source"])]),
            })
        plan = {
            "format": "KB7 bounded split-region flash plan v1",
            "complete_flash_image": False,
            "status": "deprecated_offline_audit_only",
            "execution_authorized": False,
            "superseded_by": "tools/flash-access/kb7-updater-plan.py",
            "power_loss_warning": (
                "The split update is not atomic. Program and read back both payloads first, "
                "then program the manifest last; interruption still requires external recovery."
            ),
            "operation_order_is_normative": True,
            "prohibited_ranges": [
                {"start": "0x00000000", "end_exclusive": "0x00010000",
                 "reason": "preserved boot header and recovery loader"},
                {"start": "0x00100000", "end_exclusive": "0x0156af8c",
                 "reason": "preserved vendor asset region"},
            ],
            "program": program,
            "erase": erase,
            "operations": operations,
            "required_readback": [
                {"offset": "0x00000000", "length": 0x1000,
                 "sha256": digest(stock["header"])},
                {"offset": "0x00001000", "length": 0xF000,
                 "sha256": digest(stock["loader"])},
                *[{"offset": item["offset"], "length": item["length"],
                   "sha256": digest(files[item["source"]])} for item in program],
                {"offset": "0x00100000", "length": REGION2_END - REGION2_START,
                 "require_owner_backup_match": True},
            ],
        }
        (work / "flash-plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        result = {
            "format": "KB7 clean-room engineering bundle audit v1",
            "offline_verification_passed": True,
            "flash_approved": False,
            "stock_anchor_sha256": {role: digest(data) for role, data in stock.items()},
            "elf": {"core0": elf0, "core1": elf1},
            "regions": {
                "core0": {"length": len(core0), "sha256": digest(core0),
                          "checksum": f"0x{checksums[0]:08x}"},
                "core1": {"length": len(core1), "sha256": digest(core1),
                          "checksum": f"0x{checksums[1]:08x}"},
            },
            "manifest_changed_offsets": [f"0x{i:x}" for i in changed],
            "header_loader_preserved": True,
            "asset_entry_preserved": True,
            "files": {name: {"length": len(data), "sha256": digest(data)}
                      for name, data in files.items()},
        }
        (work / "audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        raw0_path.unlink()
        raw1_path.unlink()
        os.replace(work, output)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-dir", required=True, type=Path)
    parser.add_argument("--core0-elf", required=True, type=Path)
    parser.add_argument("--core1-elf", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cross-prefix", default="arm-none-eabi-")
    args = parser.parse_args()
    try:
        result = build(args.stock_dir.resolve(), args.core0_elf.resolve(),
                       args.core1_elf.resolve(), args.out.resolve(), args.cross_prefix)
    except (BundleError, OSError, ValueError) as error:
        print(f"bundle error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
