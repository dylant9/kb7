#!/usr/bin/env python3
"""Build and simulate a V1.22-only, manifest-preserving USB update plan.

This is deliberately an offline tool.  It imports no USB library, opens no
device, and has no command that can execute a flash operation.  Its output is
an unsigned engineering bundle and a fault-model report, not authorization to
install replacement firmware.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class PlanError(ValueError):
    pass


FLASH_BYTES = 0x02000000
FLASH_BASE = 0x60000000
SECTOR_BYTES = 0x1000
BLOCK_BYTES = 0x200
HEADER_START = 0x00000000
LOADER_START = 0x00001000
MANIFEST_START = 0x00010000
CORE0_START = 0x00011000
CORE0_LENGTH = 0x0000F35C
CORE0_ENVELOPE_END = 0x00021000
CORE1_START = 0x00021000
CORE1_LENGTH = 0x0006B168
CORE1_ENVELOPE_END = 0x0008D000
REGION2_START = 0x00100000
REGION2_LENGTH = 0x0146AF8C
CORE0_VMA = 0x00000000
CORE1_VMA = 0x10000000
CORE0_STACK = 0x1803F5C0
RUNTIME_ABI_VERSION = 2

PAIR_MAGIC = 0x5037424B
PAIR_FORMAT = 1
PAIR_BYTES = 32
PAIR_ID_BYTES = 16
PAIR_CORE0_OFFSET = 0x140
PAIR_CORE1_OFFSET = 0x100
PAIR_STRUCT = struct.Struct("<IHHII16s")

STOCK_SHA256 = {
    "header": "70d8c190dabfeab8ff75395131dc2ae89c279d95c967bfc9102f961f79a68af3",
    "loader": "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56",
    "manifest": "a945368195d825160ebfdd49e5f96581334da3205e0c3bd924e17fb5a7940590",
    "core0": "d779faf9f591e71602e5f17e966ac366602699a83fb5e612534d694d3dafd153",
    "core1": "b2869bc657ba896474e760f513e4514fac678a951364efc29cbf9b6bb5e2ba72",
}


@dataclass(frozen=True)
class RegionSpec:
    name: str
    start: int
    length: int
    envelope_end: int
    vma: int
    pair_offset: int
    role: int
    fixup_offset: int
    gate_offset: int
    manifest_checksum: int

    @property
    def envelope_length(self) -> int:
        return self.envelope_end - self.start


CORE0 = RegionSpec("core0", CORE0_START, CORE0_LENGTH, CORE0_ENVELOPE_END,
                   CORE0_VMA, PAIR_CORE0_OFFSET, 0, 0xEE00, 0xF000,
                   0xC3F43A6F)
CORE1 = RegionSpec("core1", CORE1_START, CORE1_LENGTH, CORE1_ENVELOPE_END,
                   CORE1_VMA, PAIR_CORE1_OFFSET, 1, 0x6AC00, 0x6AE00,
                   0xC8ED2815)
REGIONS = (CORE0, CORE1)

FORMAT = "KB7 V1.22 manifest-preserving paired bundle v1"
SIMULATION_FORMAT = "KB7 USB updater interruption model v1"
PAIR_DOMAIN = b"KB7 paired replacement firmware v1\0"
STATE_DOMAIN = b"KB7 updater modeled state v1\0"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def canonical_sha256(value: object) -> str:
    return sha256(canonical_bytes(value))


def fwin_checksum(data: bytes) -> int:
    return sum(zlib.crc32(data[offset:offset + 0x10000]) & 0xFFFFFFFF
               for offset in range(0, len(data), 0x10000)) & 0xFFFFFFFF


def read_regular(path: Path, *, size: int | None = None) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise PlanError(f"missing file: {path}") from error
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(),
            f"not a regular non-symlink file: {path}")
    if size is not None:
        require(info.st_size == size,
                f"{path.name} must be exactly {size} bytes, got {info.st_size}")
    return path.read_bytes()


def load_baselines(first: Path, second: Path) -> bytes:
    require(first.resolve() != second.resolve(), "baseline captures must be distinct files")
    try:
        require(not os.path.samefile(first, second),
                "baseline captures must not be aliases of the same file")
    except FileNotFoundError:
        pass
    left = read_regular(first, size=FLASH_BYTES)
    right = read_regular(second, size=FLASH_BYTES)
    require(left == right, "the two fresh 32-MiB baseline captures differ")
    return left


def parse_manifest(manifest: bytes) -> list[dict[str, int]]:
    require(len(manifest) == SECTOR_BYTES and manifest[:8] == b"SN_FWIN\0",
            "invalid SN_FWIN manifest")
    require(manifest[8:16] == b"v1.0.00\0", "unexpected manifest format version")
    regions: list[dict[str, int]] = []
    for index, offset in enumerate((0x20, 0x30, 0x40, 0x50)):
        load, store, length, checksum = struct.unpack_from("<IIII", manifest, offset)
        regions.append({"index": index, "load": load, "store": store,
                        "length": length, "checksum": checksum})
    expected = (
        (CORE0_VMA, FLASH_BASE + CORE0_START, CORE0_LENGTH, CORE0.manifest_checksum),
        (CORE1_VMA, FLASH_BASE + CORE1_START, CORE1_LENGTH, CORE1.manifest_checksum),
        (FLASH_BASE + REGION2_START, FLASH_BASE + REGION2_START,
         REGION2_LENGTH, regions[2]["checksum"]),
        (0x18000000, FLASH_BASE + CORE1_START, 0, 0),
    )
    for record, values in zip(regions, expected):
        require(tuple(record[key] for key in ("load", "store", "length", "checksum")) == values,
                f"manifest region {record['index']} is not the pinned V1.22 layout")
    return regions


def validate_baseline(image: bytes,
                      anchors: dict[str, str] | None = None) -> dict[str, object]:
    anchors = STOCK_SHA256 if anchors is None else anchors
    require(len(image) == FLASH_BYTES, "baseline is not exactly 32 MiB")
    slices = {
        "header": image[HEADER_START:LOADER_START],
        "loader": image[LOADER_START:MANIFEST_START],
        "manifest": image[MANIFEST_START:CORE0_START],
        "core0": image[CORE0_START:CORE0_START + CORE0_LENGTH],
        "core1": image[CORE1_START:CORE1_START + CORE1_LENGTH],
    }
    require(slices["header"][:8] == b"SNC7320A", "invalid SNC7320A boot header")
    for name, data in slices.items():
        require(sha256(data) == anchors[name],
                f"baseline {name} SHA-256 is not the pinned V1.22 value")
    records = parse_manifest(slices["manifest"])
    for record in records[:3]:
        start = record["store"] - FLASH_BASE
        end = start + record["length"]
        require(0 <= start < end <= len(image), "manifest region is outside flash")
        require(fwin_checksum(image[start:end]) == record["checksum"],
                f"manifest region {record['index']} checksum fails")
    require(image[CORE0_START + CORE0_LENGTH:CORE0_ENVELOPE_END] ==
            b"\xff" * (CORE0_ENVELOPE_END - CORE0_START - CORE0_LENGTH),
            "core0 sector-tail padding is not erased")
    require(image[CORE1_START + CORE1_LENGTH:CORE1_ENVELOPE_END] ==
            b"\xff" * (CORE1_ENVELOPE_END - CORE1_START - CORE1_LENGTH),
            "core1 sector-tail padding is not erased")
    return {"sha256": sha256(image), "slices": slices, "manifest": records}


def run(arguments: list[str]) -> str:
    result = subprocess.run(arguments, text=True, capture_output=True, check=False)
    require(result.returncode == 0,
            f"command failed ({result.returncode}): {' '.join(arguments)}\n{result.stderr}")
    return result.stdout


def validate_load_ranges(program_headers: str, expected_vma: int,
                         maximum: int) -> int:
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
                "ELF has file-backed bytes outside its updater-safe extent")
        ranges.append((physical, end))
    require(ranges, "ELF has no file-backed LOAD segment")
    ranges.sort()
    require(ranges[0][0] == expected_vma,
            "ELF's lowest file-backed LOAD address is not its required VMA")
    for previous, current in zip(ranges, ranges[1:]):
        require(previous[1] <= current[0], "ELF file-backed LOAD ranges overlap")
    return max(end for _, end in ranges) - expected_vma


def validate_extracted_image(raw: bytes, spec: RegionSpec, entry: int) -> None:
    require(raw and len(raw) <= spec.fixup_offset,
            f"{spec.name} binary overlaps the CRC-fixup reserve")
    if spec is CORE0:
        require(len(raw) >= 79 * 4, "core0 is shorter than its vector table")
        stack, reset = struct.unpack_from("<II", raw)
        require(stack == CORE0_STACK and reset == entry and (reset & 1) == 1 and
                (reset & ~1) < len(raw),
                "core0 stack/reset vector does not match its ELF")
    else:
        require(entry == CORE1_VMA + 1, "core1 entry must be exactly 0x10000001")


def inspect_and_extract(elf: Path, spec: RegionSpec, prefix: str,
                        destination: Path) -> tuple[bytes, dict[str, object]]:
    read_regular(elf)
    tools = {name: shutil.which(f"{prefix}{name}")
             for name in ("objcopy", "readelf", "nm")}
    require(all(tools.values()), f"missing ARM binutils for prefix {prefix!r}")
    header = run([tools["readelf"] or "", "-h", str(elf)])
    require("Class:" in header and "ELF32" in header and
            "Data:" in header and "little endian" in header and
            "Type:" in header and "EXEC" in header and
            "Machine:" in header and "ARM" in header,
            f"not an ELF32 little-endian ARM executable: {elf}")
    entry_line = next((line for line in header.splitlines()
                       if "Entry point address:" in line), "")
    require(entry_line, f"ELF has no entry point: {elf}")
    entry = int(entry_line.rsplit(maxsplit=1)[1], 16)
    require("There are no relocations" in
            run([tools["readelf"] or "", "-r", str(elf)]),
            f"ELF contains relocations: {elf}")
    require(not run([tools["nm"] or "", "-u", str(elf)]).strip(),
            f"ELF contains undefined symbols: {elf}")
    raw_length = validate_load_ranges(
        run([tools["readelf"] or "", "-lW", str(elf)]), spec.vma,
        spec.fixup_offset)
    run([tools["objcopy"] or "", "-O", "binary", str(elf), str(destination)])
    raw = read_regular(destination)
    require(raw and len(raw) == raw_length and len(raw) <= spec.fixup_offset,
            f"{spec.name} binary overlaps the CRC-fixup reserve")
    validate_extracted_image(raw, spec, entry)
    return raw, {"entry": f"0x{entry:08x}", "raw_length": len(raw),
                 "elf_sha256": sha256(read_regular(elf)),
                 "raw_sha256": sha256(raw)}


def validate_pair_placeholder(raw: bytes, spec: RegionSpec) -> None:
    require(spec.pair_offset + PAIR_BYTES <= len(raw),
            f"{spec.name} is missing its fixed build-pair marker")
    magic, version, size, role, abi, identifier = PAIR_STRUCT.unpack_from(
        raw, spec.pair_offset)
    require((magic, version, size, role, abi) ==
            (PAIR_MAGIC, PAIR_FORMAT, PAIR_BYTES, spec.role, RUNTIME_ABI_VERSION),
            f"{spec.name} build-pair marker metadata is invalid")
    require(identifier == b"\xff" * PAIR_ID_BYTES,
            f"{spec.name} ELF pair identifier is not the required placeholder")


def gf2_solve(columns: list[int], target: int) -> tuple[int, int]:
    require(len(columns) == 32, "CRC transform must have 32 columns")
    basis: list[tuple[int, int] | None] = [None] * 32
    rank = 0
    for index, column in enumerate(columns):
        value = column & 0xFFFFFFFF
        combination = 1 << index
        while value:
            pivot = value.bit_length() - 1
            if basis[pivot] is None:
                basis[pivot] = (value, combination)
                rank += 1
                break
            value ^= basis[pivot][0]
            combination ^= basis[pivot][1]
    value = target & 0xFFFFFFFF
    solution = 0
    while value:
        pivot = value.bit_length() - 1
        require(basis[pivot] is not None, "CRC target is outside transform span")
        value ^= basis[pivot][0]
        solution ^= basis[pivot][1]
    return solution, rank


def crc_patch(chunk: bytes, patch_offset: int, wanted_crc: int) -> tuple[bytes, int]:
    require(0 <= patch_offset <= len(chunk) - 4, "CRC patch is outside its chunk")
    base_data = bytearray(chunk)
    base_data[patch_offset:patch_offset + 4] = b"\0" * 4
    base_crc = zlib.crc32(base_data) & 0xFFFFFFFF
    columns: list[int] = []
    for bit in range(32):
        candidate = bytearray(base_data)
        candidate[patch_offset:patch_offset + 4] = (1 << bit).to_bytes(4, "little")
        columns.append((zlib.crc32(candidate) & 0xFFFFFFFF) ^ base_crc)
    value, rank = gf2_solve(columns, wanted_crc ^ base_crc)
    patch = value.to_bytes(4, "little")
    result = bytearray(base_data)
    result[patch_offset:patch_offset + 4] = patch
    require((zlib.crc32(result) & 0xFFFFFFFF) == wanted_crc,
            "CRC correction solver failed its independent recomputation")
    return patch, rank


def crc_word_rank(chunk: bytes, word_offset: int) -> int:
    require(0 <= word_offset <= len(chunk) - 4, "CRC gate is outside its chunk")
    base = bytearray(chunk)
    base[word_offset:word_offset + 4] = b"\0" * 4
    base_crc = zlib.crc32(base) & 0xFFFFFFFF
    columns = []
    for bit in range(32):
        candidate = bytearray(base)
        candidate[word_offset:word_offset + 4] = (1 << bit).to_bytes(4, "little")
        columns.append((zlib.crc32(candidate) & 0xFFFFFFFF) ^ base_crc)
    _, rank = gf2_solve(columns, 0)
    return rank


def derive_pair_id(raw0: bytes, raw1: bytes) -> bytes:
    result = hashlib.sha256(PAIR_DOMAIN + raw0 + raw1).digest()[:PAIR_ID_BYTES]
    require(result not in (b"\0" * PAIR_ID_BYTES, b"\xff" * PAIR_ID_BYTES),
            "derived pair identifier is reserved")
    return result


def build_target_region(raw: bytes, spec: RegionSpec,
                        pair_id: bytes) -> tuple[bytes, bytes, dict[str, object]]:
    require(len(pair_id) == PAIR_ID_BYTES, "invalid pair identifier length")
    validate_pair_placeholder(raw, spec)
    require(len(raw) <= spec.fixup_offset and spec.fixup_offset % BLOCK_BYTES == 0 and
            spec.gate_offset % BLOCK_BYTES == 0 and
            spec.fixup_offset + BLOCK_BYTES <= spec.gate_offset,
            f"{spec.name} updater reserve geometry is invalid")
    region = bytearray(raw + b"\xff" * (spec.length - len(raw)))
    pair_id_offset = spec.pair_offset + PAIR_STRUCT.size - PAIR_ID_BYTES
    region[pair_id_offset:pair_id_offset + PAIR_ID_BYTES] = pair_id
    require(region[spec.fixup_offset:spec.fixup_offset + BLOCK_BYTES] ==
            b"\xff" * BLOCK_BYTES, f"{spec.name} fixup block is not reserved")
    require(region[spec.gate_offset:spec.gate_offset + BLOCK_BYTES] ==
            b"\xff" * BLOCK_BYTES, f"{spec.name} commit block is not reserved")
    region[spec.gate_offset:spec.gate_offset + 4] = b"\0" * 4

    chunk_start = (spec.fixup_offset // 0x10000) * 0x10000
    chunk_end = min(chunk_start + 0x10000, spec.length)
    other_sum = sum(zlib.crc32(region[offset:min(offset + 0x10000, spec.length)]) &
                    0xFFFFFFFF for offset in range(0, spec.length, 0x10000)
                    if offset != chunk_start) & 0xFFFFFFFF
    wanted_chunk = (spec.manifest_checksum - other_sum) & 0xFFFFFFFF
    chunk = bytes(region[chunk_start:chunk_end])
    patch, patch_rank = crc_patch(chunk, spec.fixup_offset - chunk_start,
                                  wanted_chunk)
    region[spec.fixup_offset:spec.fixup_offset + 4] = patch
    require(patch != b"\xff" * 4, f"{spec.name} CRC correction is erased")
    target = bytes(region)
    require(fwin_checksum(target) == spec.manifest_checksum,
            f"{spec.name} balanced checksum does not match the unchanged manifest")

    staged_data = bytearray(target)
    staged_data[spec.gate_offset:spec.gate_offset + 4] = b"\xff" * 4
    staged = bytes(staged_data)
    require(fwin_checksum(staged) != spec.manifest_checksum,
            f"{spec.name} staged image is unexpectedly loader-valid")
    gate_chunk_start = (spec.gate_offset // 0x10000) * 0x10000
    gate_chunk_end = min(gate_chunk_start + 0x10000, spec.length)
    gate_rank = crc_word_rank(target[gate_chunk_start:gate_chunk_end],
                              spec.gate_offset - gate_chunk_start)
    require(patch_rank == 32 and gate_rank == 32,
            f"{spec.name} CRC correction/gate transform is not bijective")
    require(target[spec.gate_offset:spec.gate_offset + BLOCK_BYTES] ==
            b"\0" * 4 + b"\xff" * (BLOCK_BYTES - 4),
            f"{spec.name} commit block contains data beyond its four-byte gate")
    metadata = {
        "fixup_offset": f"0x{spec.fixup_offset:08x}",
        "fixup_bytes": patch.hex(),
        "fixup_rank": patch_rank,
        "gate_offset": f"0x{spec.gate_offset:08x}",
        "gate_final_bytes": "00000000",
        "gate_rank": gate_rank,
        "staged_checksum": f"0x{fwin_checksum(staged):08x}",
        "target_checksum": f"0x{fwin_checksum(target):08x}",
    }
    return target, staged, metadata


def validate_target_region(target: bytes, spec: RegionSpec, pair_id: bytes,
                           metadata: object) -> bytes:
    require(len(target) == spec.length, f"{spec.name} target length is invalid")
    require(len(pair_id) == PAIR_ID_BYTES and
            pair_id not in (b"\0" * PAIR_ID_BYTES, b"\xff" * PAIR_ID_BYTES),
            "bundle pair identifier is reserved")
    require(isinstance(metadata, dict), f"{spec.name} metadata is invalid")
    magic, version, size, role, abi, identifier = PAIR_STRUCT.unpack_from(
        target, spec.pair_offset)
    require((magic, version, size, role, abi, identifier) ==
            (PAIR_MAGIC, PAIR_FORMAT, PAIR_BYTES, spec.role,
             RUNTIME_ABI_VERSION, pair_id),
            f"{spec.name} paired marker does not match the bundle")
    require(target[spec.fixup_offset + 4:spec.fixup_offset + BLOCK_BYTES] ==
            b"\xff" * (BLOCK_BYTES - 4),
            f"{spec.name} fixup reserve contains unexpected bytes")
    require(target[spec.gate_offset:spec.gate_offset + BLOCK_BYTES] ==
            b"\0" * 4 + b"\xff" * (BLOCK_BYTES - 4),
            f"{spec.name} commit gate block is not sparse")
    require(metadata.get("fixup_offset") == f"0x{spec.fixup_offset:08x}" and
            metadata.get("start") == f"0x{spec.start:08x}" and
            type(metadata.get("length")) is int and metadata.get("length") == spec.length and
            type(metadata.get("envelope_length")) is int and
            metadata.get("envelope_length") == spec.envelope_length and
            metadata.get("fixup_bytes") ==
            target[spec.fixup_offset:spec.fixup_offset + 4].hex() and
            metadata.get("fixup_rank") == 32 and
            metadata.get("gate_offset") == f"0x{spec.gate_offset:08x}" and
            metadata.get("gate_final_bytes") == "00000000" and
            metadata.get("gate_rank") == 32 and
            metadata.get("target_checksum") == f"0x{spec.manifest_checksum:08x}" and
            metadata.get("target_sha256") == sha256(target),
            f"{spec.name} metadata does not bind its target")
    require(fwin_checksum(target) == spec.manifest_checksum,
            f"{spec.name} target checksum does not match the manifest")
    fixup_chunk_start = (spec.fixup_offset // 0x10000) * 0x10000
    fixup_chunk_end = min(fixup_chunk_start + 0x10000, spec.length)
    fixup_chunk = target[fixup_chunk_start:fixup_chunk_end]
    solved_patch, solved_rank = crc_patch(
        fixup_chunk, spec.fixup_offset - fixup_chunk_start,
        zlib.crc32(fixup_chunk) & 0xFFFFFFFF)
    require(solved_rank == 32 and
            solved_patch == target[spec.fixup_offset:spec.fixup_offset + 4],
            f"{spec.name} fixup transform does not independently verify")
    staged = bytearray(target)
    staged[spec.gate_offset:spec.gate_offset + 4] = b"\xff" * 4
    require(fwin_checksum(staged) != spec.manifest_checksum and
            metadata.get("staged_checksum") == f"0x{fwin_checksum(staged):08x}",
            f"{spec.name} staged checksum contract fails")
    chunk_start = (spec.gate_offset // 0x10000) * 0x10000
    chunk_end = min(chunk_start + 0x10000, spec.length)
    require(crc_word_rank(target[chunk_start:chunk_end],
                          spec.gate_offset - chunk_start) == 32,
            f"{spec.name} gate transform is not bijective")
    return bytes(staged)


def cdb_program(offset: int) -> bytes:
    require(offset % BLOCK_BYTES == 0 and 0 <= offset <= FLASH_BYTES - BLOCK_BYTES,
            "program offset is not one in-range 512-byte block")
    absolute = FLASH_BASE + offset
    return bytes((0xF6, 0x06, 0x00, (absolute >> 24) & 0xFF,
                  (absolute >> 16) & 0xFF, (absolute >> 8) & 0xFF,
                  absolute & 0xFF, 0x00, 0x01, 0, 0, 0, 0, 0, 0, 0))


def cdb_erase(offset: int) -> bytes:
    require(offset % SECTOR_BYTES == 0 and 0 <= offset <= FLASH_BYTES - SECTOR_BYTES,
            "erase offset is not one in-range 4-KiB sector")
    index = offset >> 9
    require(index <= 0xFFFF, "F6 15 block index does not fit")
    return bytes((0xF6, 0x15, 0x00, (index >> 8) & 0xFF, index & 0xFF,
                  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))


def choose_poison(image: bytes, spec: RegionSpec) -> tuple[int, int, bytes]:
    search_start = spec.start + 0x1000
    search_end = spec.start + spec.fixup_offset
    relative = image[search_start:search_end].find(b"\xff")
    require(relative >= 0, f"{spec.name} has no safe erased bit for its boot barrier")
    byte_offset = search_start + relative
    block_offset = byte_offset & ~(BLOCK_BYTES - 1)
    payload = bytearray(b"\xff" * BLOCK_BYTES)
    payload[byte_offset - block_offset] = 0xFE
    return block_offset, byte_offset, bytes(payload)


@dataclass
class Operation:
    phase: str
    action: str
    offset: int
    payload: bytes | None
    payload_source: str | None
    payload_offset: int | None

    @property
    def length(self) -> int:
        return BLOCK_BYTES if self.action == "program" else SECTOR_BYTES


def apply_operation(image: bytearray, operation: Operation) -> None:
    start = operation.offset
    end = start + operation.length
    require(CORE0_START <= start < end <= CORE1_ENVELOPE_END,
            "operation escapes the two core envelopes")
    if operation.action == "erase":
        require(start % SECTOR_BYTES == 0, "unaligned modeled erase")
        image[start:end] = b"\xff" * SECTOR_BYTES
        return
    require(operation.action == "program" and operation.payload is not None and
            len(operation.payload) == BLOCK_BYTES and start % BLOCK_BYTES == 0,
            "invalid modeled program")
    before = image[start:end]
    image[start:end] = bytes(left & right
                             for left, right in zip(before, operation.payload))


def mutable_state_sha256(image: bytes) -> str:
    return sha256(STATE_DOMAIN + image[CORE0_START:CORE0_ENVELOPE_END] +
                  image[CORE1_START:CORE1_ENVELOPE_END])


def core_checksums(image: bytes) -> tuple[int, int]:
    return (fwin_checksum(image[CORE0_START:CORE0_START + CORE0_LENGTH]),
            fwin_checksum(image[CORE1_START:CORE1_START + CORE1_LENGTH]))


def transition_reachable(preimage: bytes, observed: bytes, postimage: bytes,
                         action: str) -> bool:
    if not (len(preimage) == len(observed) == len(postimage)):
        return False
    if action == "program":
        return all((before & current) == current and (current & after) == after
                   for before, current, after in zip(preimage, observed, postimage))
    if action == "erase":
        return all((before | current) == current and (current | after) == after
                   for before, current, after in zip(preimage, observed, postimage))
    return False


def prefix_outcome(preimage: bytes, postimage: bytes, action: str,
                   cut: int) -> bytes:
    require(0 <= cut <= len(preimage) and len(preimage) == len(postimage),
            "invalid interruption prefix")
    if action == "program":
        return bytes((preimage[index] & postimage[index]) if index < cut
                     else preimage[index] for index in range(len(preimage)))
    require(action == "erase", "unknown interruption action")
    return bytes(0xFF if index < cut else preimage[index]
                 for index in range(len(preimage)))


def classify_reconciliation(preimage: bytes, observed: bytes, postimage: bytes,
                            operation: Operation) -> str:
    """Classify a two-read-stable image; a host journal is intentionally absent."""
    if not (len(preimage) == len(observed) == len(postimage)):
        return "spi_recovery_required"
    if observed == preimage:
        return "exact_preimage"
    if observed == postimage:
        return "exact_postimage"
    start = operation.offset
    end = start + operation.length
    if observed[:start] != preimage[:start] or observed[end:] != preimage[end:]:
        return "spi_recovery_required"
    if not transition_reachable(preimage[start:end], observed[start:end],
                                postimage[start:end], operation.action):
        return "spi_recovery_required"
    if operation.phase.startswith("stage_"):
        return "modeled_partial_rebuild_active_sector"
    if operation.phase.startswith("commit_"):
        return "modeled_partial_sparse_gate"
    return "spi_recovery_required"


def append_stage_operations(operations: list[Operation], current: bytearray,
                            spec: RegionSpec, staged_envelope: bytes) -> None:
    require(len(staged_envelope) == spec.envelope_length, "bad staged envelope size")
    for sector in range(spec.start, spec.envelope_end, SECTOR_BYTES):
        relative = sector - spec.start
        desired = staged_envelope[relative:relative + SECTOR_BYTES]
        before = bytes(current[sector:sector + SECTOR_BYTES])
        if before == desired:
            continue
        monotonic = all((old & new) == new for old, new in zip(before, desired))
        if not monotonic:
            operation = Operation(f"stage_{spec.name}", "erase", sector, None, None, None)
            operations.append(operation)
            apply_operation(current, operation)
        for block in range(sector, sector + SECTOR_BYTES, BLOCK_BYTES):
            block_relative = block - spec.start
            payload = staged_envelope[block_relative:block_relative + BLOCK_BYTES]
            if bytes(current[block:block + BLOCK_BYTES]) == payload:
                continue
            require(payload != b"\xff" * BLOCK_BYTES,
                    "planner attempted a no-op all-FF program")
            require(all((old & new) == new for old, new in
                        zip(current[block:block + BLOCK_BYTES], payload)),
                    "planner attempted a program that requires 0-to-1 transitions")
            operation = Operation(f"stage_{spec.name}", "program", block, payload,
                                  f"{spec.name}-sector-image.bin", block_relative)
            operations.append(operation)
            apply_operation(current, operation)
    require(bytes(current[spec.start:spec.envelope_end]) == staged_envelope,
            f"{spec.name} staging did not converge to its exact image")


def build_operations(baseline: bytes, targets: dict[str, bytes],
                     staged: dict[str, bytes]) -> tuple[list[Operation], dict[str, object]]:
    current = bytearray(baseline)
    operations: list[Operation] = []
    poisons: dict[str, object] = {}
    # Invalidate Core 0 first: under the recovered loader model this prevents
    # transfer to the old Core 0 even if power disappears before Core 1 poison.
    poison_payloads: list[bytes] = []
    for spec in (CORE0, CORE1):
        block, byte_offset, payload = choose_poison(baseline, spec)
        payload_offset = len(poison_payloads) * BLOCK_BYTES
        operation = Operation(f"poison_{spec.name}", "program", block, payload,
                              "poison-blocks.bin", payload_offset)
        operations.append(operation)
        poison_payloads.append(payload)
        apply_operation(current, operation)
        require(core_checksums(current)[spec.role] != spec.manifest_checksum,
                f"{spec.name} one-bit poison did not invalidate its checksum")
        poisons[spec.name] = {
            "block_offset": f"0x{block:08x}",
            "byte_offset": f"0x{byte_offset:08x}",
            "payload_sha256": sha256(payload),
            "requested_transition": "0xff->0xfe",
        }
    for spec in (CORE1, CORE0):
        envelope = staged[spec.name] + b"\xff" * (spec.envelope_length - spec.length)
        append_stage_operations(operations, current, spec, envelope)
        require(core_checksums(current)[spec.role] != spec.manifest_checksum,
                f"{spec.name} staged image is unexpectedly valid")
    for spec in (CORE1, CORE0):
        payload = targets[spec.name][spec.gate_offset:spec.gate_offset + BLOCK_BYTES]
        operation = Operation(f"commit_{spec.name}", "program",
                              spec.start + spec.gate_offset, payload,
                              f"{spec.name}-sector-image.bin", spec.gate_offset)
        operations.append(operation)
        apply_operation(current, operation)
        require(bytes(current[spec.start:spec.start + spec.length]) == targets[spec.name],
                f"{spec.name} commit does not produce its exact target")
    expected = bytearray(baseline)
    for spec in REGIONS:
        expected[spec.start:spec.start + spec.length] = targets[spec.name]
        expected[spec.start + spec.length:spec.envelope_end] = \
            b"\xff" * (spec.envelope_end - spec.start - spec.length)
    require(current == expected, "operation sequence does not produce the exact target image")
    return operations, {"poison": poisons,
                        "poison_payload": b"".join(poison_payloads),
                        "target_full_sha256": sha256(expected)}


def simulate(baseline: bytes, targets: dict[str, bytes], staged: dict[str, bytes],
             operations: list[Operation]) -> tuple[list[dict[str, object]], dict[str, object]]:
    current = bytearray(baseline)
    immutable_before = sha256(baseline[:CORE0_START] + baseline[CORE1_ENVELOPE_END:])
    source_regions = {spec.name: baseline[spec.start:spec.start + spec.length]
                      for spec in REGIONS}
    traces: list[dict[str, object]] = []
    both_valid_early = 0
    body_partial_barriers = 0
    byte_prefix_states_checked = 0
    unique_prefix_states_evaluated = 0
    poison_prefix_states_checked = 0
    final_gate_prefix_states_checked = 0
    journal_states_checked = 0
    for index, operation in enumerate(operations):
        unit_start = operation.offset
        unit_end = unit_start + operation.length
        sector_start = operation.offset & ~(SECTOR_BYTES - 1)
        pre_unit = bytes(current[unit_start:unit_end])
        pre_sector = bytes(current[sector_start:sector_start + SECTOR_BYTES])
        pre_state = mutable_state_sha256(current)
        pre_checksums = core_checksums(current)
        no_effect_class = "stock" if all(
            bytes(current[spec.start:spec.start + spec.length]) == source_regions[spec.name]
            for spec in REGIONS) else "isp"
        apply_operation(current, operation)
        post_unit = bytes(current[unit_start:unit_end])
        post_sector = bytes(current[sector_start:sector_start + SECTOR_BYTES])
        require(pre_unit != post_unit, f"operation {index} is a no-op")
        require(transition_reachable(pre_unit, post_unit, post_unit, operation.action),
                f"operation {index} violates modeled NOR direction")
        post_checksums = core_checksums(current)
        valid = (post_checksums[0] == CORE0.manifest_checksum,
                 post_checksums[1] == CORE1.manifest_checksum)
        target_exact = all(bytes(current[spec.start:spec.start + spec.length]) ==
                           targets[spec.name] for spec in REGIONS)
        if all(valid) and not target_exact:
            both_valid_early += 1
        post_class = "target" if target_exact and all(valid) else "isp"
        require(not all(valid) or target_exact,
                f"operation {index} creates an early checksum-valid non-target pair")
        require(sha256(bytes(current[:CORE0_START]) +
                       bytes(current[CORE1_ENVELOPE_END:])) == immutable_before,
                f"operation {index} changes an immutable range")

        if operation.phase.startswith("stage_core0"):
            require(post_checksums[1] != CORE1.manifest_checksum,
                    "Core 1 is not an invalid barrier during Core 0 staging")
            body_partial_barriers += 1
        elif operation.phase.startswith("stage_core1"):
            require(post_checksums[0] != CORE0.manifest_checksum,
                    "Core 0 is not an invalid barrier during Core 1 staging")
            body_partial_barriers += 1
        elif operation.phase == "commit_core1":
            require(post_checksums[0] != CORE0.manifest_checksum,
                    "Core 0 is not invalid during the Core 1 commit")
        elif operation.phase == "commit_core0":
            require(target_exact and all(valid), "Core 0 final commit is not exact target")

        # Cover all byte-prefix cuts symbolically in O(unit-size): every prefix
        # is a concatenation of exact-effect bytes followed by preimage bytes.
        # Per-byte reachability therefore proves all cuts without rebuilding
        # O(n) copies for each of O(n) cut points.
        require(transition_reachable(pre_unit, post_unit, post_unit, operation.action),
                f"operation {index} has no monotone prefix construction")
        byte_prefix_states_checked += operation.length - 1
        if operation.phase.startswith("poison_"):
            changed_bits = sum((left ^ right).bit_count()
                               for left, right in zip(pre_unit, post_unit))
            require(changed_bits == 1,
                    "poison operation is not exactly one requested bit")
            poison_prefix_states_checked += operation.length - 1
            unique_prefix_states_evaluated += 2
        elif operation.phase == "commit_core0":
            # Only the first four bytes have effects; cuts >=4 are the exact
            # postimage. Check each distinct byte-prefix state directly. Rank
            # 32 separately covers all within-word bit subsets.
            for cut in range(1, 4):
                partial = prefix_outcome(pre_unit, post_unit, operation.action, cut)
                candidate = bytearray(staged["core0"])
                relative = operation.offset - CORE0.start
                candidate[relative:relative + BLOCK_BYTES] = partial
                require(fwin_checksum(candidate) != CORE0.manifest_checksum,
                        "partial final gate unexpectedly validates Core 0")
                final_gate_prefix_states_checked += 1
                unique_prefix_states_evaluated += 1
            unique_prefix_states_evaluated += 2  # exact preimage and exact target
        else:
            # Dense body and Core1-gate prefixes cannot boot because the other
            # core checksum is unchanged and exactly invalid.
            opposite = 1 if operation.phase.endswith("core0") or \
                operation.phase.startswith("stage_core0") else 0
            if operation.phase.startswith("stage_") or \
                    operation.phase == "commit_core1":
                other_spec = CORE1 if opposite == 1 else CORE0
                require(pre_checksums[opposite] != other_spec.manifest_checksum,
                        "partial operation lacks an opposite invalid barrier")
            unique_prefix_states_evaluated += 2
        # Missing/old/new/torn journal records are deliberately not authority;
        # exact pre/post image classification is the same for all four.
        journal_states_checked += 4

        traces.append({
            "index": index,
            "phase": operation.phase,
            "operation": operation.action,
            "offset": f"0x{operation.offset:08x}",
            "length": operation.length,
            "sector_offset": f"0x{sector_start:08x}",
            "address_mode_cdb": "f618" + "00" * 14,
            "mutation_cdb": (cdb_program(operation.offset) if operation.action == "program"
                             else cdb_erase(operation.offset)).hex(),
            "payload_sha256": sha256(operation.payload) if operation.payload is not None else None,
            "payload_source": operation.payload_source,
            "payload_offset": (f"0x{operation.payload_offset:08x}"
                               if operation.payload_offset is not None else None),
            "pre_sector_sha256": sha256(pre_sector),
            "post_sector_sha256": sha256(post_sector),
            "pre_unit_sha256": sha256(pre_unit),
            "post_unit_sha256": sha256(post_unit),
            "pre_state_sha256": pre_state,
            "post_state_sha256": mutable_state_sha256(current),
            "pre_checksums": [f"0x{value:08x}" for value in pre_checksums],
            "post_checksums": [f"0x{value:08x}" for value in post_checksums],
            "power_loss_before_effect": no_effect_class,
            "power_loss_after_exact_effect": post_class,
            "mid_command_policy": "stop; two stable full reads; no blind retry",
        })

    final_expected = bytearray(baseline)
    for spec in REGIONS:
        final_expected[spec.start:spec.start + spec.length] = targets[spec.name]
        final_expected[spec.start + spec.length:spec.envelope_end] = \
            b"\xff" * (spec.envelope_end - spec.start - spec.length)
    require(current == final_expected, "simulator final image is not exact target")
    report = {
        "format": SIMULATION_FORMAT,
        "offline_only": True,
        "hardware_execution_authorized": False,
        "flash_approved": False,
        "operation_count": len(operations),
        "declared_fail_stop_sites_per_operation": [
            "before_intent", "during_intent", "after_intent", "during_f6_18",
            "during_cbw", "during_data_or_erase", "before_csw", "bad_csw",
            "during_poll", "poll_timeout", "before_readback", "short_readback",
            "after_compare", "during_verified_journal", "after_verified_journal",
        ],
        "declared_fail_stop_site_count": len(operations) * 15,
        "command_boundary_prefixes_checked": len(operations) + 1,
        "modeled_mutation_prefix_states_checked": byte_prefix_states_checked,
        "unique_prefix_states_evaluated": unique_prefix_states_evaluated,
        "poison_prefix_states_checked": poison_prefix_states_checked,
        "final_gate_prefix_states_checked": final_gate_prefix_states_checked,
        "journal_authority_variants_checked": journal_states_checked,
        "body_operations_with_opposite_invalid_barrier": body_partial_barriers,
        "early_checksum_valid_non_target_states": both_valid_early,
        "gate_subset_proof": (
            "Each final four-byte gate has GF(2) rank 32. Under requested-bit-subset "
            "program behavior, only all 32 clears can restore that region checksum."
        ),
        "proof_boundary": (
            "Command boundaries and intended 1-to-0 gate subsets are proved. Arbitrary "
            "physical torn erase/program behavior, disturb, misaddressing, and loader-model "
            "errors remain hardware risks and require SPI recovery."
        ),
        "final_full_sha256": sha256(final_expected),
        "invariants_passed": [
            "manifest has zero operations",
            "all operations remain inside the two core sector envelopes",
            "immutable bytes remain exact",
            "both checksums never validate early",
            "dense mutations retain an opposite-core invalid barrier",
            "Core 1 commits before Core 0",
            "final image is the exact paired target",
            "unknown mid-command outcomes never authorize continuation",
        ],
    }
    return traces, report


def descriptor_without_id(descriptor: dict[str, object]) -> dict[str, object]:
    result = dict(descriptor)
    result.pop("bundle_id", None)
    return result


def build_bundle(baseline_a: Path, baseline_b: Path, core0_elf: Path,
                 core1_elf: Path, output: Path, prefix: str,
                 *, anchors: dict[str, str] | None = None,
                 extractor: Callable[[Path, RegionSpec, str, Path],
                                     tuple[bytes, dict[str, object]]] = inspect_and_extract
                 ) -> dict[str, object]:
    require(output.parent.is_dir(), f"output parent does not exist: {output.parent}")
    require(not output.exists(), f"refusing to replace existing output: {output}")
    baseline = load_baselines(baseline_a, baseline_b)
    baseline_info = validate_baseline(baseline, anchors)
    with tempfile.TemporaryDirectory(prefix="kb7-updater-plan-", dir=output.parent) as temporary:
        work = Path(temporary)
        raw0, elf0 = extractor(core0_elf, CORE0, prefix, work / "core0.raw")
        raw1, elf1 = extractor(core1_elf, CORE1, prefix, work / "core1.raw")
        require(isinstance(elf0, dict) and isinstance(elf1, dict),
                "ELF extractor did not return metadata")
        validate_extracted_image(raw0, CORE0, int(str(elf0.get("entry")), 0))
        validate_extracted_image(raw1, CORE1, int(str(elf1.get("entry")), 0))
        validate_pair_placeholder(raw0, CORE0)
        validate_pair_placeholder(raw1, CORE1)
        pair_id = derive_pair_id(raw0, raw1)
        target0, staged0, balance0 = build_target_region(raw0, CORE0, pair_id)
        target1, staged1, balance1 = build_target_region(raw1, CORE1, pair_id)
        targets = {"core0": target0, "core1": target1}
        staged = {"core0": staged0, "core1": staged1}
        require(sha256(target0) != (anchors or STOCK_SHA256)["core0"] and
                sha256(target1) != (anchors or STOCK_SHA256)["core1"],
                "replacement region is byte-identical to stock")
        operations, operation_info = build_operations(baseline, targets, staged)
        traces, simulation = simulate(baseline, targets, staged, operations)

        envelope0 = target0 + b"\xff" * (CORE0.envelope_length - CORE0.length)
        envelope1 = target1 + b"\xff" * (CORE1.envelope_length - CORE1.length)
        files = {"core0-sector-image.bin": envelope0,
                 "core1-sector-image.bin": envelope1,
                 "poison-blocks.bin": operation_info["poison_payload"]}
        for name, data in files.items():
            (work / name).write_bytes(data)

        trace_public = traces
        descriptor: dict[str, object] = {
            "format": FORMAT,
            "schema": 1,
            "offline_only": True,
            "device_io": False,
            "unsigned": True,
            "execution_authorized": False,
            "flash_approved": False,
            "source_policy": "one-time exact V1.22 stock to paired replacement",
            "baseline_sha256": baseline_info["sha256"],
            "source_anchors": dict(anchors or STOCK_SHA256),
            "pair_id": pair_id.hex(),
            "immutable_ranges": [
                {"start": "0x00000000", "end_exclusive": "0x00011000",
                 "sha256": sha256(baseline[:CORE0_START])},
                {"start": "0x0008d000", "end_exclusive": "0x02000000",
                 "sha256": sha256(baseline[CORE1_ENVELOPE_END:])},
            ],
            "manifest_operations": 0,
            "mutable_ranges": [
                {"start": "0x00011000", "end_exclusive": "0x00021000"},
                {"start": "0x00021000", "end_exclusive": "0x0008d000"},
            ],
            "elf": {"core0": elf0, "core1": elf1},
            "regions": {
                "core0": {"start": "0x00011000", "length": CORE0_LENGTH,
                          "envelope_length": CORE0.envelope_length,
                          "target_sha256": sha256(target0), **balance0},
                "core1": {"start": "0x00021000", "length": CORE1_LENGTH,
                          "envelope_length": CORE1.envelope_length,
                          "target_sha256": sha256(target1), **balance1},
            },
            "poison": operation_info["poison"],
            "files": {name: {"length": len(data), "sha256": sha256(data)}
                      for name, data in files.items()},
            "reports": {},
            "operation_order_is_normative": True,
            "operations": trace_public,
            "target_full_sha256": operation_info["target_full_sha256"],
            "limitations": [
                "No hardware executor is included.",
                "The bundle is hash-bound but not publisher-signed.",
                "The simulator is not proof of physical power-loss atomicity.",
                "External SPI recovery remains mandatory for any future hardware trial.",
            ],
        }
        simulation_raw = (json.dumps(simulation, indent=2, sort_keys=True) + "\n").encode(
            "utf-8")
        descriptor["reports"] = {
            "simulation.json": {"length": len(simulation_raw),
                                "sha256": sha256(simulation_raw)}
        }
        descriptor["bundle_id"] = canonical_sha256(descriptor_without_id(descriptor))
        (work / "bundle.json").write_text(
            json.dumps(descriptor, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (work / "simulation.json").write_bytes(simulation_raw)
        for raw_name in ("core0.raw", "core1.raw"):
            raw_path = work / raw_name
            if raw_path.exists():
                raw_path.unlink()
        os.replace(work, output)
    return descriptor


def duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_json_constant(value: str) -> object:
    raise PlanError(f"non-finite JSON number is not permitted: {value}")


def load_descriptor(bundle_dir: Path) -> dict[str, object]:
    require(bundle_dir.is_dir() and not bundle_dir.is_symlink(),
            "bundle path is not a regular directory")
    expected = {"bundle.json", "simulation.json", "core0-sector-image.bin",
                "core1-sector-image.bin", "poison-blocks.bin"}
    require({path.name for path in bundle_dir.iterdir()} == expected,
            "bundle directory has missing or extra files")
    raw = read_regular(bundle_dir / "bundle.json")
    try:
        value = json.loads(raw, object_pairs_hook=duplicate_rejecting_object,
                           parse_constant=reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PlanError("bundle.json is not strict JSON") from error
    require(isinstance(value, dict), "bundle descriptor is not an object")
    descriptor = value
    expected_keys = {
        "format", "schema", "offline_only", "device_io", "unsigned",
        "execution_authorized", "flash_approved", "source_policy",
        "baseline_sha256", "source_anchors", "pair_id", "immutable_ranges",
        "manifest_operations", "mutable_ranges", "elf", "regions", "poison",
        "files", "reports", "operation_order_is_normative", "operations",
        "target_full_sha256", "limitations", "bundle_id",
    }
    require(set(descriptor) == expected_keys,
            "bundle descriptor has missing or unknown top-level fields")
    require(isinstance(descriptor.get("operations"), list),
            "bundle operations field is not a list")
    require(descriptor.get("format") == FORMAT and
            type(descriptor.get("schema")) is int and descriptor.get("schema") == 1,
            "unsupported bundle format")
    require(descriptor.get("offline_only") is True and
            descriptor.get("device_io") is False and
            descriptor.get("unsigned") is True and
            descriptor.get("execution_authorized") is False and
            descriptor.get("flash_approved") is False,
            "bundle safety flags are not fail closed")
    require(descriptor.get("source_policy") ==
            "one-time exact V1.22 stock to paired replacement" and
            descriptor.get("operation_order_is_normative") is True and
            type(descriptor.get("manifest_operations")) is int and
            descriptor.get("manifest_operations") == 0 and
            descriptor.get("mutable_ranges") == [
                {"start": "0x00011000", "end_exclusive": "0x00021000"},
                {"start": "0x00021000", "end_exclusive": "0x0008d000"},
            ], "bundle policy/geometry fields are invalid")
    regions = descriptor.get("regions")
    region_keys = {"start", "length", "envelope_length", "target_sha256",
                   "fixup_offset", "fixup_bytes", "fixup_rank", "gate_offset",
                   "gate_final_bytes", "gate_rank", "staged_checksum",
                   "target_checksum"}
    require(isinstance(regions, dict) and set(regions) == {"core0", "core1"} and
            all(isinstance(value, dict) and set(value) == region_keys
                for value in regions.values()),
            "bundle region schema is invalid")
    bundle_id = descriptor.get("bundle_id")
    require(isinstance(bundle_id, str) and len(bundle_id) == 64 and
            bundle_id == canonical_sha256(descriptor_without_id(descriptor)),
            "bundle content identifier does not verify")
    files = descriptor.get("files")
    require(isinstance(files, dict) and set(files) ==
            {"core0-sector-image.bin", "core1-sector-image.bin", "poison-blocks.bin"},
            "bundle payload declaration is invalid")
    for name, expected_file in files.items():
        require(isinstance(expected_file, dict), "invalid payload declaration")
        data = read_regular(bundle_dir / name)
        if name.startswith("core0"):
            required_length = CORE0.envelope_length
        elif name.startswith("core1"):
            required_length = CORE1.envelope_length
        else:
            required_length = 2 * BLOCK_BYTES
        require(type(expected_file.get("length")) is int and
                expected_file.get("length") == required_length and
                len(data) == required_length and
                sha256(data) == expected_file.get("sha256"),
                f"bundle payload {name} does not verify")
    reports = descriptor.get("reports")
    require(isinstance(reports, dict) and set(reports) == {"simulation.json"},
            "bundle report declaration is invalid")
    simulation_declaration = reports["simulation.json"]
    require(isinstance(simulation_declaration, dict), "invalid simulation declaration")
    simulation_raw = read_regular(bundle_dir / "simulation.json")
    require(type(simulation_declaration.get("length")) is int and
            len(simulation_raw) == simulation_declaration.get("length") and
            sha256(simulation_raw) == simulation_declaration.get("sha256"),
            "simulation report does not verify")
    try:
        simulation = json.loads(simulation_raw,
                                object_pairs_hook=duplicate_rejecting_object,
                                parse_constant=reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PlanError("simulation.json is not strict JSON") from error
    require(isinstance(simulation, dict) and
            simulation.get("format") == SIMULATION_FORMAT and
            simulation.get("offline_only") is True and
            simulation.get("hardware_execution_authorized") is False and
            simulation.get("flash_approved") is False and
            type(simulation.get("operation_count")) is int and
            simulation.get("operation_count") == len(descriptor.get("operations", [])) and
            simulation.get("early_checksum_valid_non_target_states") == 0,
            "simulation report does not carry the required fail-closed result")
    return descriptor


def verify_bundle(bundle_dir: Path, baseline_a: Path, baseline_b: Path,
                  *, anchors: dict[str, str] | None = None) -> dict[str, object]:
    descriptor = load_descriptor(bundle_dir)
    baseline = load_baselines(baseline_a, baseline_b)
    expected_anchors = STOCK_SHA256 if anchors is None else anchors
    validate_baseline(baseline, expected_anchors)
    require(sha256(baseline) == descriptor.get("baseline_sha256"),
            "bundle was planned for a different baseline")
    require(descriptor.get("source_anchors") == expected_anchors,
            "bundle source anchors do not match the verifier")
    require(type(descriptor.get("manifest_operations")) is int and
            descriptor.get("manifest_operations") == 0,
            "bundle attempts to mutate the manifest")
    immutable = descriptor.get("immutable_ranges")
    require(immutable == [
        {"start": "0x00000000", "end_exclusive": "0x00011000",
         "sha256": sha256(baseline[:CORE0_START])},
        {"start": "0x0008d000", "end_exclusive": "0x02000000",
         "sha256": sha256(baseline[CORE1_ENVELOPE_END:])},
    ], "bundle immutable-range binding is invalid")
    targets = {
        "core0": read_regular(bundle_dir / "core0-sector-image.bin")[:CORE0_LENGTH],
        "core1": read_regular(bundle_dir / "core1-sector-image.bin")[:CORE1_LENGTH],
    }
    pair_id_text = descriptor.get("pair_id")
    require(isinstance(pair_id_text, str) and len(pair_id_text) == PAIR_ID_BYTES * 2,
            "bundle pair identifier is invalid")
    try:
        pair_id = bytes.fromhex(pair_id_text)
    except ValueError as error:
        raise PlanError("bundle pair identifier is not hexadecimal") from error
    region_metadata = descriptor.get("regions")
    require(isinstance(region_metadata, dict) and set(region_metadata) ==
            {"core0", "core1"}, "bundle region metadata is invalid")
    staged: dict[str, bytes] = {}
    for spec in REGIONS:
        envelope = read_regular(bundle_dir / f"{spec.name}-sector-image.bin")
        require(envelope[spec.length:] == b"\xff" * (len(envelope) - spec.length),
                f"{spec.name} sector-tail padding is not erased")
        staged[spec.name] = validate_target_region(
            targets[spec.name], spec, pair_id, region_metadata[spec.name])
    operations, operation_info = build_operations(baseline, targets, staged)
    traces, simulation = simulate(baseline, targets, staged, operations)
    require(traces == descriptor.get("operations"), "bundle operation plan is not canonical")
    require(operation_info["poison"] == descriptor.get("poison"),
            "bundle poison barriers are not canonical")
    require(read_regular(bundle_dir / "poison-blocks.bin") ==
            operation_info["poison_payload"],
            "bundle poison payloads are not canonical")
    require(operation_info["target_full_sha256"] == descriptor.get("target_full_sha256"),
            "bundle target full-image binding does not verify")
    try:
        saved_simulation = json.loads(
            read_regular(bundle_dir / "simulation.json"),
            object_pairs_hook=duplicate_rejecting_object,
            parse_constant=reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PlanError("simulation.json is not strict JSON") from error
    require(saved_simulation == simulation,
            "saved simulation report differs from independent recomputation")
    simulation["bundle_id"] = descriptor["bundle_id"]
    return simulation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build", help="build and simulate an offline bundle")
    build_parser.add_argument("--baseline-a", required=True, type=Path)
    build_parser.add_argument("--baseline-b", required=True, type=Path)
    build_parser.add_argument("--core0-elf", required=True, type=Path)
    build_parser.add_argument("--core1-elf", required=True, type=Path)
    build_parser.add_argument("--out", required=True, type=Path)
    build_parser.add_argument("--cross-prefix", default="arm-none-eabi-")
    verify_parser = subparsers.add_parser("simulate", help="reverify and resimulate a bundle")
    verify_parser.add_argument("--baseline-a", required=True, type=Path)
    verify_parser.add_argument("--baseline-b", required=True, type=Path)
    verify_parser.add_argument("--bundle", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build_bundle(args.baseline_a.resolve(), args.baseline_b.resolve(),
                                  args.core0_elf.resolve(), args.core1_elf.resolve(),
                                  args.out.resolve(), args.cross_prefix)
            print(json.dumps({"bundle_id": result["bundle_id"],
                              "operations": len(result["operations"]),
                              "offline_only": True,
                              "flash_approved": False}, indent=2, sort_keys=True))
        else:
            result = verify_bundle(args.bundle.resolve(), args.baseline_a.resolve(),
                                   args.baseline_b.resolve())
            print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, PlanError, ValueError) as error:
        print(f"updater plan error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
