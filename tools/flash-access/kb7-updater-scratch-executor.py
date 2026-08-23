#!/usr/bin/env python3
"""Fixed scratch-only execution harness for the KB7 USB updater model.

This is a destructive laboratory harness, not a firmware updater.  It replays
only the already reviewed 18-program/four-erase scratch command set.  The
caller cannot select an operation, address, CDB, payload, size, device, retry,
or recovery policy.  Each ``step`` derives exactly one next operation from a
separate durable scratch journal and is dry-run unless ``--commit`` is given.
At the fixed ``program-09`` boundary, after the complete program
CBW/data/validated-CSW exchange, ``step`` durably records command completion and
then deliberately terminates its own process with SIGKILL.  It performs no WIP
poll, post-read or boundary advance.  Only a fresh-process, read-only
``reconcile`` may consume that command-complete state, poll ready and classify
the result.

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
import signal
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

JOURNAL_SCHEMA = "kb7-usb-updater-scratch-journal-v3"
PLAN_SCHEMA = "kb7-usb-updater-fixed-scratch-plan-v3"
EXPECTED_SOURCE_SCRATCH_PLAN_SHA256 = (
    "d784f036e06a972d9688d15c76a41cbd7e90ca806d5ced1aeab5aae16745085b")
EXPECTED_PLAN_SHA256 = (
    "c1aa9348e74d6d4590b0e9666a9daf83e5544c3b23292b3df217c34038d5b653")

CHECKPOINT_OPERATION_INDEX = 9
CHECKPOINT_OPERATION_ID = "program-09"
CHECKPOINT_OPERATION_OFFSET = 0x000C6000
CHECKPOINT_OPERATION_CDB_HEX = "f60600600c6000000100000000000000"
CHECKPOINT_PAYLOAD_SHA256 = (
    "ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380")
CHECKPOINT_POLICY = "after_validated_program_csw_before_wip_poll_or_postread"
CHECKPOINT_TERMINATION = "self_sigkill"
CHECKPOINT_SIGNAL = signal.SIGKILL
CHECKPOINT_EXPECTED_SHELL_STATUS = 128 + CHECKPOINT_SIGNAL
CHECKPOINT_TERMINATION_FAILURE_STATUS = 126
PREFLIGHT_STARTED_STATUS = "preflight_started"
CHECKPOINT_READY_STATUS = "checkpoint_command_complete"
CHECKPOINT_RECONCILE_STARTED_STATUS = "checkpoint_reconcile_started"
FINAL_RECONCILE_STARTED_STATUS = "final_reconcile_started"
PROCESS_NONCE = os.urandom(32).hex()


class ScratchExecutorError(SafetyError):
    """A fixed-plan, state, transport, or verification failure."""


class ReconciliationRequired(ScratchExecutorError):
    """An exact pre-USB state permits only a fresh read-only action."""


class StateInspectionRequired(ScratchExecutorError):
    """An atomic publication outcome needs a fresh local-only inspection."""


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
        "failure_policy": {
            "preflight_started_durable_before_backend_construction_or_usb": True,
            "preflight_started_failure": "external_spi_no_retry",
            "raw_intent_durable_before_backend_construction_or_usb": True,
            "intent_publication_ambiguity": (
                "no_usb_fresh_process_dry_run_state_inspection"),
            "post_intent_transport_verification_or_checkpoint_ready_source_retained": (
                "abandon_without_explicit_close_external_spi"),
            "ordinary_operation_intent_reconciliation": (
                "prohibited_external_spi"),
            "checkpoint_intent_before_command_complete_reconciliation": (
                "prohibited_external_spi"),
            "checkpoint_command_complete_reconciliation": (
                "one_fresh_process_read_only_attempt"),
            "reconciliation_started_failure": (
                "external_spi_no_retry"),
            "mutation_or_reconciliation_close_failure": (
                "external_spi_no_retry"),
            "reconciliation_start_publication_failure_with_source_retained": (
                "fresh_process_retry_permitted"),
            "final_state_publication_source_retained_after_clean_close": (
                "external_spi_no_retry"),
            "checkpoint_ready_publication_error_with_exact_target_visible": (
                "read_only_cleanup_only_experiment_invalid"),
            "verified_boundary_publication_error_with_exact_target_visible": (
                "accept_exact_visible_target"),
            "final_clear_error_with_journal_absent": (
                "accept_exact_cleared_state"),
            "unclassifiable_atomic_transition_outcome": (
                "fresh_process_dry_run_state_inspection"),
        },
        "required_active_intent_checkpoint": {
            "operation_index": CHECKPOINT_OPERATION_INDEX,
            "operation_identifier": CHECKPOINT_OPERATION_ID,
            "operation_offset": CHECKPOINT_OPERATION_OFFSET,
            "operation_cdb_hex": CHECKPOINT_OPERATION_CDB_HEX,
            "payload_sha256": CHECKPOINT_PAYLOAD_SHA256,
            "policy": CHECKPOINT_POLICY,
            "termination": CHECKPOINT_TERMINATION,
            "signal": int(CHECKPOINT_SIGNAL),
            "expected_shell_status": CHECKPOINT_EXPECTED_SHELL_STATUS,
            "termination_failure_shell_status": (
                CHECKPOINT_TERMINATION_FAILURE_STATUS),
            "durable_command_complete_status_before_termination": (
                CHECKPOINT_READY_STATUS),
            "durable_reconciliation_started_status_before_usb": (
                CHECKPOINT_RECONCILE_STARTED_STATUS),
            "shell_status_137_required_for_validation_evidence": True,
            "shell_status_evidence_not_machine_bound": True,
            "invalid_termination_cleanup_must_not_count_as_validation": True,
            "command_complete_state_allows_cleanup_after_invalid_termination": True,
            "validated_program_csw_required": True,
            "wip_poll_before_termination": False,
            "postread_before_termination": False,
            "explicit_usb_close_before_termination": False,
            "fresh_process_wip_poll_required": True,
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


def _bound_identity_fields(journal: dict[str, object]) -> dict[str, str]:
    """Recover the already-verified USB/loader identity from one boundary."""
    keys = (
        "device_path", "identify_hex", "descriptor_sha256",
        "loader_fingerprint_sha256", "loader_window_sha256",
        "manifest_sha256",
    )
    identity = {key: journal[key] for key in keys}
    if any(not isinstance(value, str) for value in identity.values()):
        raise ScratchExecutorError("bound journal identity is malformed")
    return identity  # type: ignore[return-value]


def _unbound_preflight_identity(
        transaction: ScratchTransaction) -> dict[str, str]:
    stable_descriptor = (
        _writer._verify.LOADER_DESCRIPTOR_VERSION +
        _writer._verify.LOADER_DESCRIPTOR_DEVICE +
        _writer._verify.LOADER_DESCRIPTOR_MAGIC)
    identify = _writer.LOADER_IDENT
    return {
        "device_path": "unbound-preflight",
        "identify_hex": identify.hex(),
        "descriptor_sha256": _writer.sha256_bytes(stable_descriptor),
        "loader_fingerprint_sha256": _writer.sha256_bytes(
            identify + stable_descriptor),
        "loader_window_sha256": EXPECTED_LOADER_SHA256,
        "manifest_sha256": transaction.manifest.sha256,
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


def preflight_started_journal(
        transaction: ScratchTransaction) -> dict[str, object]:
    journal = boundary_journal(
        transaction, _unbound_preflight_identity(transaction), 0)
    journal["status"] = PREFLIGHT_STARTED_STATUS
    return journal


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
    if require_absent and not _path_is_exactly_absent(
            path, label="require-absent journal publication"):
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
    if status == PREFLIGHT_STARTED_STATUS:
        expected = preflight_started_journal(transaction)
        if journal != expected:
            raise ScratchExecutorError(
                "preflight-started journal is not canonical")
    elif status in {
            "intent", CHECKPOINT_READY_STATUS,
            CHECKPOINT_RECONCILE_STARTED_STATUS, "checkpoint_no_effect"}:
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
        if (status != "intent" and
                boundary != CHECKPOINT_OPERATION_INDEX):
            raise ScratchExecutorError(
                "checkpoint status is outside the reviewed boundary")
    elif status in {
            "boundary_verified", "complete",
            FINAL_RECONCILE_STARTED_STATUS}:
        if any(journal.get(key) is not None for key in (
                "active_operation_id", "active_operation_sha256",
                "pre_image_sha256", "post_image_sha256",
                "intent_process_nonce")):
            raise ScratchExecutorError("boundary journal contains an active intent")
        if journal.get("last_observed_sha256") != transaction.boundary_sha256[boundary]:
            raise ScratchExecutorError("boundary journal image hash is stale")
        if (status == "complete") != (
                boundary == len(transaction.operations)) and \
                status != FINAL_RECONCILE_STARTED_STATUS:
            raise ScratchExecutorError("complete status does not match the final boundary")
        if (status == FINAL_RECONCILE_STARTED_STATUS and
                boundary != len(transaction.operations)):
            raise ScratchExecutorError(
                "final reconciliation can start only at the final boundary")
    else:
        raise ScratchExecutorError("journal status is invalid")


def _publish_exact_transition(
        transaction: ScratchTransaction, journal_path: Path,
        source: dict[str, object], target: dict[str, object], *,
        label: str,
        fault: Callable[[str], None] | None = None) -> str:
    """Publish one exact state transition and classify atomic visible outcomes.

    The return value distinguishes a confirmed target, a target that became
    visible after the writer reported an error, and an exact retained source.
    An unreadable or third state is never called terminal recovery because a
    later strict load might expose an authorizing state; it requires a fresh
    process to inspect the journal without opening USB.
    """
    validate_journal(transaction, source)
    validate_journal(transaction, target)
    try:
        write_journal_atomic(journal_path, target, fault=fault)
    except BaseException as error:
        try:
            visible = load_journal(journal_path)
            validate_journal(transaction, visible)
        except BaseException as state_error:
            raise StateInspectionRequired(
                f"{label} reported an error and its visible state could not "
                "be classified without a fresh process"
            ) from state_error
        if visible == target:
            return "target_visible_after_error"
        if visible == source:
            return "source_visible_after_error"
        raise StateInspectionRequired(
            f"{label} exposed an unexpected valid state") from error
    try:
        visible = load_journal(journal_path)
        validate_journal(transaction, visible)
    except BaseException as error:
        raise StateInspectionRequired(
            f"{label} returned but could not be read back exactly") from error
    if visible == target:
        return "target_confirmed"
    if visible == source:
        return "source_visible_after_error"
    raise StateInspectionRequired(f"{label} exposed an unexpected valid state")


def _path_is_exactly_absent(path: Path, *, label: str) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError as error:
        raise StateInspectionRequired(
            f"{label} could not distinguish absence from a filesystem error"
        ) from error
    return False


def _publish_initial_preflight(
        transaction: ScratchTransaction, journal_path: Path,
        target: dict[str, object]) -> str:
    """Atomically replace exact absence with the terminal preflight marker."""
    validate_journal(transaction, target)
    if not _path_is_exactly_absent(
            journal_path, label="preflight-started publication"):
        raise ScratchExecutorError(
            "preflight refuses to replace an existing journal")
    try:
        write_journal_atomic(journal_path, target, require_absent=True)
    except BaseException as error:
        if _path_is_exactly_absent(
                journal_path, label="preflight-started publication"):
            return "source_visible_after_error"
        try:
            visible = load_journal(journal_path)
            validate_journal(transaction, visible)
        except BaseException as state_error:
            raise StateInspectionRequired(
                "preflight-started publication reported an error and its "
                "visible state could not be classified"
            ) from state_error
        if visible == target:
            return "target_visible_after_error"
        raise StateInspectionRequired(
            "preflight-started publication exposed an unexpected valid state"
        ) from error
    try:
        visible = load_journal(journal_path)
        validate_journal(transaction, visible)
    except BaseException as error:
        raise StateInspectionRequired(
            "preflight-started publication returned but could not be read "
            "back exactly") from error
    if visible != target:
        raise StateInspectionRequired(
            "preflight-started publication exposed an unexpected valid state")
    return "target_confirmed"


def _clear_exact_transition(
        transaction: ScratchTransaction, journal_path: Path,
        source: dict[str, object], *, label: str) -> str:
    """Clear one terminal state and classify the exact visible outcome.

    A distinct return means unlink became visible even though the clear
    operation reported an error (for example, a directory-fsync failure).  The
    flash was already exactly verified and the USB session cleanly closed, so
    absence is the safe completed state.  An unreadable or substituted state
    requires fresh local-only inspection rather than a misleading exit 3.
    """
    validate_journal(transaction, source)
    try:
        clear_journal(journal_path)
    except BaseException as error:
        if _path_is_exactly_absent(journal_path, label=label):
            return "target_visible_after_error"
        try:
            visible = load_journal(journal_path)
            validate_journal(transaction, visible)
        except BaseException as state_error:
            raise StateInspectionRequired(
                f"{label} reported an error and its visible state could not "
                "be classified without a fresh process"
            ) from state_error
        if visible == source:
            raise RecoveryRequired(
                f"{label} did not clear its terminal state") from error
        raise StateInspectionRequired(
            f"{label} exposed an unexpected valid state") from error
    if not _path_is_exactly_absent(journal_path, label=label):
        raise StateInspectionRequired(
            f"{label} returned but the absent state could not be confirmed")
    return "target_confirmed"


def _strict_close_usb_device(device) -> None:
    """Release one clean BOT session and surface every libusb close failure."""
    first_error: BaseException | None = None
    release_succeeded = False
    try:
        result = _writer._verify.lib.libusb_release_interface(
            device.h, device.iface)
        if result != 0:
            first_error = RuntimeError(
                f"libusb_release_interface failed ({result})")
        else:
            release_succeeded = True
        if release_succeeded and device.reattach:
            result = _writer._verify.lib.libusb_attach_kernel_driver(
                device.h, device.iface)
            if result != 0:
                first_error = RuntimeError(
                    f"libusb_attach_kernel_driver failed ({result})")
    except BaseException as error:
        first_error = error
    try:
        _writer._verify.lib.libusb_close(device.h)
    except BaseException as error:
        if first_error is None:
            first_error = error
    try:
        _writer._verify.lib.libusb_exit(device.ctx)
    except BaseException as error:
        if first_error is None:
            first_error = error
    if first_error is not None:
        raise first_error


class _StrictCloseMixin:
    def close(self) -> None:
        _strict_close_usb_device(self)


class FixedScratchNoRecoveryReadOnlyDevice(
        _StrictCloseMixin, _writer._verify.Device):
    """Read-only F6 transport that sends no endpoint recovery after errors."""

    clear_halt_on_error = False


class FixedScratchStrictWriteDevice(_StrictCloseMixin, _writer.WriteDevice):
    """Mutation transport whose clean-session close checks every libusb rc."""


class FixedScratchReadOnlyBackend:
    """Identity and full-chip reads through the read-only verifier whitelist."""

    def __init__(self, transaction: ScratchTransaction, operation_index: int,
                 *, device_factory=FixedScratchNoRecoveryReadOnlyDevice) -> None:
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

    def wait_ready(self) -> None:
        if self._closed:
            raise ScratchExecutorError("ready polling is unavailable after close")
        _writer.poll_ready(self._device)

    def close(self) -> None:
        if not self._closed:
            try:
                self._device.close()
            finally:
                self._closed = True


class FixedScratchUsbMutationBackend:
    """One-operation strict transport with no caller-supplied flash fields."""

    def __init__(self, transaction: ScratchTransaction, operation_index: int,
                 *, device_factory=FixedScratchStrictWriteDevice) -> None:
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

    def execute_checkpoint_before_poll(self) -> None:
        """Complete F6 18 and the program CSW, but issue no WIP poll."""
        if self._operation.identifier != CHECKPOINT_OPERATION_ID:
            raise ScratchExecutorError(
                "abrupt checkpoint is restricted to the reviewed operation")
        self.set_mode()
        self.mutate()

    def abandon_without_close(self) -> None:
        """Mark the post-CSW handle as intentionally left to SIGKILL."""
        self._require_phase("mutation_sent")
        self._phase = "abandoned"

    def close(self) -> None:
        if self._phase != "closed":
            try:
                self._device.close()
            finally:
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


def _planned_sigkill() -> None:
    """End the checkpoint process without Python/libusb cleanup."""
    # The caller has already durably published command completion. Do not add
    # any further output or other fallible work between this call and SIGKILL.
    try:
        os.kill(os.getpid(), CHECKPOINT_SIGNAL)
    except BaseException:
        os._exit(CHECKPOINT_TERMINATION_FAILURE_STATUS)
    # Returning from os.kill() means the required signal was not delivered.
    # Never counterfeit the evidence-bearing status 137 with a normal exit.
    os._exit(CHECKPOINT_TERMINATION_FAILURE_STATUS)


def _live_preflight_locked(transaction: ScratchTransaction, journal_path: Path, *,
                           backend_factory=FixedScratchReadOnlyBackend,
                           progress: bool = True) -> dict[str, object]:
    validate_journal_path(transaction, journal_path)
    started = preflight_started_journal(transaction)
    initial_outcome = _publish_initial_preflight(
        transaction, journal_path, started)
    if initial_outcome == "source_visible_after_error":
        raise StateInspectionRequired(
            "preflight-started was not published and no USB was opened; "
            "inspect the absent state in a fresh preflight dry-run")
    if initial_outcome == "target_visible_after_error":
        raise RecoveryRequired(
            "preflight-started became visible after a publication error; no "
            "USB was opened and external-SPI recovery is required")

    backend = None
    transition_in_flight: tuple[
        dict[str, object], dict[str, object], str] | None = None
    final_state_is_authoritative = False
    try:
        backend = backend_factory(transaction, 0)
        raw_identity = backend.identity()
        observed = _two_stable_reads(backend, progress=progress)
        _require_live_image(
            transaction, transaction.baseline, observed,
            "scratch preflight versus baseline")
        identity = _identity_fields(raw_identity, observed)
        try:
            backend.close()
        except BaseException as error:
            raise RecoveryRequired(
                "scratch preflight ended with an uncertain USB close; do not "
                "authorize mutation") from error
        journal = boundary_journal(transaction, identity, 0)
        transition_in_flight = (
            started, journal, "preflight verified-boundary publication")
        final_outcome = _publish_exact_transition(
            transaction, journal_path, started, journal,
            label="preflight verified-boundary publication")
        if final_outcome == "source_visible_after_error":
            transition_in_flight = None
            raise RecoveryRequired(
                "preflight verified boundary was not published; the "
                "preflight-started state is terminal")
        final_state_is_authoritative = True
        transition_in_flight = None
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
    except (StateInspectionRequired, RecoveryRequired):
        raise
    except BaseException as error:
        if transition_in_flight is not None or final_state_is_authoritative:
            raise StateInspectionRequired(
                "preflight final publication was interrupted after an atomic "
                "state transition; inspect it in a fresh dry-run") from error
        raise RecoveryRequired(
            "scratch preflight transport or exact verification failed after "
            "its durable start marker; do not probe this USB session") from error


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
    if status == PREFLIGHT_STARTED_STATUS:
        raise RecoveryRequired(
            "a preflight USB attempt was already consumed; external-SPI "
            "recovery is required")
    if status == "intent":
        raise RecoveryRequired(
            "a raw operation intent has no command-complete authorization; "
            "USB continuation and reconciliation are prohibited")
    if status == CHECKPOINT_READY_STATUS:
        raise ReconciliationRequired(
            "the checkpoint command-complete state requires fresh-process "
            "read-only reconciliation")
    if status in {
            CHECKPOINT_RECONCILE_STARTED_STATUS,
            FINAL_RECONCILE_STARTED_STATUS}:
        raise RecoveryRequired(
            "a one-shot reconciliation was already consumed; external-SPI "
            "recovery is required")
    if status == "checkpoint_no_effect":
        raise RecoveryRequired(
            "checkpoint campaign is consumed; no further USB command is "
            "authorized before external-SPI baseline restore")
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
                      journal_fault: Callable[[str], None] | None = None,
                      checkpoint_terminator: Callable[[], None] = _planned_sigkill,
                      ) -> dict[str, object]:
    validate_journal_path(transaction, journal_path)
    current = load_journal(journal_path)
    index = _require_step_state(transaction, current)
    operation = transaction.operations[index]
    is_checkpoint = index == CHECKPOINT_OPERATION_INDEX
    preimage = expected_boundary_image(transaction, index)
    postimage = expected_boundary_image(transaction, index + 1)
    bound_identity = _bound_identity_fields(current)
    intent = intent_journal(transaction, bound_identity, index)
    backend = None
    intent_is_durable = False
    checkpoint_ready_is_durable = False
    final_state_is_authoritative = False
    transition_in_flight: tuple[
        dict[str, object], dict[str, object], str] | None = None
    try:
        # Consume this one-shot operation before constructing a backend or
        # issuing any USB command.  A constructor, identity or pre-read anomaly
        # therefore leaves a raw intent that cannot authorize another session.
        transition_in_flight = (
            current, intent, "scratch raw-intent publication")
        intent_outcome = _publish_exact_transition(
            transaction, journal_path, current, intent,
            label="scratch raw-intent publication", fault=journal_fault)
        if intent_outcome == "source_visible_after_error":
            transition_in_flight = None
            raise StateInspectionRequired(
                "scratch raw intent was not published and no USB was opened; "
                "inspect the unchanged boundary in a fresh dry-run")
        intent_is_durable = True
        if intent_outcome == "target_visible_after_error":
            transition_in_flight = None
            raise RecoveryRequired(
                "scratch raw intent became visible after a publication error; "
                "no USB was opened and external-SPI recovery is required")
        transition_in_flight = None

        backend = backend_factory(transaction, index)
        raw_identity = backend.identity()
        observed = _two_stable_reads(backend, progress=progress)
        _require_live_image(transaction, preimage, observed, "scratch step preimage")
        identity = _identity_fields(raw_identity, observed)
        validate_journal(transaction, current, identity)
        validate_journal(transaction, intent, identity)
        # From the first transport command through exact post-verification, an
        # anomaly can leave BOT or flash state uncertain. Do not explicitly
        # release/reattach this interface; require the proven SPI path.
        if is_checkpoint:
            try:
                backend.execute_checkpoint_before_poll()
            except BaseException as error:
                raise RecoveryRequired(
                    "checkpoint transport failed before a validated program "
                    "CSW; do not probe this USB session") from error
            backend.abandon_without_close()
            ready = dict(intent)
            ready["status"] = CHECKPOINT_READY_STATUS
            transition_in_flight = (
                intent, ready, "checkpoint command-complete publication")
            ready_outcome = _publish_exact_transition(
                transaction, journal_path, intent, ready,
                label="checkpoint command-complete publication",
                fault=journal_fault)
            if ready_outcome == "source_visible_after_error":
                transition_in_flight = None
                raise RecoveryRequired(
                    "checkpoint command-complete state was not published; "
                    "the raw intent is terminal and USB is prohibited")
            checkpoint_ready_is_durable = True
            transition_in_flight = None
            if ready_outcome == "target_visible_after_error":
                raise ReconciliationRequired(
                    "the exact checkpoint command-complete state became "
                    "visible after a publication error; the experiment is "
                    "invalid and only fresh-process read-only cleanup is "
                    "authorized")
            try:
                checkpoint_terminator()
            except BaseException as error:
                raise ReconciliationRequired(
                    "checkpoint command completion is durable, but planned "
                    "host termination failed; the experiment is invalid and "
                    "only fresh-process read-only cleanup is authorized"
                ) from error
            raise ReconciliationRequired(
                "checkpoint command completion is durable, but planned host "
                "termination returned; the experiment is invalid and only "
                "fresh-process read-only cleanup is authorized")
        try:
            backend.execute()
            observed = _two_stable_reads(backend, progress=progress)
            _require_live_image(
                transaction, postimage, observed, "scratch step postimage")
        except BaseException as error:
            raise RecoveryRequired(
                "scratch transport or exact verification failed after durable "
                "intent; do not probe this USB session") from error
        try:
            backend.close()
        except BaseException as error:
            raise RecoveryRequired(
                "scratch operation exact postimage was verified, but its USB "
                "session did not close cleanly") from error
        verified = boundary_journal(transaction, identity, index + 1)
        transition_in_flight = (
            intent, verified, "scratch verified-boundary publication")
        verified_outcome = _publish_exact_transition(
            transaction, journal_path, intent, verified,
            label="scratch verified-boundary publication",
            fault=journal_fault)
        if verified_outcome == "source_visible_after_error":
            transition_in_flight = None
            raise RecoveryRequired(
                "scratch verified boundary was not published; the raw intent "
                "is terminal and USB reconciliation is prohibited")
        final_state_is_authoritative = True
        transition_in_flight = None
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
    except (StateInspectionRequired, RecoveryRequired):
        raise
    except ReconciliationRequired as error:
        if checkpoint_ready_is_durable:
            raise
        if intent_is_durable:
            raise RecoveryRequired(
                f"scratch operation {operation.identifier} stopped before "
                "durable checkpoint command completion; USB reconciliation "
                "is prohibited") from error
        raise
    except BaseException as error:
        if checkpoint_ready_is_durable:
            raise ReconciliationRequired(
                "checkpoint command completion is durable, but the process "
                "stopped before its planned SIGKILL; only fresh-process "
                "read-only cleanup is authorized") from error
        if transition_in_flight is not None or final_state_is_authoritative:
            label = (
                transition_in_flight[2] if transition_in_flight is not None
                else "scratch verified-boundary publication")
            raise StateInspectionRequired(
                f"{label} was interrupted after an atomic state transition; "
                "inspect the journal in a fresh dry-run before any USB action"
            ) from error
        if intent_is_durable:
            raise RecoveryRequired(
                f"scratch operation {operation.identifier} stopped after "
                f"durable intent; USB reconciliation is prohibited: {error}"
            ) from error
        raise


def live_step(transaction: ScratchTransaction, journal_path: Path, *,
              backend_factory=FixedScratchUsbMutationBackend,
              progress: bool = True,
              journal_fault: Callable[[str], None] | None = None,
              checkpoint_terminator: Callable[[], None] = _planned_sigkill,
              ) -> dict[str, object]:
    with scratch_journal_lock(transaction, journal_path):
        return _live_step_locked(
            transaction, journal_path, backend_factory=backend_factory,
            progress=progress, journal_fault=journal_fault,
            checkpoint_terminator=checkpoint_terminator)


def _require_reconcile_state(transaction: ScratchTransaction,
                             journal: dict[str, object]) -> None:
    """Admit only exact checkpoint-command-complete or final-complete state."""
    validate_journal(transaction, journal)
    status = journal["status"]
    if status == PREFLIGHT_STARTED_STATUS:
        raise RecoveryRequired(
            "a preflight USB attempt was already consumed; reconciliation "
            "and further USB commands are prohibited")
    if status == "intent":
        raise RecoveryRequired(
            "a raw operation intent does not prove checkpoint command "
            "completion; USB reconciliation is prohibited")
    if status == CHECKPOINT_READY_STATUS:
        _validate_checkpoint_operation(transaction.operations)
        return
    if status in {
            CHECKPOINT_RECONCILE_STARTED_STATUS,
            FINAL_RECONCILE_STARTED_STATUS}:
        raise RecoveryRequired(
            "a one-shot reconciliation was already started; no further USB "
            "command is authorized")
    if status == "checkpoint_no_effect":
        raise RecoveryRequired(
            "the checkpoint campaign is consumed; do not issue another USB "
            "command before external-SPI baseline restore")
    if status == "boundary_verified":
        raise ScratchExecutorError(
            "intermediate verified boundaries are not reconcilable; run the "
            "next fixed step or stop")
    if status != "complete":
        raise ScratchExecutorError("journal is not a reconcilable stable state")


def _reconciliation_started_journal(
        source: dict[str, object]) -> dict[str, object]:
    started = dict(source)
    if source["status"] == CHECKPOINT_READY_STATUS:
        started["status"] = CHECKPOINT_RECONCILE_STARTED_STATUS
        started["intent_process_nonce"] = PROCESS_NONCE
    elif source["status"] == "complete":
        started["status"] = FINAL_RECONCILE_STARTED_STATUS
    else:
        raise ScratchExecutorError("cannot consume a non-reconcilable journal")
    return started


def _publish_reconciliation_started(
        transaction: ScratchTransaction, journal_path: Path,
        source: dict[str, object]) -> dict[str, object]:
    """Consume one reconciliation attempt and verify it before opening USB."""
    started = _reconciliation_started_journal(source)
    validate_journal(transaction, started)
    outcome = _publish_exact_transition(
        transaction, journal_path, source, started,
        label="reconciliation-started publication")
    if outcome == "source_visible_after_error":
        raise ReconciliationRequired(
            "reconciliation authorization was not consumed; no USB was "
            "opened and a fresh-process retry is permitted")
    if outcome == "target_visible_after_error":
        raise RecoveryRequired(
            "reconciliation-started became visible after a publication "
            "error; the one-shot attempt is consumed and no USB was opened")
    return started


def _live_reconcile_locked(transaction: ScratchTransaction, journal_path: Path, *,
                           backend_factory=FixedScratchReadOnlyBackend,
                           progress: bool = True) -> dict[str, object]:
    validate_journal_path(transaction, journal_path)
    source = load_journal(journal_path)
    _require_reconcile_state(transaction, source)
    checkpoint_reconciliation = source["status"] == CHECKPOINT_READY_STATUS
    index = source["boundary_index"]
    if (checkpoint_reconciliation and
            hmac.compare_digest(
                source["intent_process_nonce"], PROCESS_NONCE)):
        raise ScratchExecutorError(
            "checkpoint command completion must be reconciled by a fresh process")
    current = _publish_reconciliation_started(
        transaction, journal_path, source)
    backend_index = min(index, len(transaction.operations) - 1)
    fresh_process_wip_poll_completed = False
    final_state_is_authoritative = False
    transition_in_flight: tuple[
        dict[str, object], dict[str, object] | None, str] | None = None
    try:
        backend = backend_factory(transaction, backend_index)
        raw_identity = backend.identity()
        if checkpoint_reconciliation:
            backend.wait_ready()
            fresh_process_wip_poll_completed = True
        observed = _two_stable_reads(backend, progress=progress)
        identity = _identity_fields(raw_identity, observed)
        validate_journal(transaction, current, identity)
        observed_sha = _writer.sha256_bytes(observed)
        campaign_stopped = False
        if checkpoint_reconciliation:
            pre_sha = source["pre_image_sha256"]
            post_sha = source["post_image_sha256"]
            if hmac.compare_digest(observed_sha, pre_sha):
                boundary = index
                classification = "exact_preimage_checkpoint_consumed_no_effect"
                campaign_stopped = True
            elif hmac.compare_digest(observed_sha, post_sha):
                boundary = index + 1
                classification = "exact_postimage_completed"
            else:
                raise RecoveryRequired(
                    "stable image is neither the exact intent preimage nor postimage")
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
        try:
            backend.close()
        except BaseException as error:
            raise RecoveryRequired(
                "exact reconciliation image was classified, but the USB "
                "session did not close cleanly") from error
        if campaign_stopped:
            verified = dict(source)
            verified.update(identity)
            verified["status"] = "checkpoint_no_effect"
            verified["last_observed_sha256"] = observed_sha
            verified["intent_process_nonce"] = PROCESS_NONCE
            validate_journal(transaction, verified, identity)
            transition_in_flight = (
                current, verified, "checkpoint no-effect publication")
            final_outcome = _publish_exact_transition(
                transaction, journal_path, current, verified,
                label="checkpoint no-effect publication")
            if final_outcome == "source_visible_after_error":
                transition_in_flight = None
                raise RecoveryRequired(
                    "checkpoint no-effect state was not published; the "
                    "reconciliation-started state is terminal")
            final_state_is_authoritative = True
            transition_in_flight = None
        elif boundary == len(transaction.operations):
            transition_in_flight = (
                current, None, "final reconciliation state clear")
            _clear_exact_transition(
                transaction, journal_path, current,
                label="final reconciliation state clear")
            final_state_is_authoritative = True
            transition_in_flight = None
        else:
            verified = boundary_journal(transaction, identity, boundary)
            transition_in_flight = (
                current, verified,
                "checkpoint reconciled-boundary publication")
            final_outcome = _publish_exact_transition(
                transaction, journal_path, current, verified,
                label="checkpoint reconciled-boundary publication")
            if final_outcome == "source_visible_after_error":
                transition_in_flight = None
                raise RecoveryRequired(
                    "checkpoint reconciled boundary was not published; the "
                    "reconciliation-started state is terminal")
            final_state_is_authoritative = True
            transition_in_flight = None
        return {
            "classification": classification,
            "boundary_index": boundary,
            "next_operation": (
                None if (campaign_stopped or
                         boundary == len(transaction.operations))
                else transaction.operations[boundary].identifier),
            "observed_sha256": observed_sha,
            "automatic_retry": False,
            "fresh_process_wip_poll_completed": (
                fresh_process_wip_poll_completed),
            "campaign_stopped": campaign_stopped,
            "state_cleared": (
                boundary == len(transaction.operations) and
                not campaign_stopped),
            "firmware_region_mutation_enabled": False,
        }
    except (StateInspectionRequired, RecoveryRequired):
        raise
    except BaseException as error:
        if transition_in_flight is not None or final_state_is_authoritative:
            label = (
                transition_in_flight[2] if transition_in_flight is not None
                else "scratch reconciliation final state")
            raise StateInspectionRequired(
                f"{label} was interrupted after an atomic state transition; "
                "inspect the journal in a fresh dry-run before any USB action"
            ) from error
        raise RecoveryRequired(
            "one-shot read-only reconciliation failed after its durable "
            "authorization was consumed; do not issue another USB command"
        ) from error


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


def _inspection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--baseline-a", required=True, type=Path)
    parser.add_argument("--baseline-b", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)


def _inspection_result(
        transaction: ScratchTransaction,
        journal: dict[str, object] | None) -> dict[str, object]:
    if journal is None:
        return {
            "journal_status": "absent",
            "boundary_index": None,
            "permitted_next": "preflight_dry_run_only",
            "usb_opened": False,
        }
    status = journal["status"]
    boundary = journal["boundary_index"]
    if status == "boundary_verified":
        next_action = "step_dry_run"
    elif status in {CHECKPOINT_READY_STATUS, "complete"}:
        next_action = "reconcile_dry_run"
    else:
        next_action = "external_spi_no_usb"
    return {
        "journal_status": status,
        "boundary_index": boundary,
        "permitted_next": next_action,
        "usb_opened": False,
    }


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
        if journal["status"] in {
                PREFLIGHT_STARTED_STATUS,
                CHECKPOINT_RECONCILE_STARTED_STATUS,
                FINAL_RECONCILE_STARTED_STATUS}:
            print("next      : external-SPI recovery; USB is prohibited")
            return
        if journal["status"] in {
                "intent", CHECKPOINT_READY_STATUS, "checkpoint_no_effect"}:
            label = {
                "intent": "intent",
                CHECKPOINT_READY_STATUS: "ready",
                "checkpoint_no_effect": "consumed",
            }[journal["status"]]
            print(f"{label:<10}: {journal['active_operation_id']}")
            if journal["status"] == CHECKPOINT_READY_STATUS:
                print("next      : one fresh-process read-only reconcile")
            else:
                print("next      : external-SPI recovery; USB is prohibited")
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
            ("reconcile", "read-only classification of checkpoint or final state")):
        _arguments(commands.add_parser(command, help=help_text))
    _inspection_arguments(commands.add_parser(
        "inspect", help="inspect only the local fixed journal; never open USB"))
    arguments = parser.parse_args()
    try:
        transaction = load_transaction(arguments.baseline_a, arguments.baseline_b)
        validate_journal_path(transaction, arguments.journal)
        if arguments.command == "inspect":
            if _path_is_exactly_absent(
                    arguments.journal, label="scratch journal inspection"):
                journal = None
            else:
                journal = load_journal(arguments.journal)
                validate_journal(transaction, journal)
            _print_plan(arguments.command, transaction, journal)
            print(json.dumps(
                _inspection_result(transaction, journal),
                indent=2, sort_keys=True))
            return 0
        journal = None
        if arguments.command == "preflight":
            if not _path_is_exactly_absent(
                    arguments.journal, label="preflight journal inspection"):
                existing = load_journal(arguments.journal)
                validate_journal(transaction, existing)
                if existing["status"] == PREFLIGHT_STARTED_STATUS:
                    raise RecoveryRequired(
                        "a prior preflight USB attempt was consumed; external-"
                        "SPI recovery is required")
                raise ScratchExecutorError(
                    "preflight refuses to replace an existing journal")
        else:
            journal = load_journal(arguments.journal)
            validate_journal(transaction, journal)
            if arguments.command == "step":
                _require_step_state(transaction, journal)
            else:
                _require_reconcile_state(transaction, journal)
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
        if result.get("campaign_stopped") is True:
            print(
                "\nCHECKPOINT CAMPAIGN STOPPED: the exact pre-command image "
                "was observed and this checkpoint attempt is consumed.",
                file=sys.stderr)
            print(
                "Do not retry or run step. Keep the device stable and use the "
                "rehearsed external SPI restore before normal boot or another "
                "campaign; the observed scratch image is exact, not corrupt.",
                file=sys.stderr)
            return 5
        return 0
    except StateInspectionRequired as error:
        print(f"\nSTATE INSPECTION REQUIRED: {error}", file=sys.stderr)
        print(
            "This result authorizes no further USB action. Start a fresh "
            "process with the inspect command; it performs local journal "
            "validation only and reports the permitted dry-run or SPI action.",
            file=sys.stderr)
        return 4
    except ReconciliationRequired as error:
        print(f"\nRECONCILIATION REQUIRED: {error}", file=sys.stderr)
        print(
            "Do not run another step. Start a fresh process with reconcile "
            "--commit.", file=sys.stderr)
        return 4
    except RecoveryRequired as error:
        print(f"\nSPI RECOVERY REQUIRED: {error}", file=sys.stderr)
        print(
            "Do not issue another USB command; recover and verify the complete "
            "baseline via external SPI.", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print(
            "\nABORT: interrupted outside a classified operation result. "
            "Do not issue another USB command until a fresh local-only "
            "inspect classifies the journal.", file=sys.stderr)
        return 130
    except (ScratchExecutorError, SafetyError, RuntimeError,
            ValueError, OSError) as error:
        print(f"\nABORT: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
