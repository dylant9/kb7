#!/usr/bin/env python3
"""Build and verify the fixed V1.22 loader-reentry proof campaign.

This tool is offline-only.  It turns the default-off ``recovery-proof`` Core-0
ELF and two exact owner baseline captures into a private campaign directory.
The campaign replaces the Core-0 sector envelope and uses one temporary,
fixed-sector Core-1 checksum poison as an independent boot barrier.  Core 1 is
restored byte-exact before either Core-0 final commit.  Every
boot/loader/manifest byte remains exact, and the second fixed operation
sequence restores the exact stock Core-0 envelope.

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
import shutil
import sys
import tempfile
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
    "kb7_updater_plan_for_loader_reentry_campaign",
    TOOL_DIRECTORY / "kb7-updater-plan.py")

PlanError = _planner.PlanError

FORMAT = "KB7 V1.22 fixed loader-reentry proof campaign v1"
SIMULATION_FORMAT = "KB7 loader-reentry install/restore simulation v1"
CAMPAIGN_SCHEMA = 1
EXPECTED_BASELINE_SHA256 = (
    "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f")
EXPECTED_PROOF_RAW = {
    "entry": "0x00000175",
    "raw_length": 1224,
    "raw_sha256": (
        "b4ac207328a5f738ce0ddd4e0ea2fc82f9afa5bfe5b8f613de42106a3a3886e1"),
}
PROOF_PAIR_DOMAIN = b"KB7 fixed loader-reentry proof Core0 v1\0"
PROOF_IMAGE_NAME = "proof-core0-sector-image.bin"
CAMPAIGN_NAME = "campaign.json"
SIMULATION_NAME = "simulation.json"


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


def _proof_pair_id(raw: bytes, baseline: bytes) -> bytes:
    core1 = baseline[
        _planner.CORE1_START:_planner.CORE1_START + _planner.CORE1_LENGTH]
    value = hashlib.sha256(PROOF_PAIR_DOMAIN + raw + core1).digest()[:16]
    require(value not in (bytes(16), b"\xff" * 16),
            "derived proof identifier is reserved")
    return value


def _verify_proof_symbols(elf: Path, prefix: str) -> None:
    nm = shutil.which(f"{prefix}nm")
    require(nm is not None, f"missing ARM nm for prefix {prefix!r}")
    symbols = _planner.run([nm, "-g", str(elf)])
    for required in (
            "kb7_loader_trampoline_relocate_and_enter",
            "kb7_loader_trampoline_blob_start",
            "kb7_loader_trampoline_start"):
        require(required in symbols, f"proof ELF is missing {required}")
    for forbidden in (
            "core0_main", "kb7_usb_init", "kb7_flash_program_block",
            "kb7_flash_erase_sector", "kb7_memcpy"):
        require(forbidden not in symbols,
                f"proof ELF unexpectedly retains {forbidden}")


def _restore_gate_offset(stock_core0: bytes) -> int:
    require(len(stock_core0) == _planner.CORE0_LENGTH,
            "stock Core-0 target length is invalid")
    # Keep the gate in the first sector.  That sector is rebuilt first while
    # the one-bit poison remains elsewhere, so a checksum-invalid barrier is
    # established before any later sector can remove the poison.
    for offset in range(0, _planner.SECTOR_BYTES, 4):
        word = stock_core0[offset:offset + 4]
        if word != b"\xff" * 4:
            chunk_end = min(0x10000, len(stock_core0))
            if _planner.crc_word_rank(stock_core0[:chunk_end], offset) == 32:
                return offset
    raise PlanError("stock Core 0 has no full-rank restore gate in its first sector")


def _staged_with_gate(target: bytes, gate_offset: int) -> bytes:
    require(gate_offset % 4 == 0 and 0 <= gate_offset <= len(target) - 4,
            "gate word is outside its target")
    staged = bytearray(target)
    staged[gate_offset:gate_offset + 4] = b"\xff" * 4
    require(staged != target, "gate word would be an erased no-op")
    require(_planner.fwin_checksum(staged) != _planner.CORE0.manifest_checksum,
            "staged Core 0 is unexpectedly loader-valid")
    return bytes(staged)


def _append_stage_core0(operations: list[object], current: bytearray,
                        staged: bytes, *, phase: str, payload_source: str,
                        gate_offset: int) -> None:
    spec = _planner.CORE0
    envelope = staged + b"\xff" * (spec.envelope_length - spec.length)
    gate_sector_relative = gate_offset & ~(_planner.SECTOR_BYTES - 1)
    sector_offsets = [gate_sector_relative] + [
        offset for offset in range(0, spec.envelope_length, _planner.SECTOR_BYTES)
        if offset != gate_sector_relative
    ]
    for relative in sector_offsets:
        sector = spec.start + relative
        desired = envelope[relative:relative + _planner.SECTOR_BYTES]
        before = bytes(current[sector:sector + _planner.SECTOR_BYTES])
        if before != desired and not all(
                (old & new) == new for old, new in zip(before, desired)):
            operation = _planner.Operation(
                phase, "erase", sector, None, None, None)
            operations.append(operation)
            _planner.apply_operation(current, operation)
        for block in range(sector, sector + _planner.SECTOR_BYTES,
                           _planner.BLOCK_BYTES):
            payload_offset = block - spec.start
            payload = envelope[
                payload_offset:payload_offset + _planner.BLOCK_BYTES]
            before_block = bytes(current[block:block + _planner.BLOCK_BYTES])
            if before_block == payload:
                continue
            require(payload != b"\xff" * _planner.BLOCK_BYTES,
                    "campaign attempted an all-erased program")
            require(all((old & new) == new for old, new in
                        zip(before_block, payload)),
                    "campaign attempted a 0-to-1 program")
            operation = _planner.Operation(
                phase, "program", block, payload, payload_source,
                payload_offset)
            operations.append(operation)
            _planner.apply_operation(current, operation)
    require(bytes(current[spec.start:spec.envelope_end]) == envelope,
            f"{phase} did not converge to the exact staged envelope")


def _append_poison(operations: list[object], current: bytearray,
                   spec: object, *, phase: str) -> dict[str, object]:
    block, byte_offset, payload = _planner.choose_poison(
        bytes(current), spec)
    operation = _planner.Operation(
        phase, "program", block, payload, "authored-poison", 0)
    operations.append(operation)
    _planner.apply_operation(current, operation)
    require(_planner.core_checksums(current)[spec.role] !=
            spec.manifest_checksum,
            f"{phase} did not invalidate {spec.name}")
    return {
        "block_offset": f"0x{block:08x}",
        "byte_offset": f"0x{byte_offset:08x}",
        "payload_sha256": sha256(payload),
        "requested_transition": "0xff->0xfe",
    }


def _restore_core1_barrier(operations: list[object], current: bytearray,
                           baseline: bytes, poison: dict[str, object], *,
                           phase_prefix: str) -> dict[str, object]:
    spec = _planner.CORE1
    poison_absolute = int(str(poison["byte_offset"]), 0)
    sector_absolute = poison_absolute & ~(_planner.SECTOR_BYTES - 1)
    sector_relative = sector_absolute - spec.start
    stock = baseline[spec.start:spec.start + spec.length]
    stock_sector = stock[
        sector_relative:sector_relative + _planner.SECTOR_BYTES]

    erase = _planner.Operation(
        f"{phase_prefix}_stage_core1_barrier", "erase", sector_absolute,
        None, None, None)
    operations.append(erase)
    _planner.apply_operation(current, erase)
    for block_relative in range(0, _planner.SECTOR_BYTES, _planner.BLOCK_BYTES):
        payload = bytes(stock_sector[
            block_relative:block_relative + _planner.BLOCK_BYTES])
        if payload == b"\xff" * _planner.BLOCK_BYTES:
            continue
        block_absolute = sector_absolute + block_relative
        program = _planner.Operation(
            f"{phase_prefix}_stage_core1_barrier", "program", block_absolute,
            payload, "baseline-core1", sector_relative + block_relative)
        operations.append(program)
        _planner.apply_operation(current, program)
    require(bytes(current[spec.start:spec.start + spec.length]) == stock,
            "Core-1 barrier restoration is not exact stock")
    return {
        "sector_offset": f"0x{sector_relative:08x}",
        "absolute_sector_offset": f"0x{sector_absolute:08x}",
        "restored_sector_sha256": sha256(stock_sector),
        "safety_barrier": "Core0 remains checksum-invalid throughout",
    }


def _append_commit(operations: list[object], current: bytearray,
                   target: bytes, *, phase: str, payload_source: str,
                   gate_offset: int) -> None:
    block_relative = gate_offset & ~(_planner.BLOCK_BYTES - 1)
    payload = target[
        block_relative:block_relative + _planner.BLOCK_BYTES]
    operation = _planner.Operation(
        phase, "program", _planner.CORE0.start + block_relative, payload,
        payload_source, block_relative)
    operations.append(operation)
    _planner.apply_operation(current, operation)
    require(bytes(current[
        _planner.CORE0.start:_planner.CORE0.start + _planner.CORE0.length]) == target,
        f"{phase} did not produce its exact target")


def _operation_descriptor(index: int, operation: object,
                          preimage: bytes, postimage: bytes) -> dict[str, object]:
    if operation.action == "program":
        require(operation.payload is not None,
                "program operation has no payload")
        cdb = _planner.cdb_program(operation.offset)
        payload_hash: str | None = sha256(operation.payload)
    else:
        require(operation.action == "erase" and operation.payload is None,
                "operation action/payload is invalid")
        cdb = _planner.cdb_erase(operation.offset)
        payload_hash = None
    return {
        "index": index,
        "phase": operation.phase,
        "action": operation.action,
        "offset": f"0x{operation.offset:08x}",
        "length": operation.length,
        "cdb_hex": cdb.hex(),
        "payload_sha256": payload_hash,
        "payload_source": operation.payload_source,
        "payload_offset": operation.payload_offset,
        "pre_full_sha256": sha256(preimage),
        "post_full_sha256": sha256(postimage),
        "pre_mutable_sha256": _planner.mutable_state_sha256(preimage),
        "post_mutable_sha256": _planner.mutable_state_sha256(postimage),
    }


def _simulate(baseline: bytes, proof_image: bytes,
              operations: tuple[object, ...], install_count: int,
              restore_gate_offset: int,
              core1_barrier_sector: int) -> tuple[list[dict[str, object]],
                                                  dict[str, object]]:
    current = bytearray(baseline)
    immutable = baseline[:_planner.CORE0_START] + baseline[
        _planner.CORE1_ENVELOPE_END:]
    traces: list[dict[str, object]] = []
    symbolic_prefix_states = 0
    early_valid = 0
    opposite_barrier_prefixes = 0
    poison_prefix_states = 0
    sparse_gate_subset_proofs = 0
    for index, operation in enumerate(operations):
        pre = bytes(current)
        pre_unit = pre[operation.offset:operation.offset + operation.length]
        _planner.apply_operation(current, operation)
        post = bytes(current)
        post_unit = post[operation.offset:operation.offset + operation.length]
        require(pre_unit != post_unit, f"operation {index} is a no-op")
        require(_planner.transition_reachable(
            pre_unit, post_unit, post_unit, operation.action),
            f"operation {index} violates modeled NOR direction")
        require(post[:_planner.CORE0_START] + post[_planner.CORE1_ENVELOPE_END:] ==
                immutable, f"operation {index} changes an immutable range")
        if operation.offset >= _planner.CORE1_START:
            require(core1_barrier_sector <= operation.offset and
                    operation.offset + operation.length <=
                    core1_barrier_sector + _planner.SECTOR_BYTES,
                    f"operation {index} escapes the one Core-1 barrier sector")
        checksums = _planner.core_checksums(post)
        valid = (checksums[0] == _planner.CORE0.manifest_checksum,
                 checksums[1] == _planner.CORE1.manifest_checksum)
        at_install_target = index + 1 == install_count and post == proof_image
        at_restore_target = index + 1 == len(operations) and post == baseline
        if all(valid) and not (at_install_target or at_restore_target):
            early_valid += 1
        require(not all(valid) or at_install_target or at_restore_target,
                f"operation {index} creates an early valid application pair")
        if "stage_core0" in operation.phase:
            require(not valid[1],
                    f"operation {index} lacks the invalid Core-1 barrier")
            opposite_barrier_prefixes += operation.length - 1
        if "core1_barrier" in operation.phase:
            require(not valid[0],
                    f"operation {index} lacks the invalid Core-0 barrier")
            opposite_barrier_prefixes += operation.length - 1
        if "poison_" in operation.phase:
            changed = [position for position, (left, right) in enumerate(
                       zip(pre_unit, post_unit)) if left != right]
            require(len(changed) == 1 and
                    (pre_unit[changed[0]] ^ post_unit[changed[0]]).bit_count() == 1,
                    f"operation {index} poison is not exactly one bit")
            # Every byte-prefix before the changed byte is the exact stable
            # preimage; every later prefix is the exact invalid postimage.
            require(_planner.prefix_outcome(
                pre_unit, post_unit, operation.action, changed[0]) == pre_unit and
                _planner.prefix_outcome(
                    pre_unit, post_unit, operation.action,
                    changed[0] + 1) == post_unit,
                    f"operation {index} poison-prefix model is not binary")
            poison_prefix_states += operation.length - 1
        if operation.phase.endswith("commit_core0"):
            gate = (_planner.CORE0.gate_offset if
                    operation.phase.startswith("install_") else
                    restore_gate_offset)
            relative = operation.offset - _planner.CORE0.start
            changed = [position for position, (left, right) in enumerate(
                       zip(pre_unit, post_unit)) if left != right]
            gate_in_unit = gate - relative
            require(changed and min(changed) >= gate_in_unit and
                    max(changed) < gate_in_unit + 4,
                    f"operation {index} Core-0 commit changes more than its gate word")
            core0_post = post[
                _planner.CORE0_START:
                _planner.CORE0_START + _planner.CORE0_LENGTH]
            chunk_start = (gate // 0x10000) * 0x10000
            chunk_end = min(chunk_start + 0x10000, len(core0_post))
            require(_planner.crc_word_rank(
                core0_post[chunk_start:chunk_end], gate - chunk_start) == 32,
                    f"operation {index} Core-0 gate is not bijective")
            require(_planner.fwin_checksum(core0_post) ==
                    _planner.CORE0.manifest_checksum,
                    f"operation {index} Core-0 gate does not reach the exact checksum")
            sparse_gate_subset_proofs += 1
        traces.append(_operation_descriptor(index, operation, pre, post))
        symbolic_prefix_states += operation.length - 1

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
        "modeled_byte_prefix_states_checked": symbolic_prefix_states,
        "opposite_barrier_prefix_states_checked": opposite_barrier_prefixes,
        "single_bit_poison_prefix_states_checked": poison_prefix_states,
        "sparse_gate_subset_proofs": sparse_gate_subset_proofs,
        "early_loader_valid_non_target_states": early_valid,
        "core1_operation_count": sum(
            operation.offset >= _planner.CORE1_START for operation in operations),
        "core1_barrier_sector": f"0x{core1_barrier_sector:08x}",
        "preserved_boot_region_operation_count": 0,
        "restore_gate_offset": f"0x{restore_gate_offset:08x}",
        "invariants_passed": [
            "Core-0 plus one fixed Core-1 barrier sector contain all operations",
            "header, loader, manifest, and all flash after Core 1 remain exact",
            "the inactive core remains checksum-invalid during every staging unit",
            "Core 1 is restored to exact stock before each Core-0 final commit",
            "each poison has only exact-pre/exact-post prefix states",
            "each final one-word gate is a rank-32 unique checksum solution",
            "the install target is the exact checksum-valid proof image",
            "the restore target is the exact full-chip baseline",
            "only exact command boundaries authorize continuation",
        ],
        "proof_boundary": (
            "Command boundaries, exact payloads, and monotone byte-prefix models are "
            "covered. Misaddressing, disturb, arbitrary physical torn-NOR behavior, "
            "and loader-model errors still require external SPI recovery."),
    }


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
        raw, elf_info = _planner.inspect_and_extract(
            proof_elf, _planner.CORE0, prefix, work / "proof-core0.raw")
    else:
        raw, elf_info = extractor(
            proof_elf, _planner.CORE0, prefix, work / "proof-core0.raw")
    require({key: elf_info.get(key) for key in proof_identity} == proof_identity,
            "proof Core-0 raw identity is not the reviewed recovery-proof image")

    pair_id = _proof_pair_id(raw, baseline)
    target_core0, staged_install, target_metadata = \
        _planner.build_target_region(raw, _planner.CORE0, pair_id)
    proof_image_mutable = bytearray(baseline)
    proof_image_mutable[
        _planner.CORE0_START:_planner.CORE0_START + _planner.CORE0_LENGTH] = target_core0
    proof_image_mutable[
        _planner.CORE0_START + _planner.CORE0_LENGTH:
        _planner.CORE0_ENVELOPE_END] = b"\xff" * (
            _planner.CORE0_ENVELOPE_END - _planner.CORE0_START -
            _planner.CORE0_LENGTH)
    proof_image = bytes(proof_image_mutable)

    current = bytearray(baseline)
    operations: list[object] = []
    install_poison = _append_poison(
        operations, current, _planner.CORE0,
        phase="install_poison_core0")
    install_core1_poison = _append_poison(
        operations, current, _planner.CORE1,
        phase="install_poison_core1")
    _append_stage_core0(
        operations, current, staged_install, phase="install_stage_core0",
        payload_source=PROOF_IMAGE_NAME,
        gate_offset=_planner.CORE0.gate_offset)
    install_core1_barrier = _restore_core1_barrier(
        operations, current, baseline, install_core1_poison,
        phase_prefix="install")
    _append_commit(
        operations, current, target_core0, phase="install_commit_core0",
        payload_source=PROOF_IMAGE_NAME,
        gate_offset=_planner.CORE0.gate_offset)
    require(bytes(current) == proof_image,
            "install sequence does not produce the exact proof image")
    install_count = len(operations)

    restore_poison = _append_poison(
        operations, current, _planner.CORE0,
        phase="restore_poison_core0")
    restore_core1_poison = _append_poison(
        operations, current, _planner.CORE1,
        phase="restore_poison_core1")
    stock_core0 = baseline[
        _planner.CORE0_START:_planner.CORE0_START + _planner.CORE0_LENGTH]
    restore_gate = _restore_gate_offset(stock_core0)
    staged_restore = _staged_with_gate(stock_core0, restore_gate)
    _append_stage_core0(
        operations, current, staged_restore, phase="restore_stage_core0",
        payload_source="baseline-core0", gate_offset=restore_gate)
    restore_core1_barrier = _restore_core1_barrier(
        operations, current, baseline, restore_core1_poison,
        phase_prefix="restore")
    _append_commit(
        operations, current, stock_core0, phase="restore_commit_core0",
        payload_source="baseline-core0", gate_offset=restore_gate)
    require(bytes(current) == baseline,
            "restore sequence does not produce the exact baseline")

    operation_tuple = tuple(operations)
    core1_barrier_sector = int(
        str(install_core1_barrier["absolute_sector_offset"]), 0)
    require(restore_core1_barrier["absolute_sector_offset"] ==
            install_core1_barrier["absolute_sector_offset"],
            "install and restore did not use one fixed Core-1 barrier sector")
    traces, simulation = _simulate(
        baseline, proof_image, operation_tuple, install_count, restore_gate,
        core1_barrier_sector)
    simulation_raw = (json.dumps(
        simulation, indent=2, sort_keys=True) + "\n").encode("utf-8")
    proof_envelope = target_core0 + b"\xff" * (
        _planner.CORE0.envelope_length - _planner.CORE0.length)
    files = {
        PROOF_IMAGE_NAME: proof_envelope,
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
        "source_policy": "exact V1.22 stock -> fixed proof Core0 -> exact stock",
        "baseline_sha256": sha256(baseline),
        "proof_full_sha256": sha256(proof_image),
        "source_anchors": dict(anchors),
        "preserved_regions": [
            *_planner.preserved_boot_regions(baseline),
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
                "start": f"0x{_planner.CORE0_START:08x}",
                "end_exclusive": f"0x{_planner.CORE0_ENVELOPE_END:08x}",
            },
            {
                "start": install_core1_barrier["absolute_sector_offset"],
                "end_exclusive": f"0x{core1_barrier_sector + _planner.SECTOR_BYTES:08x}",
            },
        ],
        "proof_raw": {
            "entry": elf_info["entry"],
            "raw_length": elf_info["raw_length"],
            "raw_sha256": elf_info["raw_sha256"],
        },
        "proof_pair_id": pair_id.hex(),
        "proof_core0": {
            "target_sha256": sha256(target_core0),
            "full_envelope_sha256": sha256(proof_envelope),
            **target_metadata,
        },
        "install_poison": install_poison,
        "install_core1_poison": install_core1_poison,
        "install_core1_barrier": install_core1_barrier,
        "restore_poison": restore_poison,
        "restore_core1_poison": restore_core1_poison,
        "restore_core1_barrier": restore_core1_barrier,
        "restore_gate": {
            "offset": f"0x{restore_gate:08x}",
            "absolute_offset": f"0x{_planner.CORE0_START + restore_gate:08x}",
            "target_word": stock_core0[restore_gate:restore_gate + 4].hex(),
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
        },
        "limitations": [
            "This descriptor does not authorize live hardware execution.",
            "The custom proof path remains hardware-unrun.",
            "Physical torn-NOR, misaddressing, and disturb remain SPI-recovery cases.",
            "A new USB enumeration supports but cannot prove the cause of loader entry.",
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
            prefix="kb7-loader-reentry-campaign-", dir=output.parent) as temporary:
        work = Path(temporary)
        descriptor, files, _campaign = _derive(
            baseline, proof_elf, prefix, work, anchors=anchors,
            proof_identity=proof_identity, extractor=extractor)
        for name, data in files.items():
            (work / name).write_bytes(data)
        (work / CAMPAIGN_NAME).write_text(
            json.dumps(descriptor, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        raw = work / "proof-core0.raw"
        if raw.exists():
            raw.unlink()
        os.replace(work, output)
    return descriptor


def _load_json(path: Path) -> dict[str, object]:
    raw = _planner.read_regular(path)
    try:
        value = json.loads(
            raw, object_pairs_hook=_planner.duplicate_rejecting_object,
            parse_constant=_planner.reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PlanError(f"{path.name} is not strict JSON") from error
    require(isinstance(value, dict), f"{path.name} is not an object")
    return value


def load_campaign(campaign_dir: Path, baseline_a: Path, baseline_b: Path,
                  proof_elf: Path, prefix: str,
                  *, anchors: dict[str, str] | None = None,
                  proof_identity: dict[str, object] | None = None,
                  extractor: Callable | None = None) -> Campaign:
    require(campaign_dir.is_dir() and not campaign_dir.is_symlink(),
            "campaign path is not a regular directory")
    require({path.name for path in campaign_dir.iterdir()} == {
        CAMPAIGN_NAME, PROOF_IMAGE_NAME, SIMULATION_NAME},
        "campaign directory has missing or extra files")
    saved = _load_json(campaign_dir / CAMPAIGN_NAME)
    campaign_id = saved.get("campaign_id")
    require(isinstance(campaign_id, str) and len(campaign_id) == 64,
            "campaign identifier is malformed")
    without_id = dict(saved)
    without_id.pop("campaign_id", None)
    require(campaign_id == _planner.canonical_sha256(without_id),
            "campaign identifier does not verify")
    baseline = _planner.load_baselines(baseline_a, baseline_b)
    with tempfile.TemporaryDirectory(prefix="kb7-loader-reentry-verify-") as temporary:
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
        command.add_argument("--proof-core0-elf", required=True, type=Path)
        command.add_argument("--campaign", required=True, type=Path)
        command.add_argument("--cross-prefix", default="arm-none-eabi-")
    args = parser.parse_args()
    try:
        if args.command == "build":
            descriptor = build_campaign(
                args.baseline_a, args.baseline_b, args.proof_core0_elf,
                args.campaign, args.cross_prefix)
            result = {
                "campaign_id": descriptor["campaign_id"],
                "baseline_sha256": descriptor["baseline_sha256"],
                "proof_full_sha256": descriptor["proof_full_sha256"],
                "install_operation_count": descriptor["install_operation_count"],
                "restore_operation_count": descriptor["restore_operation_count"],
                "preserved_boot_region_operation_count": 0,
                "core1_operation_count": sum(
                    int(str(operation["offset"]), 0) >= _planner.CORE1_START
                    for operation in descriptor["operations"]),
                "offline_only": True,
                "flash_approved": False,
            }
        else:
            campaign = load_campaign(
                args.campaign, args.baseline_a, args.baseline_b,
                args.proof_core0_elf, args.cross_prefix)
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
        print(f"loader-reentry campaign error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
