#!/usr/bin/env python3
"""Build and verify the fixed V1.22 region-1 loader-reentry proof campaign.

This tool is offline-only.  It turns the default-off ``region1-reentry-proof``
ELF and two exact owner baseline captures into a private campaign directory.

Stock region 0 ("Core 0") stays installed and untouched.  The campaign
patches one region-1 flash sector, the one holding the stock application
entry 0x1004a524, so that the proof image replaces the stock main routine in
place, then CRC-balances that sector to the unchanged manifest checksum.  The
loader, header, manifest and region 0 keep every byte; region 1 keeps every
byte outside the patch sector and one temporary poison sector.

Barriers while region 1 is rebuilt:

1. one reviewed erased bit in a separate stock region-1 sector is cleared
   first, so region 1 is checksum-invalid before any erase begins;
2. the patch sector is rebuilt with its final four-byte checksum gate left
   erased, so no intermediate state of that sector can validate;
3. the poison sector is erased and programmed back to exact stock while the
   gate is still erased; and
4. the sparse gate is programmed last.

The restore direction repeats the structure back to exact stock.  Every
byte-prefix state of every operation is enumerated and its region-1 checksum
computed; none may validate except the two exact targets.

No USB library is imported and no hardware execution is authorized here.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zlib
from typing import Callable


TOOL_DIRECTORY = Path(__file__).resolve().parent


def _load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load required module: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


_planner = _load_module(
    "kb7_updater_plan_for_region1_reentry_campaign",
    TOOL_DIRECTORY / "kb7-updater-plan.py")
_core0_campaign = _load_module(
    "kb7_loader_reentry_campaign_for_region1_reentry_campaign",
    TOOL_DIRECTORY / "kb7-loader-reentry-campaign.py")

PlanError = _planner.PlanError

FORMAT = "KB7 V1.22 fixed region-1 loader-reentry proof campaign v1"
SIMULATION_FORMAT = "KB7 region-1 patch install/restore simulation v1"
CAMPAIGN_SCHEMA = 1
EXPECTED_BASELINE_SHA256 = (
    "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f")
REGION1_VMA = 0x10000000
REGION1_ENTRY = 0x1004A525
PATCH_OFFSET = REGION1_ENTRY - REGION1_VMA - 1  # 0x4a524, region-1 relative
PATCH_SECTOR = PATCH_OFFSET & ~(0x1000 - 1)      # 0x4a000
PATCH_SECTOR_END = PATCH_SECTOR + 0x1000
EXPECTED_PROOF_RAW = {
    "entry": f"0x{REGION1_ENTRY:08x}",
    "raw_length": 404,
    "raw_sha256": (
        "e753380b3c0ce9fb28f69f4d9d066d0877cbd612dedd37149290556420d29356"),
}
PATCH_SECTOR_NAME = "proof-core1-patch-sector.bin"
CAMPAIGN_NAME = "campaign.json"
SIMULATION_NAME = "simulation.json"

SECTOR = _planner.SECTOR_BYTES
BLOCK = _planner.BLOCK_BYTES
SPEC = _planner.CORE1


@dataclass(frozen=True)
class Campaign:
    baseline: bytes
    proof_image: bytes
    operations: tuple[object, ...]
    install_operation_count: int
    descriptor: dict[str, object]

    @property
    def restore_operation_count(self) -> int:
        return len(self.operations) - self.install_operation_count


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Proof ELF extraction


def _section_rows(section_headers: str) -> list[tuple[str, str, int, int, str]]:
    rows = []
    for line in section_headers.splitlines():
        match = re.match(
            r"^\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-fA-F]{8})\s+"
            r"([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+\S+\s+(\S*)\s", line)
        if match:
            name, kind, address, _offset, size, flags = match.groups()
            rows.append((name, kind, int(address, 16), int(size, 16), flags))
    return rows


def inspect_and_extract(elf: Path, prefix: str,
                        destination: Path) -> tuple[bytes, dict[str, object]]:
    """Extract the proof's single code section and prove its placement."""

    _planner.read_regular(elf)
    tools = {name: shutil.which(f"{prefix}{name}")
             for name in ("objcopy", "readelf", "nm")}
    require(all(tools.values()), f"missing ARM binutils for prefix {prefix!r}")
    header = _planner.run([tools["readelf"] or "", "-h", str(elf)])
    require("ELF32" in header and "little endian" in header and
            "EXEC" in header and "ARM" in header,
            f"not an ELF32 little-endian ARM executable: {elf}")
    entry_line = next((line for line in header.splitlines()
                       if "Entry point address:" in line), "")
    require(entry_line, f"ELF has no entry point: {elf}")
    entry = int(entry_line.rsplit(maxsplit=1)[1], 16)
    require(entry == REGION1_ENTRY,
            "region-1 proof entry is not the stock application entry")
    require("There are no relocations" in
            _planner.run([tools["readelf"] or "", "-r", str(elf)]),
            f"ELF contains relocations: {elf}")
    require(not _planner.run([tools["nm"] or "", "-u", str(elf)]).strip(),
            f"ELF contains undefined symbols: {elf}")
    rows = _section_rows(_planner.run([tools["readelf"] or "", "-SW", str(elf)]))
    code = [row for row in rows if "X" in row[4] and row[3] > 0]
    require(len(code) == 1 and code[0][0] == ".text",
            "proof ELF must have exactly one executable section")
    loaded = [row for row in rows
              if row[1] == "PROGBITS" and "A" in row[4] and row[3] > 0]
    require(loaded == code, "proof ELF carries loaded bytes beyond its code")
    _name, _kind, address, size, _flags = code[0]
    require(address == REGION1_VMA + PATCH_OFFSET and
            address + size <= REGION1_VMA + PATCH_SECTOR_END,
            "proof code is not confined to the entry's flash sector")
    _planner.run([tools["objcopy"] or "", "-O", "binary", str(elf), str(destination)])
    raw = _planner.read_regular(destination)
    require(len(raw) == size, "extracted proof length differs from its section")
    return raw, {"entry": f"0x{entry:08x}", "raw_length": len(raw),
                 "elf_sha256": sha256(_planner.read_regular(elf)),
                 "raw_sha256": sha256(raw)}


def _verify_proof_symbols(elf: Path, prefix: str) -> None:
    nm = shutil.which(f"{prefix}nm")
    require(nm is not None, f"missing ARM nm for prefix {prefix!r}")
    symbols = _planner.run([nm, "-g", str(elf)])
    for required in ("region1_proof_entry", "region1_proof_main",
                     "kb7_loader_trampoline_relocate_and_enter",
                     "kb7_loader_trampoline_blob_start",
                     "kb7_loader_trampoline_start"):
        require(required in symbols, f"proof ELF is missing {required}")
    for forbidden in ("core0_main", "core1_entry", "kb7_application_main",
                      "kb7_usb_init", "kb7_flash_program_block",
                      "kb7_flash_erase_sector", "kb7_memcpy"):
        require(forbidden not in symbols,
                f"proof ELF unexpectedly retains {forbidden}")


# ---------------------------------------------------------------------------
# Target construction


def _chunk_bounds(offset: int) -> tuple[int, int]:
    start = (offset // 0x10000) * 0x10000
    return start, min(start + 0x10000, SPEC.length)


def _balance(region: bytearray, fixup_offset: int) -> tuple[bytes, int]:
    """Solve the fixup word so the region reaches the manifest checksum."""

    chunk_start, chunk_end = _chunk_bounds(fixup_offset)
    other_sum = sum(zlib.crc32(region[offset:min(offset + 0x10000, SPEC.length)]) &
                    0xFFFFFFFF for offset in range(0, SPEC.length, 0x10000)
                    if offset != chunk_start) & 0xFFFFFFFF
    wanted = (SPEC.manifest_checksum - other_sum) & 0xFFFFFFFF
    patch, rank = _planner.crc_patch(
        bytes(region[chunk_start:chunk_end]), fixup_offset - chunk_start, wanted)
    return patch, rank


def build_patched_region(stock: bytes, raw: bytes) -> tuple[bytes, bytes, dict[str, object]]:
    """Patch the proof into stock region 1 and balance the checksum.

    Returns ``(target, staged, metadata)``.  ``target`` is the exact
    checksum-valid region; ``staged`` is ``target`` with its gate word
    erased and is checksum-invalid.  Only bytes inside the patch sector
    differ from stock.
    """

    require(len(stock) == SPEC.length, "stock region 1 has the wrong length")
    require(_planner.fwin_checksum(stock) == SPEC.manifest_checksum,
            "stock region 1 does not carry the manifest checksum")
    require(raw and len(raw) % 4 == 0 and
            PATCH_OFFSET + len(raw) + 8 <= PATCH_SECTOR_END,
            "proof code plus fixup and gate words do not fit the patch sector")
    fixup_offset = PATCH_OFFSET + len(raw)
    gate_offset = fixup_offset + 4
    region = bytearray(stock)
    region[PATCH_OFFSET:PATCH_OFFSET + len(raw)] = raw
    region[gate_offset:gate_offset + 4] = b"\0" * 4
    patch, patch_rank = _balance(region, fixup_offset)
    region[fixup_offset:fixup_offset + 4] = patch
    require(patch != b"\xff" * 4, "CRC correction is an erased word")
    target = bytes(region)
    require(_planner.fwin_checksum(target) == SPEC.manifest_checksum,
            "balanced region does not match the unchanged manifest")
    staged_data = bytearray(target)
    staged_data[gate_offset:gate_offset + 4] = b"\xff" * 4
    staged = bytes(staged_data)
    require(_planner.fwin_checksum(staged) != SPEC.manifest_checksum,
            "staged region is unexpectedly loader-valid")
    chunk_start, chunk_end = _chunk_bounds(gate_offset)
    gate_rank = _planner.crc_word_rank(target[chunk_start:chunk_end],
                                       gate_offset - chunk_start)
    require(patch_rank == 32 and gate_rank == 32,
            "CRC correction/gate transform is not bijective")
    require(target[:PATCH_SECTOR] == stock[:PATCH_SECTOR] and
            target[PATCH_SECTOR_END:] == stock[PATCH_SECTOR_END:],
            "patched region differs from stock outside the patch sector")
    metadata = {
        "patch_offset": f"0x{PATCH_OFFSET:08x}",
        "patch_length": len(raw),
        "patch_sector_offset": f"0x{PATCH_SECTOR:08x}",
        "absolute_patch_sector_offset": f"0x{SPEC.start + PATCH_SECTOR:08x}",
        "fixup_offset": f"0x{fixup_offset:08x}",
        "fixup_bytes": patch.hex(),
        "fixup_rank": patch_rank,
        "gate_offset": f"0x{gate_offset:08x}",
        "gate_final_bytes": "00000000",
        "gate_rank": gate_rank,
        "staged_checksum": f"0x{_planner.fwin_checksum(staged):08x}",
        "target_checksum": f"0x{_planner.fwin_checksum(target):08x}",
        "target_sha256": sha256(target),
        "target_sector_sha256": sha256(target[PATCH_SECTOR:PATCH_SECTOR_END]),
    }
    return target, staged, metadata


def restore_gate_offset(stock: bytes) -> int:
    """A full-rank stock word inside the patch sector for the restore gate."""

    chunk_start, chunk_end = _chunk_bounds(PATCH_SECTOR)
    chunk = stock[chunk_start:chunk_end]
    for offset in range(PATCH_SECTOR, PATCH_SECTOR_END, 4):
        if stock[offset:offset + 4] != b"\xff" * 4 and \
                _planner.crc_word_rank(chunk, offset - chunk_start) == 32:
            return offset
    raise PlanError("stock patch sector has no full-rank restore gate")


def staged_with_gate(target: bytes, gate_offset: int) -> bytes:
    staged = bytearray(target)
    staged[gate_offset:gate_offset + 4] = b"\xff" * 4
    require(bytes(staged) != target, "gate word would be an erased no-op")
    require(_planner.fwin_checksum(staged) != SPEC.manifest_checksum,
            "staged region is unexpectedly loader-valid")
    return bytes(staged)


# ---------------------------------------------------------------------------
# Operation sequences


def _append_stage_patch_sector(operations: list[object], current: bytearray,
                               staged: bytes, *, phase: str,
                               payload_source: str) -> None:
    sector = SPEC.start + PATCH_SECTOR
    desired = staged[PATCH_SECTOR:PATCH_SECTOR_END]
    before = bytes(current[sector:sector + SECTOR])
    require(before != desired, f"{phase} has nothing to stage")
    if not all((old & new) == new for old, new in zip(before, desired)):
        erase = _planner.Operation(phase, "erase", sector, None, None, None)
        operations.append(erase)
        _planner.apply_operation(current, erase)
    for block_relative in range(0, SECTOR, BLOCK):
        payload = desired[block_relative:block_relative + BLOCK]
        block = sector + block_relative
        if bytes(current[block:block + BLOCK]) == payload:
            continue
        require(payload != b"\xff" * BLOCK, "campaign attempted an all-erased program")
        require(all((old & new) == new for old, new in
                    zip(current[block:block + BLOCK], payload)),
                "campaign attempted a 0-to-1 program")
        program = _planner.Operation(
            phase, "program", block, payload, payload_source, block_relative)
        operations.append(program)
        _planner.apply_operation(current, program)
    require(bytes(current[sector:sector + SECTOR]) == desired,
            f"{phase} did not converge to the exact staged sector")


def _append_commit(operations: list[object], current: bytearray, target: bytes,
                   *, phase: str, payload_source: str, gate_offset: int) -> None:
    block_relative = gate_offset & ~(BLOCK - 1)
    payload = target[block_relative:block_relative + BLOCK]
    operation = _planner.Operation(
        phase, "program", SPEC.start + block_relative, payload, payload_source,
        block_relative - PATCH_SECTOR)
    operations.append(operation)
    _planner.apply_operation(current, operation)
    require(bytes(current[SPEC.start:SPEC.start + SPEC.length]) == target,
            f"{phase} did not produce its exact target")


def _restore_poison_sector(operations: list[object], current: bytearray,
                           baseline: bytes, poison: dict[str, object], *,
                           phase_prefix: str) -> dict[str, object]:
    """Erase and program the poison sector back to exact stock.

    The patch sector is staged and checksum-invalid while this runs, so only
    the poison sector is compared with stock; every other region-1 byte must
    be untouched by these operations.
    """

    poison_absolute = int(str(poison["byte_offset"]), 0)
    sector_absolute = poison_absolute & ~(SECTOR - 1)
    require(sector_absolute != SPEC.start + PATCH_SECTOR,
            "poison sector coincides with the patch sector")
    sector_relative = sector_absolute - SPEC.start
    stock_sector = baseline[sector_absolute:sector_absolute + SECTOR]
    before_rest = bytes(current[SPEC.start:sector_absolute]) + bytes(
        current[sector_absolute + SECTOR:SPEC.start + SPEC.length])
    phase = f"{phase_prefix}_stage_core1_barrier"
    erase = _planner.Operation(phase, "erase", sector_absolute, None, None, None)
    operations.append(erase)
    _planner.apply_operation(current, erase)
    for block_relative in range(0, SECTOR, BLOCK):
        payload = stock_sector[block_relative:block_relative + BLOCK]
        if payload == b"\xff" * BLOCK:
            continue
        program = _planner.Operation(
            phase, "program", sector_absolute + block_relative, payload,
            "baseline-core1", sector_relative + block_relative)
        operations.append(program)
        _planner.apply_operation(current, program)
    require(bytes(current[sector_absolute:sector_absolute + SECTOR]) == stock_sector,
            "poison sector restoration is not exact stock")
    after_rest = bytes(current[SPEC.start:sector_absolute]) + bytes(
        current[sector_absolute + SECTOR:SPEC.start + SPEC.length])
    require(after_rest == before_rest,
            "poison sector restoration touched another sector")
    return {
        "sector_offset": f"0x{sector_relative:08x}",
        "absolute_sector_offset": f"0x{sector_absolute:08x}",
        "restored_sector_sha256": sha256(stock_sector),
        "safety_barrier": "region-1 checksum gate remains erased throughout",
    }


# ---------------------------------------------------------------------------
# Simulation


def _prefix_states(pre_unit: bytes, post_unit: bytes, action: str):
    """Yield every distinct modeled byte-prefix outcome of one operation."""

    seen: set[bytes] = set()
    for cut in range(0, len(pre_unit) + 1):
        state = _planner.prefix_outcome(pre_unit, post_unit, action, cut)
        if state not in seen:
            seen.add(state)
            yield cut, state


def _simulate(baseline: bytes, proof_image: bytes,
              operations: tuple[object, ...], install_count: int,
              install_gate: int, restore_gate: int,
              poison_sector: int) -> tuple[list[dict[str, object]], dict[str, object]]:
    current = bytearray(baseline)
    immutable = (baseline[:SPEC.start] + baseline[SPEC.start + SPEC.length:])
    patch_sector = SPEC.start + PATCH_SECTOR
    traces: list[dict[str, object]] = []
    prefix_states = 0
    distinct_prefix_states = 0
    poison_prefix_states = 0
    gate_proofs = 0
    early_valid = 0
    for index, operation in enumerate(operations):
        pre = bytes(current)
        unit_start = operation.offset
        unit_end = unit_start + operation.length
        pre_unit = pre[unit_start:unit_end]
        _planner.apply_operation(current, operation)
        post = bytes(current)
        post_unit = post[unit_start:unit_end]
        require(pre_unit != post_unit, f"operation {index} is a no-op")
        require(_planner.transition_reachable(
            pre_unit, post_unit, post_unit, operation.action),
            f"operation {index} violates modeled NOR direction")
        require(post[:SPEC.start] + post[SPEC.start + SPEC.length:] == immutable,
                f"operation {index} changes an immutable range")
        sector = unit_start & ~(SECTOR - 1)
        require(sector in (patch_sector, poison_sector) and
                unit_end <= sector + SECTOR,
                f"operation {index} escapes the patch and poison sectors")
        at_install_target = index + 1 == install_count and post == proof_image
        at_restore_target = index + 1 == len(operations) and post == baseline
        checksum_valid = _planner.core_checksums(post)[1] == SPEC.manifest_checksum
        if checksum_valid and not (at_install_target or at_restore_target):
            early_valid += 1
        require(_planner.core_checksums(post)[0] == _planner.CORE0.manifest_checksum,
                f"operation {index} disturbed region 0")

        # Exhaustive byte-prefix enumeration: every distinct modeled outcome
        # of an interrupted program or erase is checked for loader validity.
        # Cut 0 is the exact pre-image, which is loader-valid only at the two
        # stable endpoints (exact stock before the first install operation
        # and the exact proof image before the first restore operation).
        pre_is_stable = pre == baseline or pre == proof_image
        region_state = bytearray(pre[SPEC.start:SPEC.start + SPEC.length])
        relative_start = unit_start - SPEC.start
        for cut, state in _prefix_states(pre_unit, post_unit, operation.action):
            region_state[relative_start:relative_start + len(state)] = state
            valid = _planner.fwin_checksum(bytes(region_state)) == \
                SPEC.manifest_checksum
            allowed = ((state == pre_unit and pre_is_stable) or
                       (state == post_unit and
                        (at_install_target or at_restore_target)))
            require(not valid or allowed,
                    f"operation {index} has a loader-valid prefix state at cut {cut}")
            distinct_prefix_states += 1
        prefix_states += operation.length + 1

        if "poison" in operation.phase:
            changed = [position for position, (left, right) in enumerate(
                zip(pre_unit, post_unit)) if left != right]
            require(len(changed) == 1 and
                    (pre_unit[changed[0]] ^ post_unit[changed[0]]).bit_count() == 1,
                    f"operation {index} poison is not exactly one bit")
            poison_prefix_states += operation.length + 1
        if operation.phase.endswith("commit"):
            gate = install_gate if operation.phase.startswith("install") else restore_gate
            relative = unit_start - SPEC.start
            changed = [position for position, (left, right) in enumerate(
                zip(pre_unit, post_unit)) if left != right]
            require(changed and min(changed) >= gate - relative and
                    max(changed) < gate - relative + 4,
                    f"operation {index} commit changes more than its gate word")
            region = post[SPEC.start:SPEC.start + SPEC.length]
            chunk_start, chunk_end = _chunk_bounds(gate)
            require(_planner.crc_word_rank(region[chunk_start:chunk_end],
                                           gate - chunk_start) == 32,
                    f"operation {index} gate is not bijective")
            require(checksum_valid, f"operation {index} gate does not validate")
            gate_proofs += 1
        traces.append(_core0_campaign._operation_descriptor(index, operation, pre, post))

    require(bytes(current) == baseline,
            "combined campaign does not restore the exact full baseline")
    require(early_valid == 0, "campaign has an early loader-valid non-target")
    return traces, {
        "format": SIMULATION_FORMAT,
        "offline_only": True,
        "hardware_execution_authorized": False,
        "flash_approved": False,
        "operation_count": len(operations),
        "install_operation_count": install_count,
        "restore_operation_count": len(operations) - install_count,
        "command_boundaries_checked": len(operations) + 1,
        "modeled_byte_prefix_states_checked": prefix_states,
        "distinct_prefix_states_evaluated": distinct_prefix_states,
        "single_bit_poison_prefix_states_checked": poison_prefix_states,
        "sparse_gate_subset_proofs": gate_proofs,
        "early_loader_valid_non_target_states": early_valid,
        "region0_operation_count": 0,
        "patch_sector": f"0x{patch_sector:08x}",
        "poison_sector": f"0x{poison_sector:08x}",
        "preserved_boot_region_operation_count": 0,
        "install_gate_offset": f"0x{install_gate:08x}",
        "restore_gate_offset": f"0x{restore_gate:08x}",
        "invariants_passed": [
            "the patch sector and one fixed poison sector contain all operations",
            "header, loader, manifest, region 0 and all flash after region 1 remain exact",
            "region 0 keeps its manifest checksum at every command boundary",
            "region 1 is checksum-invalid at every non-target command boundary",
            "every distinct byte-prefix state of every operation is checksum-invalid",
            "each poison is exactly one requested bit",
            "each final one-word gate is a rank-32 unique checksum solution",
            "the install target is the exact checksum-valid proof image",
            "the restore target is the exact full-chip baseline",
        ],
        "proof_boundary": (
            "Command boundaries, exact payloads and every modeled byte-prefix state "
            "are covered by direct checksum evaluation. Misaddressing, disturb, "
            "arbitrary physical torn-NOR behavior and loader-model errors still "
            "require external SPI recovery."),
    }


# ---------------------------------------------------------------------------
# Derivation


def _derive(baseline: bytes, proof_elf: Path, prefix: str, work: Path,
            *, anchors: dict[str, str] | None = None,
            proof_identity: dict[str, object] | None = None,
            extractor: Callable | None = None
            ) -> tuple[dict[str, object], dict[str, bytes], Campaign]:
    anchors = _planner.STOCK_SHA256 if anchors is None else anchors
    proof_identity = EXPECTED_PROOF_RAW if proof_identity is None else proof_identity
    baseline_info = _planner.validate_baseline(baseline, anchors)
    require(baseline_info["sha256"] == EXPECTED_BASELINE_SHA256 or
            anchors is not _planner.STOCK_SHA256,
            "baseline full-chip SHA-256 is not the exact reviewed V1.22 capture")
    if extractor is None:
        _verify_proof_symbols(proof_elf, prefix)
        raw, elf_info = inspect_and_extract(proof_elf, prefix, work / "proof-core1.raw")
    else:
        raw, elf_info = extractor(proof_elf, prefix, work / "proof-core1.raw")
    require({key: elf_info.get(key) for key in proof_identity} == proof_identity,
            "proof raw identity is not the reviewed region1-reentry-proof image")

    stock = baseline[SPEC.start:SPEC.start + SPEC.length]
    target, staged_install, target_metadata = build_patched_region(stock, raw)
    install_gate = int(str(target_metadata["gate_offset"]), 0)
    proof_image_mutable = bytearray(baseline)
    proof_image_mutable[SPEC.start:SPEC.start + SPEC.length] = target
    proof_image = bytes(proof_image_mutable)

    current = bytearray(baseline)
    operations: list[object] = []
    install_poison = _core0_campaign._append_poison(
        operations, current, SPEC, phase="install_poison_core1")
    _append_stage_patch_sector(
        operations, current, staged_install, phase="install_stage_core1_patch",
        payload_source=PATCH_SECTOR_NAME)
    install_barrier = _restore_poison_sector(
        operations, current, baseline, install_poison, phase_prefix="install")
    _append_commit(operations, current, target, phase="install_commit",
                   payload_source=PATCH_SECTOR_NAME, gate_offset=install_gate)
    require(bytes(current) == proof_image,
            "install sequence does not produce the exact proof image")
    install_count = len(operations)

    restore_poison = _core0_campaign._append_poison(
        operations, current, SPEC, phase="restore_poison_core1")
    restore_gate = restore_gate_offset(stock)
    staged_restore = staged_with_gate(stock, restore_gate)
    _append_stage_patch_sector(
        operations, current, staged_restore, phase="restore_stage_core1_patch",
        payload_source="baseline-core1")
    restore_barrier = _restore_poison_sector(
        operations, current, baseline, restore_poison, phase_prefix="restore")
    _append_commit(operations, current, stock, phase="restore_commit",
                   payload_source="baseline-core1", gate_offset=restore_gate)
    require(bytes(current) == baseline,
            "restore sequence does not produce the exact baseline")

    operation_tuple = tuple(operations)
    poison_sector = int(str(install_barrier["absolute_sector_offset"]), 0)
    require(restore_barrier["absolute_sector_offset"] ==
            install_barrier["absolute_sector_offset"],
            "install and restore did not use one fixed poison sector")
    traces, simulation = _simulate(
        baseline, proof_image, operation_tuple, install_count, install_gate,
        restore_gate, poison_sector)
    simulation_raw = (json.dumps(
        simulation, indent=2, sort_keys=True) + "\n").encode("utf-8")
    patch_sector_bytes = target[PATCH_SECTOR:PATCH_SECTOR_END]
    files = {
        PATCH_SECTOR_NAME: patch_sector_bytes,
        SIMULATION_NAME: simulation_raw,
    }
    descriptor: dict[str, object] = {
        "format": FORMAT,
        "schema": CAMPAIGN_SCHEMA,
        "offline_only": True,
        "device_io": False,
        "execution_authorized": False,
        "flash_approved": False,
        "campaign_self_authorizes_execution": False,
        "requires_separate_executor_authorization": True,
        "source_policy": (
            "exact V1.22 stock -> one patched region-1 sector holding the "
            "fixed proof at the stock entry -> exact stock"),
        "baseline_sha256": sha256(baseline),
        "proof_full_sha256": sha256(proof_image),
        "source_anchors": dict(anchors),
        "preserved_regions": [
            *_planner.preserved_boot_regions(baseline),
            {
                "name": "core0-envelope",
                "start": f"0x{_planner.CORE0_START:08x}",
                "end_exclusive": f"0x{_planner.CORE0_ENVELOPE_END:08x}",
                "sha256": sha256(baseline[
                    _planner.CORE0_START:_planner.CORE0_ENVELOPE_END]),
            },
            {
                "name": "after-core1-envelope",
                "start": f"0x{_planner.CORE1_ENVELOPE_END:08x}",
                "end_exclusive": f"0x{_planner.FLASH_BYTES:08x}",
                "sha256": sha256(baseline[
                    _planner.CORE1_ENVELOPE_END:_planner.FLASH_BYTES]),
            },
        ],
        "mutable_ranges": [
            {
                "start": f"0x{SPEC.start + PATCH_SECTOR:08x}",
                "end_exclusive": f"0x{SPEC.start + PATCH_SECTOR_END:08x}",
            },
            {
                "start": install_barrier["absolute_sector_offset"],
                "end_exclusive": f"0x{poison_sector + SECTOR:08x}",
            },
        ],
        "proof_raw": {
            "entry": elf_info["entry"],
            "raw_length": elf_info["raw_length"],
            "raw_sha256": elf_info["raw_sha256"],
        },
        "proof_core1": target_metadata,
        "install_poison": install_poison,
        "install_barrier": install_barrier,
        "restore_poison": restore_poison,
        "restore_barrier": restore_barrier,
        "restore_gate": {
            "offset": f"0x{restore_gate:08x}",
            "absolute_offset": f"0x{SPEC.start + restore_gate:08x}",
            "target_word": stock[restore_gate:restore_gate + 4].hex(),
            "rank": 32,
        },
        "install_operation_count": install_count,
        "restore_operation_count": len(operation_tuple) - install_count,
        "operation_count": len(operation_tuple),
        "operations": traces,
        "files": {
            name: {"length": len(data), "sha256": sha256(data)}
            for name, data in files.items()
        },
        "policy": {
            "one_operation_per_cli_invocation": True,
            "two_exact_full_chip_reads_before_and_after": True,
            "durable_intent_before_usb_open": True,
            "automatic_retry": False,
            "transport_anomaly_requires_external_spi": True,
            "proof_reentry_requires_new_usb_enumeration": True,
            "generic_firmware_executor_remains_locked": True,
            "region0_operations": 0,
        },
        "limitations": [
            "This descriptor does not authorize live hardware execution.",
            "The custom proof path remains hardware-unrun.",
            "Physical torn-NOR, misaddressing, and disturb remain SPI-recovery cases.",
            "A new USB enumeration supports but cannot prove the cause of loader entry.",
            "Execution requires the separately gated fixed executor revision bound to this format.",
        ],
    }
    descriptor["campaign_id"] = _planner.canonical_sha256(descriptor)
    return descriptor, files, Campaign(
        baseline=baseline,
        proof_image=proof_image,
        operations=operation_tuple,
        install_operation_count=install_count,
        descriptor=descriptor,
    )


def build_campaign(baseline_a: Path, baseline_b: Path, proof_elf: Path,
                   output: Path, prefix: str,
                   *, anchors: dict[str, str] | None = None,
                   proof_identity: dict[str, object] | None = None,
                   extractor: Callable | None = None) -> dict[str, object]:
    require(output.parent.is_dir(), "campaign output parent does not exist")
    require(not output.exists(), "refusing to replace an existing campaign")
    baseline = _planner.load_baselines(baseline_a, baseline_b)
    with tempfile.TemporaryDirectory(
            prefix="kb7-region1-reentry-campaign-", dir=output.parent) as temporary:
        work = Path(temporary)
        descriptor, files, _campaign = _derive(
            baseline, proof_elf, prefix, work, anchors=anchors,
            proof_identity=proof_identity, extractor=extractor)
        for name, data in files.items():
            (work / name).write_bytes(data)
        (work / CAMPAIGN_NAME).write_text(
            json.dumps(descriptor, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        raw = work / "proof-core1.raw"
        if raw.exists():
            raw.unlink()
        os.replace(work, output)
    return descriptor


def load_campaign(campaign_dir: Path, baseline_a: Path, baseline_b: Path,
                  proof_elf: Path, prefix: str,
                  *, anchors: dict[str, str] | None = None,
                  proof_identity: dict[str, object] | None = None,
                  extractor: Callable | None = None) -> Campaign:
    require(campaign_dir.is_dir() and not campaign_dir.is_symlink(),
            "campaign path is not a regular directory")
    require({path.name for path in campaign_dir.iterdir()} == {
        CAMPAIGN_NAME, PATCH_SECTOR_NAME, SIMULATION_NAME},
        "campaign directory has missing or extra files")
    saved = _core0_campaign._load_json(campaign_dir / CAMPAIGN_NAME)
    campaign_id = saved.get("campaign_id")
    require(isinstance(campaign_id, str) and len(campaign_id) == 64,
            "campaign identifier is malformed")
    without_id = dict(saved)
    without_id.pop("campaign_id", None)
    require(campaign_id == _planner.canonical_sha256(without_id),
            "campaign identifier does not verify")
    baseline = _planner.load_baselines(baseline_a, baseline_b)
    with tempfile.TemporaryDirectory(prefix="kb7-region1-reentry-verify-") as temporary:
        expected, files, campaign = _derive(
            baseline, proof_elf, prefix, Path(temporary), anchors=anchors,
            proof_identity=proof_identity, extractor=extractor)
    require(saved == expected,
            "saved campaign differs from independent recomputation")
    for name, data in files.items():
        require(_planner.read_regular(campaign_dir / name) == data,
                f"campaign payload {name} differs from recomputation")
    return campaign


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build the private offline campaign")
    verify = subparsers.add_parser("verify", help="rederive and verify a campaign")
    for command in (build, verify):
        command.add_argument("--baseline-a", required=True, type=Path)
        command.add_argument("--baseline-b", required=True, type=Path)
        command.add_argument("--proof-core1-elf", required=True, type=Path)
        command.add_argument("--campaign", required=True, type=Path)
        command.add_argument("--cross-prefix", default="arm-none-eabi-")
    args = parser.parse_args()
    try:
        if args.command == "build":
            descriptor = build_campaign(
                args.baseline_a, args.baseline_b, args.proof_core1_elf,
                args.campaign, args.cross_prefix)
            result = {
                "campaign_id": descriptor["campaign_id"],
                "baseline_sha256": descriptor["baseline_sha256"],
                "proof_full_sha256": descriptor["proof_full_sha256"],
                "install_operation_count": descriptor["install_operation_count"],
                "restore_operation_count": descriptor["restore_operation_count"],
                "preserved_boot_region_operation_count": 0,
                "region0_operation_count": 0,
                "offline_only": True,
                "flash_approved": False,
            }
        else:
            campaign = load_campaign(
                args.campaign, args.baseline_a, args.baseline_b,
                args.proof_core1_elf, args.cross_prefix)
            result = {
                "campaign_id": campaign.descriptor["campaign_id"],
                "baseline_sha256": campaign.descriptor["baseline_sha256"],
                "proof_full_sha256": campaign.descriptor["proof_full_sha256"],
                "operation_count": len(campaign.operations),
                "verified": True,
                "device_accessed": False,
                "files_written": False,
            }
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, PlanError, ValueError) as error:
        print(f"region-1 reentry campaign error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
