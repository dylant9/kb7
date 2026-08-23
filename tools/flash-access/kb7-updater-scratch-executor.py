#!/usr/bin/env python3
"""Fixed scratch-only execution harness for the KB7 USB updater model.

This is a destructive laboratory harness, not a firmware updater.  It replays
only the already reviewed 18-program/four-erase scratch command set.  The
caller cannot select an operation, address, CDB, payload, size, device, retry,
or recovery policy.  Each ``step`` derives exactly one next operation from a
separate durable scratch journal and is dry-run unless ``--commit`` is given.
At the fixed ``program-09`` boundary, ``step`` deliberately stops after the
reviewed program command and WIP-ready poll, without post-read or journal
advance; only a fresh-process, read-only ``reconcile`` may classify the result.

The general paired-firmware executor remains read-only and mutation-locked.
This tool never accepts a firmware bundle and cannot construct an operation in
the header, loader, manifest, firmware, asset, settings, or tail regions.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import MappingProxyType
from typing import Callable


sys.dont_write_bytecode = True

TOOL_DIRECTORY = Path(__file__).resolve().parent


def _load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load required module: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


_restart = _load_module(
    "kb7_scratch_restart_for_updater_executor",
    TOOL_DIRECTORY / "kb7-isp-scratch-restart.py")
_writer = _restart._writer

SafetyError = _writer.SafetyError

FLASH_SIZE = _restart.FLASH_SIZE
BLOCK = _restart.BLOCK
SECTOR = _restart.SECTOR
ENVELOPE_LO = _restart.ENVELOPE_LO
ENVELOPE_HI = _restart.ENVELOPE_HI
EXPECTED_LOADER_SHA256 = _restart.EXPECTED_LOADER_SHA256

JOURNAL_SCHEMA = "kb7-usb-updater-scratch-journal-v2"
PLAN_SCHEMA = "kb7-usb-updater-fixed-scratch-plan-v2"
EXPECTED_SOURCE_SCRATCH_PLAN_SHA256 = (
    "d784f036e06a972d9688d15c76a41cbd7e90ca806d5ced1aeab5aae16745085b")
EXPECTED_PLAN_SHA256 = (
    "f0a8acfcdc7ab5fb7a7dc2753ed8bdca0e381a9433f64fe311348442a8bbdb32")

CHECKPOINT_OPERATION_INDEX = 9
CHECKPOINT_OPERATION_ID = "program-09"
CHECKPOINT_OPERATION_OFFSET = 0x000C6000
CHECKPOINT_OPERATION_CDB_HEX = "f60600600c6000000100000000000000"
CHECKPOINT_PAYLOAD_SHA256 = (
    "ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380")
CHECKPOINT_POLICY = "after_command_and_wip_poll_before_postread"
PROCESS_NONCE = os.urandom(32).hex()


class ScratchExecutorError(SafetyError):
    """A fixed-plan, state, transport, or verification failure."""


class ReconciliationRequired(ScratchExecutorError):
    """A durable intent exists and a new read-only session is required."""


class RecoveryRequired(ScratchExecutorError):
    """The observed image is outside the two exact authorized outcomes."""


@dataclass(frozen=True)
class ScratchOperation:
    identifier: str
    action: str
    offset: int
    payload: bytes | None
    cdb: bytes

    @property
    def length(self) -> int:
        return BLOCK if self.action == "program" else SECTOR


def _fixed_operations() -> tuple[ScratchOperation, ...]:
    writes = (_restart.PREPARE_A_WRITES + (_restart.PROGRAM_CUT_WRITE,) +
              _restart.PREPARE_B_WRITES)
    operations = [
        ScratchOperation(
            identifier=f"program-{index:02d}",
            action="program",
            offset=offset,
            payload=payload,
            cdb=_writer.cdb_program(offset, BLOCK),
        )
        for index, (offset, payload) in enumerate(writes)
    ]
    for identifier, offset in (
            ("erase-work-a", _restart.WORK_A_SECTOR),
            ("erase-work-b", _restart.WORK_B_SECTOR),
            ("erase-lower-guard", _restart.LOWER_GUARD_SECTOR),
            ("erase-upper-guard", _restart.UPPER_GUARD_SECTOR)):
        operations.append(ScratchOperation(
            identifier=identifier,
            action="erase",
            offset=offset,
            payload=None,
            cdb=_writer.cdb_erase(offset),
        ))
    return tuple(operations)


OPERATIONS = _fixed_operations()


def _source_sha256(path: str | os.PathLike[str]) -> str:
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def implementation_hashes() -> dict[str, str]:
    return {
        "scratch_executor_source_sha256": _source_sha256(__file__),
        "scratch_plan_source_sha256": _source_sha256(_restart.__file__),
        "writer_source_sha256": _source_sha256(_writer.__file__),
        "verifier_source_sha256": _source_sha256(_writer._verify.__file__),
    }


# Bind the files that supplied this process's executing code once at import.
# A later on-disk edit cannot silently change the journal written by this
# already-running process; a new process sees the changed hash and refuses the
# existing journal.
IMPLEMENTATION_HASHES = MappingProxyType(implementation_hashes())


def _operation_descriptor(operation: ScratchOperation) -> dict[str, object]:
    return {
        "identifier": operation.identifier,
        "action": operation.action,
        "offset": operation.offset,
        "length": operation.length,
        "cdb_hex": operation.cdb.hex(),
        "payload_sha256": (
            None if operation.payload is None
            else _writer.sha256_bytes(operation.payload)),
    }


def plan_descriptor() -> dict[str, object]:
    return {
        "schema": PLAN_SCHEMA,
        "flash_size": FLASH_SIZE,
        "block_size": BLOCK,
        "sector_size": SECTOR,
        "envelope": [ENVELOPE_LO, ENVELOPE_HI],
        "address_mode_cdb_hex": _writer.cdb_simple(
            _writer.SUB_EX4B).hex(),
        "source_scratch_plan_sha256": _restart.PLAN_SHA256,
        "required_active_intent_checkpoint": {
            "operation_index": CHECKPOINT_OPERATION_INDEX,
            "operation_identifier": CHECKPOINT_OPERATION_ID,
            "operation_offset": CHECKPOINT_OPERATION_OFFSET,
            "operation_cdb_hex": CHECKPOINT_OPERATION_CDB_HEX,
            "payload_sha256": CHECKPOINT_PAYLOAD_SHA256,
            "policy": CHECKPOINT_POLICY,
            "fresh_process_reconciliation_required": True,
            "automatic_retry": False,
            "single_attempt": True,
            "exact_preimage_policy": "stop_campaign_checkpoint_consumed",
        },
        "operations": [
            _operation_descriptor(operation) for operation in OPERATIONS],
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("ascii")


def _plan_sha256() -> str:
    return hashlib.sha256(_canonical_bytes(plan_descriptor())).hexdigest()


PLAN_SHA256 = EXPECTED_PLAN_SHA256


@dataclass(frozen=True)
class ScratchTransaction:
    baseline: bytes
    manifest: object
    operations: tuple[ScratchOperation, ...]
    boundary_sha256: tuple[str, ...]
    baseline_paths: tuple[Path, Path]

    @property
    def baseline_sha256(self) -> str:
        return _writer.sha256_bytes(self.baseline)


def _validate_operation(operation: ScratchOperation, manifest: object) -> None:
    if type(operation) is not ScratchOperation:
        raise ScratchExecutorError("operation is not from the fixed scratch domain")
    if operation.action not in {"program", "erase"}:
        raise ScratchExecutorError("fixed scratch operation has an unknown action")
    end = operation.offset + operation.length
    if not (ENVELOPE_LO <= operation.offset < end <= ENVELOPE_HI):
        raise ScratchExecutorError("fixed operation escapes the scratch envelope")
    if not (manifest.scratch_lo <= operation.offset and end <= manifest.scratch_hi):
        raise ScratchExecutorError("fixed operation escapes manifest-derived scratch")
    for region in manifest.regions:
        if operation.offset < region.end and region.offset < end:
            raise ScratchExecutorError("fixed operation overlaps a declared region")
    if operation.action == "program":
        if (operation.offset % BLOCK or operation.length != BLOCK or
                operation.payload is None or len(operation.payload) != BLOCK):
            raise ScratchExecutorError("fixed program operation is malformed")
        canonical = _writer.cdb_program(operation.offset, BLOCK)
    else:
        if (operation.offset % SECTOR or operation.payload is not None or
                operation.length != SECTOR):
            raise ScratchExecutorError("fixed erase operation is malformed")
        canonical = _writer.cdb_erase(operation.offset)
    if not hmac.compare_digest(canonical, operation.cdb):
        raise ScratchExecutorError("fixed operation CDB is not canonical")


def _validate_checkpoint_operation(
        operations: tuple[ScratchOperation, ...]) -> ScratchOperation:
    if not 0 <= CHECKPOINT_OPERATION_INDEX < len(operations):
        raise ScratchExecutorError("active-intent checkpoint index is invalid")
    operation = operations[CHECKPOINT_OPERATION_INDEX]
    if (operation.identifier != CHECKPOINT_OPERATION_ID or
            operation.action != "program" or
            operation.offset != CHECKPOINT_OPERATION_OFFSET or
            operation.length != BLOCK or
            operation.payload is None or
            not hmac.compare_digest(
                operation.cdb.hex(), CHECKPOINT_OPERATION_CDB_HEX) or
            not hmac.compare_digest(
                _writer.sha256_bytes(operation.payload),
                CHECKPOINT_PAYLOAD_SHA256)):
        raise ScratchExecutorError(
            "active-intent checkpoint operation is not the reviewed command")
    return operation


def _apply_operation(image: bytearray, operation: ScratchOperation) -> None:
    start = operation.offset
    end = start + operation.length
    if operation.action == "program":
        before = image[start:end]
        payload = operation.payload
        if payload is None or any((old & new) != new
                                  for old, new in zip(before, payload)):
            raise ScratchExecutorError(
                "fixed program requires an impossible 0-to-1 transition")
        image[start:end] = bytes(old & new for old, new in zip(before, payload))
    elif operation.action == "erase":
        image[start:end] = b"\xff" * SECTOR
    else:
        raise ScratchExecutorError("cannot apply an unknown scratch operation")


def expected_boundary_image(transaction: ScratchTransaction,
                            boundary_index: int) -> bytes:
    if not 0 <= boundary_index <= len(transaction.operations):
        raise ScratchExecutorError("scratch boundary index is outside the plan")
    image = bytearray(transaction.baseline)
    for operation in transaction.operations[:boundary_index]:
        _apply_operation(image, operation)
    return bytes(image)


def load_transaction(baseline_a: Path, baseline_b: Path) -> ScratchTransaction:
    try:
        if baseline_a.resolve() == baseline_b.resolve() or os.path.samefile(
                baseline_a, baseline_b):
            raise ScratchExecutorError("baseline captures must be distinct files")
    except FileNotFoundError:
        pass
    if baseline_a.is_symlink() or baseline_b.is_symlink():
        raise ScratchExecutorError("baseline captures must be regular non-symlink files")
    baseline = _writer.load_baseline(baseline_a)
    second = _writer.load_baseline(baseline_b)
    manifest = _restart.validate_baselines(baseline, second)
    if (not hmac.compare_digest(
            _restart.PLAN_SHA256,
            EXPECTED_SOURCE_SCRATCH_PLAN_SHA256) or
            not hmac.compare_digest(
                _restart._plan_sha256(),
                EXPECTED_SOURCE_SCRATCH_PLAN_SHA256)):
        raise ScratchExecutorError("reviewed scratch-plan source binding changed")
    if not hmac.compare_digest(_plan_sha256(), EXPECTED_PLAN_SHA256):
        raise ScratchExecutorError("fixed executor plan binding changed")

    checked_sectors: set[int] = set()
    for operation in OPERATIONS:
        _validate_operation(operation, manifest)
        sector = operation.offset & ~(SECTOR - 1)
        if sector not in checked_sectors:
            _writer.validate_target(manifest, baseline, sector)
            checked_sectors.add(sector)
    _validate_checkpoint_operation(OPERATIONS)

    current = bytearray(baseline)
    boundary_hashes = [_writer.sha256_bytes(current)]
    for operation in OPERATIONS:
        before = bytes(current)
        _apply_operation(current, operation)
        if current == before:
            raise ScratchExecutorError(
                f"fixed operation {operation.identifier} has no effect")
        boundary_hashes.append(_writer.sha256_bytes(current))
    if bytes(current) != baseline:
        raise ScratchExecutorError("fixed scratch plan does not restore its baseline")
    if len(set(boundary_hashes[:-1])) != len(boundary_hashes) - 1:
        raise ScratchExecutorError("scratch plan has an ambiguous intermediate boundary")
    return ScratchTransaction(
        baseline=baseline,
        manifest=manifest,
        operations=OPERATIONS,
        boundary_sha256=tuple(boundary_hashes),
        baseline_paths=(baseline_a.resolve(strict=True),
                        baseline_b.resolve(strict=True)),
    )


JOURNAL_KEYS = {
    "schema", "status", "plan_sha256", "source_scratch_plan_sha256",
    "baseline_sha256", "manifest_sha256", "loader_window_sha256",
    "device_path", "identify_hex", "descriptor_sha256",
    "loader_fingerprint_sha256", "scratch_executor_source_sha256",
    "scratch_plan_source_sha256", "writer_source_sha256",
    "verifier_source_sha256", "operation_count", "boundary_index",
    "active_operation_id", "active_operation_sha256",
    "pre_image_sha256", "post_image_sha256", "last_observed_sha256",
    "intent_process_nonce",
}


def _identity_fields(raw: dict[str, str], image: bytes) -> dict[str, str]:
    expected = {
        "device_path", "identify_hex", "descriptor_sha256",
        "loader_fingerprint_sha256",
    }
    if set(raw) != expected or any(
            not isinstance(raw[key], str) or not raw[key] for key in expected):
        raise ScratchExecutorError("live loader identity is malformed")
    return {
        **raw,
        "loader_window_sha256": _writer.sha256_bytes(
            image[_restart.LOADER_OFFSET:
                  _restart.LOADER_OFFSET + _restart.LOADER_SIZE]),
        "manifest_sha256": _writer.sha256_bytes(
            image[_writer.MANIFEST_OFFSET:
                  _writer.MANIFEST_OFFSET + _writer.MANIFEST_SIZE]),
    }


def _journal_common(transaction: ScratchTransaction,
                    identity: dict[str, str]) -> dict[str, object]:
    return {
        "schema": JOURNAL_SCHEMA,
        "plan_sha256": PLAN_SHA256,
        "source_scratch_plan_sha256": _restart.PLAN_SHA256,
        "baseline_sha256": transaction.baseline_sha256,
        "manifest_sha256": transaction.manifest.sha256,
        "loader_window_sha256": EXPECTED_LOADER_SHA256,
        "device_path": identity["device_path"],
        "identify_hex": identity["identify_hex"],
        "descriptor_sha256": identity["descriptor_sha256"],
        "loader_fingerprint_sha256": identity["loader_fingerprint_sha256"],
        **IMPLEMENTATION_HASHES,
        "operation_count": len(transaction.operations),
    }


def _operation_sha256(operation: ScratchOperation) -> str:
    return hashlib.sha256(_canonical_bytes(
        _operation_descriptor(operation))).hexdigest()


def boundary_journal(transaction: ScratchTransaction,
                     identity: dict[str, str],
                     boundary_index: int) -> dict[str, object]:
    if not 0 <= boundary_index <= len(transaction.operations):
        raise ScratchExecutorError("cannot journal an invalid scratch boundary")
    return {
        **_journal_common(transaction, identity),
        "status": ("complete" if boundary_index == len(transaction.operations)
                   else "boundary_verified"),
        "boundary_index": boundary_index,
        "active_operation_id": None,
        "active_operation_sha256": None,
        "pre_image_sha256": None,
        "post_image_sha256": None,
        "last_observed_sha256": transaction.boundary_sha256[boundary_index],
        "intent_process_nonce": None,
    }


def intent_journal(transaction: ScratchTransaction,
                   identity: dict[str, str],
                   operation_index: int, *,
                   process_nonce: str | None = None) -> dict[str, object]:
    if not 0 <= operation_index < len(transaction.operations):
        raise ScratchExecutorError("cannot journal an invalid scratch operation")
    operation = transaction.operations[operation_index]
    nonce = PROCESS_NONCE if process_nonce is None else process_nonce
    _validate_hex(nonce, 64, "intent_process_nonce")
    return {
        **_journal_common(transaction, identity),
        "status": "intent",
        "boundary_index": operation_index,
        "active_operation_id": operation.identifier,
        "active_operation_sha256": _operation_sha256(operation),
        "pre_image_sha256": transaction.boundary_sha256[operation_index],
        "post_image_sha256": transaction.boundary_sha256[operation_index + 1],
        "last_observed_sha256": transaction.boundary_sha256[operation_index],
        "intent_process_nonce": nonce,
    }


def _reject_json_constant(value: str):
    raise ScratchExecutorError(f"non-finite JSON number is not permitted: {value}")


def _duplicate_rejecting_object(
        pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ScratchExecutorError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _safe_parent(path: Path) -> Path:
    parent = path.absolute().parent
    if not parent.exists():
        raise ScratchExecutorError(
            "journal parent does not exist; create it explicitly")
    information = parent.lstat()
    if (parent.is_symlink() or not stat.S_ISDIR(information.st_mode) or
            parent.resolve(strict=True) != parent):
        raise ScratchExecutorError("journal parent is not a regular directory")
    return parent


def validate_journal_path(transaction: ScratchTransaction, path: Path) -> None:
    parent = _safe_parent(path)
    absolute = path.absolute()
    checkout = TOOL_DIRECTORY.parent.parent.resolve(strict=True)
    if absolute == checkout or checkout in absolute.parents:
        raise ScratchExecutorError("scratch journal must remain outside the checkout")
    for baseline in transaction.baseline_paths:
        try:
            if absolute.resolve() == baseline or os.path.samefile(absolute, baseline):
                raise ScratchExecutorError("journal must not alias a baseline capture")
        except FileNotFoundError:
            continue
    if parent.resolve(strict=True) != parent:
        raise ScratchExecutorError("journal parent changed during validation")


def journal_lock_path(journal_path: Path) -> Path:
    return journal_path.with_name(journal_path.name + ".lock")


@contextmanager
def scratch_journal_lock(transaction: ScratchTransaction,
                         journal_path: Path):
    """Hold one persistent-inode lock across state read, USB and publication."""
    validate_journal_path(transaction, journal_path)
    lock_path = journal_lock_path(journal_path)
    validate_journal_path(transaction, lock_path)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise ScratchExecutorError("cannot safely open scratch journal lock") from error
    try:
        information = os.fstat(descriptor)
        if (not stat.S_ISREG(information.st_mode) or
                stat.S_IMODE(information.st_mode) != 0o600 or
                information.st_uid != os.geteuid() or
                information.st_nlink != 1 or information.st_size != 0):
            raise ScratchExecutorError(
                "scratch journal lock is not a private empty regular file")
        for baseline in transaction.baseline_paths:
            baseline_information = baseline.stat()
            if (information.st_dev, information.st_ino) == (
                    baseline_information.st_dev, baseline_information.st_ino):
                raise ScratchExecutorError("journal lock aliases a baseline capture")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ScratchExecutorError(
                "another scratch executor process holds this journal lock") from error
        path_information = lock_path.lstat()
        if ((path_information.st_dev, path_information.st_ino) !=
                (information.st_dev, information.st_ino)):
            raise ScratchExecutorError("scratch journal lock path changed while opening")
        yield lock_path
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def write_journal_atomic(path: Path, journal: dict[str, object], *,
                         require_absent: bool = False,
                         fault: Callable[[str], None] | None = None) -> None:
    if path.is_symlink():
        raise ScratchExecutorError("refusing a symbolic-link journal path")
    if require_absent and os.path.lexists(path):
        raise ScratchExecutorError("preflight refuses to replace existing state")
    parent = _safe_parent(path)
    encoded = (json.dumps(
        journal, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".kb7-updater-scratch-journal.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if fault is not None:
            fault("during_journal_publish")
        os.replace(temporary, path)
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def clear_journal(path: Path) -> None:
    parent = _safe_parent(path)
    if path.is_symlink():
        raise ScratchExecutorError("refusing to clear a symbolic-link journal")
    path.unlink()
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def load_journal(path: Path) -> dict[str, object]:
    _safe_parent(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as error:
        raise ScratchExecutorError("scratch journal does not exist") from error
    except OSError as error:
        raise ScratchExecutorError("cannot safely open scratch journal") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 65536:
            raise ScratchExecutorError("scratch journal is not a small regular file")
        raw = os.read(descriptor, 65537)
        after = os.fstat(descriptor)
        fingerprint = lambda info: (
            info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)
        if (len(raw) != before.st_size or len(raw) > 65536 or
                fingerprint(before) != fingerprint(after)):
            raise ScratchExecutorError("scratch journal changed while it was read")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(
            raw, object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ScratchExecutorError("scratch journal is not strict JSON") from error
    if not isinstance(value, dict) or set(value) != JOURNAL_KEYS:
        raise ScratchExecutorError("scratch journal has missing or unknown fields")
    return value


def _validate_hex(value: object, length: int, name: str) -> None:
    if (not isinstance(value, str) or len(value) != length or
            any(character not in "0123456789abcdef" for character in value)):
        raise ScratchExecutorError(f"journal {name} is malformed")


def validate_journal(transaction: ScratchTransaction,
                     journal: dict[str, object],
                     identity: dict[str, str] | None = None) -> None:
    if set(journal) != JOURNAL_KEYS or journal.get("schema") != JOURNAL_SCHEMA:
        raise ScratchExecutorError("journal schema is not the fixed scratch domain")
    expected_common = {
        "plan_sha256": PLAN_SHA256,
        "source_scratch_plan_sha256": _restart.PLAN_SHA256,
        "baseline_sha256": transaction.baseline_sha256,
        "manifest_sha256": transaction.manifest.sha256,
        "loader_window_sha256": EXPECTED_LOADER_SHA256,
        "operation_count": len(transaction.operations),
        **IMPLEMENTATION_HASHES,
    }
    for key, expected in expected_common.items():
        if type(journal.get(key)) is not type(expected) or journal.get(key) != expected:
            raise ScratchExecutorError(f"journal {key} does not match this plan")
    for key in (
            "plan_sha256", "source_scratch_plan_sha256", "baseline_sha256",
            "manifest_sha256", "loader_window_sha256", "descriptor_sha256",
            "loader_fingerprint_sha256", "scratch_executor_source_sha256",
            "scratch_plan_source_sha256", "writer_source_sha256",
            "verifier_source_sha256"):
        _validate_hex(journal.get(key), 64, key)
    _validate_hex(
        journal.get("identify_hex"), len(_writer.LOADER_IDENT.hex()),
        "identify_hex")
    if not isinstance(journal.get("device_path"), str) or not journal["device_path"]:
        raise ScratchExecutorError("journal device path is malformed")
    if identity is not None:
        for key in (
                "device_path", "identify_hex", "descriptor_sha256",
                "loader_fingerprint_sha256", "loader_window_sha256",
                "manifest_sha256"):
            if journal.get(key) != identity.get(key):
                raise ScratchExecutorError(f"live device does not match journal {key}")

    boundary = journal.get("boundary_index")
    if type(boundary) is not int or not 0 <= boundary <= len(transaction.operations):
        raise ScratchExecutorError("journal boundary index is invalid")
    status = journal.get("status")
    if status in {"intent", "checkpoint_no_effect"}:
        if boundary >= len(transaction.operations):
            raise ScratchExecutorError("intent cannot follow the final boundary")
        operation = transaction.operations[boundary]
        if (journal.get("active_operation_id") != operation.identifier or
                journal.get("active_operation_sha256") !=
                _operation_sha256(operation) or
                journal.get("pre_image_sha256") !=
                transaction.boundary_sha256[boundary] or
                journal.get("post_image_sha256") !=
                transaction.boundary_sha256[boundary + 1] or
                journal.get("last_observed_sha256") !=
                transaction.boundary_sha256[boundary]):
            raise ScratchExecutorError("journal intent is not canonical")
        _validate_hex(
            journal.get("intent_process_nonce"), 64,
            "intent_process_nonce")
        if (status == "checkpoint_no_effect" and
                boundary != CHECKPOINT_OPERATION_INDEX):
            raise ScratchExecutorError(
                "consumed checkpoint status is outside the reviewed boundary")
    elif status in {"boundary_verified", "complete"}:
        if any(journal.get(key) is not None for key in (
                "active_operation_id", "active_operation_sha256",
                "pre_image_sha256", "post_image_sha256",
                "intent_process_nonce")):
            raise ScratchExecutorError("boundary journal contains an active intent")
        if journal.get("last_observed_sha256") != transaction.boundary_sha256[boundary]:
            raise ScratchExecutorError("boundary journal image hash is stale")
        if (status == "complete") != (boundary == len(transaction.operations)):
            raise ScratchExecutorError("complete status does not match the final boundary")
    else:
        raise ScratchExecutorError("journal status is invalid")


class FixedScratchReadOnlyBackend:
    """Identity and full-chip reads through the read-only verifier whitelist."""

    def __init__(self, transaction: ScratchTransaction, operation_index: int,
                 *, device_factory=_writer._verify.Device) -> None:
        if not 0 <= operation_index < len(transaction.operations):
            raise ScratchExecutorError("scratch read index is outside the plan")
        self._device = device_factory()
        self._closed = False

    def identity(self) -> dict[str, str]:
        if self._closed:
            raise ScratchExecutorError("identity is unavailable after close")
        return _writer.query_loader_identity(self._device)

    def capture(self, *, progress: bool = True) -> bytes:
        if self._closed:
            raise ScratchExecutorError("readback is unavailable after close")
        return _writer.capture_full_chip(self._device, progress=progress)

    def close(self) -> None:
        if not self._closed:
            self._device.close()
            self._closed = True


class FixedScratchUsbMutationBackend:
    """One-operation strict transport with no caller-supplied flash fields."""

    def __init__(self, transaction: ScratchTransaction, operation_index: int,
                 *, device_factory=_writer.WriteDevice) -> None:
        if not 0 <= operation_index < len(transaction.operations):
            raise ScratchExecutorError("scratch operation index is outside the plan")
        operation = transaction.operations[operation_index]
        _validate_operation(operation, transaction.manifest)
        if operation != OPERATIONS[operation_index]:
            raise ScratchExecutorError("scratch operation is not canonical")
        self._operation = operation
        self._manifest = transaction.manifest
        self._device = device_factory()
        self._phase = "opened"

    def _require_phase(self, expected: str) -> None:
        if self._phase != expected:
            raise ScratchExecutorError(
                f"scratch backend is {self._phase}, expected {expected}")

    def identity(self) -> dict[str, str]:
        if self._phase not in {"opened", "ready"}:
            raise ScratchExecutorError("identity is unavailable during mutation")
        return _writer.query_loader_identity(self._device)

    def capture(self, *, progress: bool = True) -> bytes:
        if self._phase not in {"opened", "ready"}:
            raise ScratchExecutorError("readback is unavailable during mutation")
        return _writer.capture_full_chip(self._device, progress=progress)

    def set_mode(self) -> None:
        self._require_phase("opened")
        try:
            mode = _writer.set_address_mode_for_range(
                self._device, self._operation.offset, self._operation.length)
            if mode != _writer.SUB_EX4B:
                raise ScratchExecutorError("fixed operation did not select F6 18")
            self._phase = "mode_set"
        except BaseException:
            self._phase = "failed"
            raise

    def mutate(self) -> None:
        self._require_phase("mode_set")
        try:
            operation = self._operation
            _validate_operation(operation, self._manifest)
            if operation.action == "program":
                cdb = _writer.cdb_program(operation.offset, BLOCK)
                if operation.payload is None:
                    raise ScratchExecutorError("canonical program payload is missing")
                self._device.program(cdb, operation.payload)
            else:
                self._device.cmd(_writer.cdb_erase(operation.offset))
            self._phase = "mutation_sent"
        except BaseException:
            self._phase = "failed"
            raise

    def poll(self) -> None:
        self._require_phase("mutation_sent")
        try:
            _writer.poll_ready(self._device)
            self._phase = "ready"
        except BaseException:
            self._phase = "failed"
            raise

    def execute(self) -> None:
        self.set_mode()
        self.mutate()
        self.poll()

    def close(self) -> None:
        if self._phase != "closed":
            self._device.close()
            self._phase = "closed"


def _two_stable_reads(backend, *, progress: bool) -> bytes:
    first = backend.capture(progress=progress)
    second = backend.capture(progress=progress)
    _writer.require_exact_image("two full-chip scratch reads", first, second)
    return first


def _require_live_image(transaction: ScratchTransaction, expected: bytes,
                        observed: bytes, label: str) -> dict[str, str]:
    _writer.require_exact_image(label, expected, observed)
    _restart.validate_loader_window(observed)
    manifest = _writer.parse_manifest(observed)
    _restart.validate_v122_layout(manifest)
    if not hmac.compare_digest(manifest.sha256, transaction.manifest.sha256):
        raise RecoveryRequired("live manifest changed during scratch execution")
    return {"observed_sha256": _writer.sha256_bytes(observed)}


def _live_preflight_locked(transaction: ScratchTransaction, journal_path: Path, *,
                           backend_factory=FixedScratchReadOnlyBackend,
                           progress: bool = True) -> dict[str, object]:
    validate_journal_path(transaction, journal_path)
    if os.path.lexists(journal_path):
        raise ScratchExecutorError("preflight refuses to replace an existing journal")
    backend = backend_factory(transaction, 0)
    try:
        raw_identity = backend.identity()
        observed = _two_stable_reads(backend, progress=progress)
        _require_live_image(
            transaction, transaction.baseline, observed,
            "scratch preflight versus baseline")
        identity = _identity_fields(raw_identity, observed)
        journal = boundary_journal(transaction, identity, 0)
        write_journal_atomic(journal_path, journal, require_absent=True)
        return {
            "classification": "exact_stock_or_complete",
            "boundary_index": 0,
            "operation_count": len(transaction.operations),
            "next_operation": transaction.operations[0].identifier,
            "plan_sha256": PLAN_SHA256,
            "baseline_sha256": transaction.baseline_sha256,
            "device_path": identity["device_path"],
            "firmware_region_mutation_enabled": False,
        }
    finally:
        backend.close()


def live_preflight(transaction: ScratchTransaction, journal_path: Path, *,
                   backend_factory=FixedScratchReadOnlyBackend,
                   progress: bool = True) -> dict[str, object]:
    with scratch_journal_lock(transaction, journal_path):
        return _live_preflight_locked(
            transaction, journal_path, backend_factory=backend_factory,
            progress=progress)


def _require_step_state(transaction: ScratchTransaction,
                        journal: dict[str, object]) -> int:
    validate_journal(transaction, journal)
    status = journal["status"]
    if status == "intent":
        raise ScratchExecutorError("unresolved intent requires reconcile")
    if status == "checkpoint_no_effect":
        raise ScratchExecutorError(
            "checkpoint campaign is consumed; USB mutation retry is prohibited")
    if status == "complete":
        raise ScratchExecutorError(
            "scratch plan is complete; run reconcile to clear state")
    if status != "boundary_verified":
        raise ScratchExecutorError("scratch step requires a verified boundary")
    index = journal["boundary_index"]
    if type(index) is not int or not 0 <= index < len(transaction.operations):
        raise ScratchExecutorError("scratch step boundary is invalid")
    if index == CHECKPOINT_OPERATION_INDEX:
        _validate_checkpoint_operation(transaction.operations)
    return index


def _live_step_locked(transaction: ScratchTransaction, journal_path: Path, *,
                      backend_factory=FixedScratchUsbMutationBackend,
                      progress: bool = True,
                      journal_fault: Callable[[str], None] | None = None
                      ) -> dict[str, object]:
    validate_journal_path(transaction, journal_path)
    current = load_journal(journal_path)
    index = _require_step_state(transaction, current)
    operation = transaction.operations[index]
    is_checkpoint = index == CHECKPOINT_OPERATION_INDEX
    preimage = expected_boundary_image(transaction, index)
    postimage = expected_boundary_image(transaction, index + 1)
    backend = backend_factory(transaction, index)
    intent_is_durable = False
    try:
        raw_identity = backend.identity()
        observed = _two_stable_reads(backend, progress=progress)
        _require_live_image(transaction, preimage, observed, "scratch step preimage")
        identity = _identity_fields(raw_identity, observed)
        validate_journal(transaction, current, identity)
        intent = intent_journal(transaction, identity, index)
        write_journal_atomic(journal_path, intent, fault=journal_fault)
        intent_is_durable = True
        backend.execute()
        if is_checkpoint:
            return {
                "classification": "planned_active_intent_checkpoint",
                "command_completed_operation": operation.identifier,
                "boundary_index": index,
                "expected_post_boundary_index": index + 1,
                "next_operation": None,
                "observed_sha256": None,
                "automatic_retry": False,
                "postread_performed": False,
                "reconciliation_required": True,
                "state_cleared": False,
                "firmware_region_mutation_enabled": False,
            }
        observed = _two_stable_reads(backend, progress=progress)
        _require_live_image(transaction, postimage, observed, "scratch step postimage")
        verified = boundary_journal(transaction, identity, index + 1)
        write_journal_atomic(journal_path, verified, fault=journal_fault)
        is_final = index + 1 == len(transaction.operations)
        return {
            "classification": (
                "exact_baseline_restored_pending_finalize" if is_final
                else "exact_scratch_boundary"),
            "completed_operation": operation.identifier,
            "boundary_index": index + 1,
            "next_operation": (
                None if is_final
                else transaction.operations[index + 1].identifier),
            "observed_sha256": _writer.sha256_bytes(observed),
            "automatic_retry": False,
            "state_cleared": False,
            "firmware_region_mutation_enabled": False,
        }
    except BaseException as error:
        if intent_is_durable:
            raise ReconciliationRequired(
                f"scratch operation {operation.identifier} stopped after "
                f"durable intent: {error}") from error
        raise
    finally:
        try:
            backend.close()
        except BaseException as close_error:
            if intent_is_durable:
                raise ReconciliationRequired(
                    f"scratch operation {operation.identifier} ended with an "
                    f"uncertain USB close after durable intent: {close_error}"
                ) from close_error
            raise


def live_step(transaction: ScratchTransaction, journal_path: Path, *,
              backend_factory=FixedScratchUsbMutationBackend,
              progress: bool = True,
              journal_fault: Callable[[str], None] | None = None
              ) -> dict[str, object]:
    with scratch_journal_lock(transaction, journal_path):
        return _live_step_locked(
            transaction, journal_path, backend_factory=backend_factory,
            progress=progress, journal_fault=journal_fault)


def _live_reconcile_locked(transaction: ScratchTransaction, journal_path: Path, *,
                           backend_factory=FixedScratchReadOnlyBackend,
                           progress: bool = True) -> dict[str, object]:
    validate_journal_path(transaction, journal_path)
    current = load_journal(journal_path)
    validate_journal(transaction, current)
    index = current["boundary_index"]
    if (current["status"] == "intent" and
            hmac.compare_digest(
                current["intent_process_nonce"], PROCESS_NONCE)):
        raise ScratchExecutorError(
            "active intent must be reconciled by a fresh process")
    backend_index = min(index, len(transaction.operations) - 1)
    backend = backend_factory(transaction, backend_index)
    try:
        raw_identity = backend.identity()
        observed = _two_stable_reads(backend, progress=progress)
        identity = _identity_fields(raw_identity, observed)
        validate_journal(transaction, current, identity)
        observed_sha = _writer.sha256_bytes(observed)
        if current["status"] == "intent":
            pre_sha = current["pre_image_sha256"]
            post_sha = current["post_image_sha256"]
            if hmac.compare_digest(observed_sha, pre_sha):
                if index == CHECKPOINT_OPERATION_INDEX:
                    _require_live_image(
                        transaction,
                        expected_boundary_image(transaction, index),
                        observed,
                        "consumed checkpoint exact preimage")
                    consumed = dict(current)
                    consumed["status"] = "checkpoint_no_effect"
                    consumed["last_observed_sha256"] = observed_sha
                    write_journal_atomic(journal_path, consumed)
                    return {
                        "classification": (
                            "exact_preimage_checkpoint_consumed_no_effect"),
                        "boundary_index": index,
                        "next_operation": None,
                        "observed_sha256": observed_sha,
                        "automatic_retry": False,
                        "campaign_stopped": True,
                        "state_cleared": False,
                        "firmware_region_mutation_enabled": False,
                    }
                boundary = index
                classification = "exact_preimage_no_observable_effect"
            elif hmac.compare_digest(observed_sha, post_sha):
                boundary = index + 1
                classification = "exact_postimage_completed"
            else:
                raise RecoveryRequired(
                    "stable image is neither the exact intent preimage nor postimage")
        elif current["status"] == "checkpoint_no_effect":
            boundary = index
            if not hmac.compare_digest(
                    observed_sha, transaction.boundary_sha256[boundary]):
                raise RecoveryRequired(
                    "consumed checkpoint image changed after classification")
            classification = "exact_preimage_checkpoint_consumed_no_effect"
        else:
            boundary = index
            if not hmac.compare_digest(
                    observed_sha, transaction.boundary_sha256[boundary]):
                raise RecoveryRequired("stable image does not match its journal boundary")
            classification = (
                "exact_stock_or_complete" if boundary in
                {0, len(transaction.operations)}
                else "exact_boundary_already_verified")
        expected = expected_boundary_image(transaction, boundary)
        _require_live_image(transaction, expected, observed, "scratch reconciliation")
        if current["status"] == "checkpoint_no_effect":
            verified = dict(current)
            verified.update(identity)
            verified["last_observed_sha256"] = observed_sha
            write_journal_atomic(journal_path, verified)
        else:
            verified = boundary_journal(transaction, identity, boundary)
            write_journal_atomic(journal_path, verified)
            if boundary == len(transaction.operations):
                clear_journal(journal_path)
        return {
            "classification": classification,
            "boundary_index": boundary,
            "next_operation": (
                None if (boundary == len(transaction.operations) or
                         current["status"] == "checkpoint_no_effect")
                else transaction.operations[boundary].identifier),
            "observed_sha256": observed_sha,
            "automatic_retry": False,
            "campaign_stopped": current["status"] == "checkpoint_no_effect",
            "state_cleared": (
                boundary == len(transaction.operations) and
                current["status"] != "checkpoint_no_effect"),
            "firmware_region_mutation_enabled": False,
        }
    finally:
        backend.close()


def live_reconcile(transaction: ScratchTransaction, journal_path: Path, *,
                   backend_factory=FixedScratchReadOnlyBackend,
                   progress: bool = True) -> dict[str, object]:
    with scratch_journal_lock(transaction, journal_path):
        return _live_reconcile_locked(
            transaction, journal_path, backend_factory=backend_factory,
            progress=progress)


def _arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--baseline-a", required=True, type=Path)
    parser.add_argument("--baseline-b", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument(
        "--commit", action="store_true",
        help="open USB for this fixed command; dry-run is the default")


def _print_plan(command: str, transaction: ScratchTransaction,
                journal: dict[str, object] | None) -> None:
    print(f"command   : {command}")
    print(f"plan      : sha256 {PLAN_SHA256}")
    print(f"baseline  : sha256 {transaction.baseline_sha256}")
    print(f"loader    : sha256 {EXPECTED_LOADER_SHA256}")
    print(f"envelope  : [0x{ENVELOPE_LO:x},0x{ENVELOPE_HI:x})")
    print(f"operations: {len(transaction.operations)} fixed commands")
    print("firmware  : mutation hard-disabled")
    if journal is not None:
        print(f"status    : {journal['status']}")
        print(f"boundary  : {journal['boundary_index']}")
        if journal["status"] in {"intent", "checkpoint_no_effect"}:
            label = "intent" if journal["status"] == "intent" else "consumed"
            print(f"{label:<10}: {journal['active_operation_id']}")
            print("next      : reconcile only; mutation retry is prohibited")
            return
        boundary = journal["boundary_index"]
        if boundary < len(transaction.operations):
            operation = transaction.operations[boundary]
            print(f"next      : {operation.identifier} ({operation.action})")
            if boundary == CHECKPOINT_OPERATION_INDEX:
                print(f"checkpoint: mandatory {CHECKPOINT_POLICY}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
            ("preflight", "bind exact stock flash; no mutation unless later stepped"),
            ("step", "perform exactly one state-derived fixed scratch operation"),
            ("reconcile", "read-only classification after an uncertain step")):
        _arguments(commands.add_parser(command, help=help_text))
    arguments = parser.parse_args()
    try:
        transaction = load_transaction(arguments.baseline_a, arguments.baseline_b)
        validate_journal_path(transaction, arguments.journal)
        journal = None
        if arguments.command == "preflight":
            if os.path.lexists(arguments.journal):
                raise ScratchExecutorError(
                    "preflight refuses to replace an existing journal")
        else:
            journal = load_journal(arguments.journal)
            validate_journal(transaction, journal)
            if arguments.command == "step":
                _require_step_state(transaction, journal)
        _print_plan(arguments.command, transaction, journal)
        if not arguments.commit:
            print("\nDRY RUN -- no USB device was opened and nothing was changed.")
            return 0
        print("\nCOMMIT REQUESTED -- keep proven external SPI recovery available.")
        if arguments.command == "preflight":
            result = live_preflight(transaction, arguments.journal)
        elif arguments.command == "step":
            result = live_step(transaction, arguments.journal)
        else:
            result = live_reconcile(transaction, arguments.journal)
        print(json.dumps(result, indent=2, sort_keys=True))
        if result.get("reconciliation_required") is True:
            print(
                "\nRECONCILIATION REQUIRED: planned active-intent checkpoint "
                "reached after command completion and WIP-ready polling.",
                file=sys.stderr)
            print(
                "Do not run another step. Start a fresh process with reconcile "
                "--commit.", file=sys.stderr)
            return 4
        if result.get("campaign_stopped") is True:
            print(
                "\nCHECKPOINT CAMPAIGN STOPPED: the exact pre-command image "
                "was observed and this checkpoint attempt is consumed.",
                file=sys.stderr)
            print(
                "Do not retry or run step. Keep the device stable and report "
                "this result; the observed scratch image is exact, not corrupt.",
                file=sys.stderr)
            return 5
        return 0
    except ReconciliationRequired as error:
        print(f"\nRECONCILIATION REQUIRED: {error}", file=sys.stderr)
        print(
            "Do not run another step. Start a fresh process with reconcile "
            "--commit.", file=sys.stderr)
        return 4
    except RecoveryRequired as error:
        print(f"\nSPI RECOVERY REQUIRED: {error}", file=sys.stderr)
        print("Do not issue another USB mutation.", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nABORT: interrupted before durable mutation intent", file=sys.stderr)
        return 130
    except (ScratchExecutorError, SafetyError, RuntimeError,
            ValueError, OSError) as error:
        print(f"\nABORT: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
