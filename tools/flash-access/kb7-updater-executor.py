#!/usr/bin/env python3
"""Read-only front end and locked transaction engine for KB7 USB updates.

The public CLI has only two read-only device operations:

``preflight``
    Reverify an offline V1.22 bundle, read the complete flash twice through the
    preserved loader, require the exact planned baseline, and create a durable
    device/session-bound journal.

``reconcile``
    Read the complete flash twice, classify the image from flash contents, and
    repair journal position only when the image is an exact modeled boundary.

The mutation engine below is exercised with fake transports by the test suite,
but live mutation is deliberately not wired and no execute/commit command is
exposed.  Enabling it requires a reviewed source change plus the remaining
scratch fault-injection and recovery evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
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
    "kb7_updater_plan_for_executor", TOOL_DIRECTORY / "kb7-updater-plan.py")
_writer = _load_module(
    "kb7_isp_writer_for_executor", TOOL_DIRECTORY / "kb7-isp-write2.py")

SafetyError = _writer.SafetyError

JOURNAL_SCHEMA = "kb7-usb-updater-journal-v1"
LIVE_MUTATION_ENABLED = False

FAULT_SITES = (
    "before_intent",
    "during_intent",
    "after_intent",
    "during_f6_18",
    "during_cbw",
    "during_data_or_erase",
    "before_csw",
    "bad_csw",
    "during_poll",
    "poll_timeout",
    "before_readback",
    "short_readback",
    "after_compare",
    "during_verified_journal",
    "after_verified_journal",
)

JOURNAL_KEYS = {
    "schema",
    "status",
    "bundle_id",
    "baseline_sha256",
    "target_full_sha256",
    "device_path",
    "identify_hex",
    "descriptor_sha256",
    "loader_fingerprint_sha256",
    "loader_window_sha256",
    "manifest_sha256",
    "executor_source_sha256",
    "planner_source_sha256",
    "writer_source_sha256",
    "verifier_source_sha256",
    "operation_count",
    "boundary_index",
    "active_operation_index",
    "active_operation_sha256",
    "pre_full_sha256",
    "expected_post_full_sha256",
    "last_observed_full_sha256",
}


class ExecutorError(SafetyError):
    """A fail-closed executor, journal, or reconciliation error."""


class ExecutionLocked(ExecutorError):
    """Live firmware-region mutation is unavailable in this source revision."""


class ReconciliationRequired(ExecutorError):
    """A durable intent exists and flash must be classified before continuing."""


@dataclass(frozen=True)
class Transaction:
    baseline: bytes
    descriptor: dict[str, object]
    operations: tuple[object, ...]
    target_image: bytes
    boundary_mutable_hashes: tuple[str, ...]
    bundle_dir: Path
    baseline_paths: tuple[Path, Path]

    @property
    def bundle_id(self) -> str:
        return str(self.descriptor["bundle_id"])

    @property
    def baseline_sha256(self) -> str:
        return _planner.sha256(self.baseline)

    @property
    def target_full_sha256(self) -> str:
        return str(self.descriptor["target_full_sha256"])


def _source_sha256(path: str | os.PathLike[str]) -> str:
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def implementation_hashes() -> dict[str, str]:
    return {
        "executor_source_sha256": _source_sha256(__file__),
        "planner_source_sha256": _source_sha256(_planner.__file__),
        "writer_source_sha256": _source_sha256(_writer.__file__),
        "verifier_source_sha256": _source_sha256(_writer._verify.__file__),
    }


def _targets_and_staged(bundle_dir: Path, descriptor: dict[str, object]
                        ) -> tuple[dict[str, bytes], dict[str, bytes]]:
    pair_text = descriptor.get("pair_id")
    if not isinstance(pair_text, str):
        raise ExecutorError("bundle pair identifier is missing")
    try:
        pair_id = bytes.fromhex(pair_text)
    except ValueError as error:
        raise ExecutorError("bundle pair identifier is not hexadecimal") from error
    metadata = descriptor.get("regions")
    if not isinstance(metadata, dict):
        raise ExecutorError("bundle region metadata is missing")

    targets: dict[str, bytes] = {}
    staged: dict[str, bytes] = {}
    for spec in _planner.REGIONS:
        envelope = _planner.read_regular(
            bundle_dir / f"{spec.name}-sector-image.bin")
        target = envelope[:spec.length]
        targets[spec.name] = target
        staged[spec.name] = _planner.validate_target_region(
            target, spec, pair_id, metadata[spec.name])
    return targets, staged


def load_transaction(bundle_dir: Path, baseline_a: Path, baseline_b: Path,
                     *, anchors: dict[str, str] | None = None) -> Transaction:
    # Let the planner inspect the paths before canonicalizing them. Resolving a
    # symlink first would erase the evidence needed by its non-symlink policy.
    _planner.verify_bundle(bundle_dir, baseline_a, baseline_b, anchors=anchors)
    descriptor = _planner.load_descriptor(bundle_dir)
    baseline = _planner.load_baselines(baseline_a, baseline_b)
    targets, staged = _targets_and_staged(bundle_dir, descriptor)
    operations, _information = _planner.build_operations(baseline, targets, staged)
    if not operations:
        raise ExecutorError("bundle has no update operations")

    current = bytearray(baseline)
    boundary_hashes = [_planner.mutable_state_sha256(current)]
    for operation in operations:
        _planner.apply_operation(current, operation)
        boundary_hashes.append(_planner.mutable_state_sha256(current))
    target_image = bytes(current)
    if _planner.sha256(target_image) != descriptor.get("target_full_sha256"):
        raise ExecutorError("reconstructed target does not match the bundle")
    traces = descriptor.get("operations")
    if not isinstance(traces, list) or len(traces) != len(operations):
        raise ExecutorError("bundle operation count is inconsistent")
    expected_hashes = [str(traces[0]["pre_state_sha256"])] + [
        str(trace["post_state_sha256"]) for trace in traces
    ]
    if boundary_hashes != expected_hashes:
        raise ExecutorError("operation boundary hashes do not reproduce")
    return Transaction(
        baseline=baseline,
        descriptor=descriptor,
        operations=tuple(operations),
        target_image=target_image,
        boundary_mutable_hashes=tuple(boundary_hashes),
        bundle_dir=bundle_dir.resolve(strict=True),
        baseline_paths=(baseline_a.resolve(strict=True), baseline_b.resolve(strict=True)),
    )


def expected_boundary_image(transaction: Transaction, boundary_index: int) -> bytes:
    if not 0 <= boundary_index <= len(transaction.operations):
        raise ExecutorError("journal boundary index is outside the plan")
    image = bytearray(transaction.baseline)
    for operation in transaction.operations[:boundary_index]:
        _planner.apply_operation(image, operation)
    return bytes(image)


def operation_sha256(transaction: Transaction, index: int) -> str:
    traces = transaction.descriptor["operations"]
    return _planner.canonical_sha256(traces[index])


def _identity_fields(identity: dict[str, str], live_image: bytes) -> dict[str, str]:
    required = {
        "device_path", "identify_hex", "descriptor_sha256",
        "loader_fingerprint_sha256",
    }
    if set(identity) != required or any(
            not isinstance(identity[key], str) or not identity[key] for key in required):
        raise ExecutorError("live loader identity is malformed")
    return {
        **identity,
        "loader_window_sha256": _planner.sha256(
            live_image[_planner.LOADER_START:_planner.MANIFEST_START]),
        "manifest_sha256": _planner.sha256(
            live_image[_planner.MANIFEST_START:_planner.CORE0_START]),
    }


def _journal_common(transaction: Transaction, identity: dict[str, str]) -> dict[str, object]:
    return {
        "schema": JOURNAL_SCHEMA,
        "bundle_id": transaction.bundle_id,
        "baseline_sha256": transaction.baseline_sha256,
        "target_full_sha256": transaction.target_full_sha256,
        "device_path": identity["device_path"],
        "identify_hex": identity["identify_hex"],
        "descriptor_sha256": identity["descriptor_sha256"],
        "loader_fingerprint_sha256": identity["loader_fingerprint_sha256"],
        "loader_window_sha256": identity["loader_window_sha256"],
        "manifest_sha256": identity["manifest_sha256"],
        **implementation_hashes(),
        "operation_count": len(transaction.operations),
    }


def boundary_journal(transaction: Transaction, identity: dict[str, str],
                     boundary_index: int, *, preflight: bool = False) -> dict[str, object]:
    image = expected_boundary_image(transaction, boundary_index)
    if boundary_index == len(transaction.operations):
        status = "complete"
    elif preflight and boundary_index == 0:
        status = "preflight_verified"
    else:
        status = "boundary_verified"
    return {
        **_journal_common(transaction, identity),
        "status": status,
        "boundary_index": boundary_index,
        "active_operation_index": None,
        "active_operation_sha256": None,
        "pre_full_sha256": None,
        "expected_post_full_sha256": None,
        "last_observed_full_sha256": _planner.sha256(image),
    }


def intent_journal(transaction: Transaction, identity: dict[str, str],
                   operation_index: int) -> dict[str, object]:
    preimage = expected_boundary_image(transaction, operation_index)
    postimage = bytearray(preimage)
    _planner.apply_operation(postimage, transaction.operations[operation_index])
    return {
        **_journal_common(transaction, identity),
        "status": "intent",
        "boundary_index": operation_index,
        "active_operation_index": operation_index,
        "active_operation_sha256": operation_sha256(transaction, operation_index),
        "pre_full_sha256": _planner.sha256(preimage),
        "expected_post_full_sha256": _planner.sha256(postimage),
        "last_observed_full_sha256": _planner.sha256(preimage),
    }


def _reject_json_constant(value: str):
    raise ExecutorError(f"non-finite JSON number is not permitted: {value}")


def _duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ExecutorError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_journal(path: Path) -> dict[str, object]:
    _safe_journal_parent(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as error:
        raise ExecutorError("updater journal does not exist") from error
    except OSError as error:
        raise ExecutorError("cannot safely open updater journal") from error
    try:
        information = os.fstat(descriptor)
        if not stat.S_ISREG(information.st_mode):
            raise ExecutorError("updater journal is not a regular non-symlink file")
        if information.st_size > 65536:
            raise ExecutorError("updater journal is unexpectedly large")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(65537)
        after = os.fstat(descriptor)
        if (len(raw) != information.st_size or len(raw) > 65536 or
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                 after.st_ctime_ns) !=
                (information.st_dev, information.st_ino, information.st_size,
                 information.st_mtime_ns, information.st_ctime_ns)):
            raise ExecutorError("updater journal changed while it was read")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(
            raw, object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ExecutorError("updater journal is not strict JSON") from error
    if not isinstance(value, dict) or set(value) != JOURNAL_KEYS:
        raise ExecutorError("updater journal has missing or unknown fields")
    return value


def _validate_hex(value: object, length: int, field: str) -> None:
    if (not isinstance(value, str) or len(value) != length or
            any(character not in "0123456789abcdef" for character in value)):
        raise ExecutorError(f"journal {field} is malformed")


def validate_journal(transaction: Transaction, journal: dict[str, object],
                     identity: dict[str, str] | None = None) -> None:
    if set(journal) != JOURNAL_KEYS or journal.get("schema") != JOURNAL_SCHEMA:
        raise ExecutorError("journal schema does not match this executor")
    common = {
        "bundle_id": transaction.bundle_id,
        "baseline_sha256": transaction.baseline_sha256,
        "target_full_sha256": transaction.target_full_sha256,
        "operation_count": len(transaction.operations),
        **implementation_hashes(),
    }
    for key, expected in common.items():
        if type(journal.get(key)) is not type(expected) or journal.get(key) != expected:
            raise ExecutorError(f"journal {key} does not match this transaction")
    for key in (
            "baseline_sha256", "target_full_sha256", "descriptor_sha256",
            "loader_fingerprint_sha256", "loader_window_sha256",
            "manifest_sha256", "executor_source_sha256", "planner_source_sha256",
            "writer_source_sha256", "verifier_source_sha256"):
        _validate_hex(journal.get(key), 64, key)
    _validate_hex(journal.get("identify_hex"), len(_writer.LOADER_IDENT.hex()),
                  "identify_hex")
    if not isinstance(journal.get("device_path"), str) or not journal["device_path"]:
        raise ExecutorError("journal device_path is malformed")
    if identity is not None:
        for key in (
                "device_path", "identify_hex", "descriptor_sha256",
                "loader_fingerprint_sha256", "loader_window_sha256",
                "manifest_sha256"):
            if journal.get(key) != identity.get(key):
                raise ExecutorError(f"live device does not match journal {key}")

    status = journal.get("status")
    if status not in {"preflight_verified", "boundary_verified", "intent", "complete"}:
        raise ExecutorError("journal status is invalid")
    boundary = journal.get("boundary_index")
    if type(boundary) is not int or not 0 <= boundary <= len(transaction.operations):
        raise ExecutorError("journal boundary index is invalid")
    expected = expected_boundary_image(transaction, boundary)
    expected_hash = _planner.sha256(expected)
    if status == "intent":
        active = journal.get("active_operation_index")
        if type(active) is not int or active != boundary or active >= len(transaction.operations):
            raise ExecutorError("journal active operation is invalid")
        postimage = bytearray(expected)
        _planner.apply_operation(postimage, transaction.operations[active])
        if (journal.get("active_operation_sha256") != operation_sha256(transaction, active) or
                journal.get("pre_full_sha256") != expected_hash or
                journal.get("expected_post_full_sha256") != _planner.sha256(postimage) or
                journal.get("last_observed_full_sha256") != expected_hash):
            raise ExecutorError("journal intent does not bind its operation edge")
    else:
        if any(journal.get(key) is not None for key in (
                "active_operation_index", "active_operation_sha256",
                "pre_full_sha256", "expected_post_full_sha256")):
            raise ExecutorError("boundary journal unexpectedly contains an active operation")
        if journal.get("last_observed_full_sha256") != expected_hash:
            raise ExecutorError("boundary journal image hash is stale")
        if status == "complete" and boundary != len(transaction.operations):
            raise ExecutorError("complete journal is not at the final boundary")
        if status == "preflight_verified" and boundary != 0:
            raise ExecutorError("preflight journal is not at the stock boundary")


def _safe_journal_parent(path: Path) -> Path:
    parent = path.absolute().parent
    if not parent.exists():
        raise ExecutorError("journal parent does not exist; create it explicitly")
    information = parent.lstat()
    if (parent.is_symlink() or not stat.S_ISDIR(information.st_mode) or
            parent.resolve(strict=True) != parent):
        raise ExecutorError("journal parent is not a regular directory")
    return parent


def write_journal_atomic(path: Path, journal: dict[str, object],
                         *, fault: Callable[[str], None] | None = None,
                         during_site: str | None = None) -> None:
    if path.is_symlink():
        raise ExecutorError("refusing a symbolic-link journal path")
    parent = _safe_journal_parent(path)
    encoded = (json.dumps(journal, indent=2, sort_keys=True, allow_nan=False) +
               "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".kb7-updater-journal.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if fault is not None and during_site is not None:
            fault(during_site)
        os.replace(temporary, path)
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def validate_journal_path(transaction: Transaction, journal_path: Path) -> None:
    _safe_journal_parent(journal_path)
    absolute = journal_path.absolute()
    if transaction.bundle_dir == absolute or transaction.bundle_dir in absolute.parents:
        raise ExecutorError("journal must remain outside the generated bundle")
    for baseline in transaction.baseline_paths:
        try:
            if absolute.resolve() == baseline or os.path.samefile(absolute, baseline):
                raise ExecutorError("journal must not alias a baseline capture")
        except FileNotFoundError:
            continue


class UsbReadBackend:
    """Strict, read-only wrapper around the hardware-validated F6 transport."""

    def __init__(self) -> None:
        self.device = _writer.WriteDevice()

    def identity(self) -> dict[str, str]:
        return _writer.query_loader_identity(self.device)

    def capture(self, *, progress: bool = True) -> bytes:
        return _writer.capture_full_chip(self.device, progress=progress)

    def close(self) -> None:
        self.device.close()


class LockedUsbMutationBackend(UsbReadBackend):
    """Placeholder whose mutation entries are unconditionally unavailable."""

    @staticmethod
    def _locked() -> None:
        raise ExecutionLocked(
            "live firmware-region mutation is disabled in this source revision")

    def set_mode(self, operation) -> None:
        del operation
        self._locked()

    def mutate(self, operation) -> None:
        del operation
        self._locked()

    def poll(self) -> None:
        self._locked()

    def read_range(self, offset: int, length: int) -> bytes:
        return _writer.read_range(self.device, offset, length)


def _two_stable_full_reads(backend, *, progress: bool) -> bytes:
    first = backend.capture(progress=progress)
    second = backend.capture(progress=progress)
    _writer.require_exact_image("two live full-chip reads", first, second)
    return first


def _validate_live_immutable(transaction: Transaction, image: bytes) -> None:
    if len(image) != _planner.FLASH_BYTES:
        raise ExecutorError("live flash capture is not exactly 32 MiB")
    if (image[:_planner.CORE0_START] != transaction.baseline[:_planner.CORE0_START] or
            image[_planner.CORE1_ENVELOPE_END:] !=
            transaction.baseline[_planner.CORE1_ENVELOPE_END:]):
        raise ExecutorError("live image differs in an immutable flash range")


def _boundary_index(transaction: Transaction, image: bytes) -> int | None:
    mutable_hash = _planner.mutable_state_sha256(image)
    candidates = [
        index for index, expected in enumerate(transaction.boundary_mutable_hashes)
        if expected == mutable_hash
    ]
    exact = [
        index for index in candidates
        if expected_boundary_image(transaction, index) == image
    ]
    if len(exact) > 1:
        raise ExecutorError("multiple operation boundaries have the same exact image")
    return exact[0] if exact else None


def classify_observed_image(transaction: Transaction, image: bytes,
                            journal: dict[str, object] | None = None
                            ) -> dict[str, object]:
    if journal is not None:
        validate_journal(transaction, journal)
    _validate_live_immutable(transaction, image)
    boundary = _boundary_index(transaction, image)
    if boundary is not None:
        if boundary == 0:
            classification = "exact_stock"
        elif boundary == len(transaction.operations):
            classification = "exact_target"
        else:
            classification = "exact_intermediate_boundary"
        return {
            "classification": classification,
            "boundary_index": boundary,
            "next_operation": (boundary if boundary < len(transaction.operations)
                               else None),
            "automatic_mutation_authorized": False,
        }

    if journal is not None and journal.get("status") == "intent":
        index = journal["active_operation_index"]
        preimage = expected_boundary_image(transaction, index)
        postimage = bytearray(preimage)
        operation = transaction.operations[index]
        _planner.apply_operation(postimage, operation)
        classification = _planner.classify_reconciliation(
            preimage, image, bytes(postimage), operation)
        return {
            "classification": classification,
            "boundary_index": None,
            "next_operation": None,
            "automatic_mutation_authorized": False,
        }
    return {
        "classification": "spi_recovery_required",
        "boundary_index": None,
        "next_operation": None,
        "automatic_mutation_authorized": False,
    }


def live_preflight(transaction: Transaction, journal_path: Path, *,
                   backend_factory=UsbReadBackend, progress: bool = True
                   ) -> dict[str, object]:
    validate_journal_path(transaction, journal_path)
    if journal_path.exists() or journal_path.is_symlink():
        raise ExecutorError("preflight refuses to replace an existing journal")
    backend = backend_factory()
    try:
        identity = backend.identity()
        observed = _two_stable_full_reads(backend, progress=progress)
        _writer.require_exact_image(
            "live preflight versus planned baseline", transaction.baseline, observed)
        _planner.validate_baseline(observed, transaction.descriptor["source_anchors"])
        bound_identity = _identity_fields(identity, observed)
        journal = boundary_journal(
            transaction, bound_identity, 0, preflight=True)
        write_journal_atomic(journal_path, journal)
        return {
            "classification": "exact_stock",
            "bundle_id": transaction.bundle_id,
            "baseline_sha256": transaction.baseline_sha256,
            "device_path": bound_identity["device_path"],
            "journal": str(journal_path),
            "operation_count": len(transaction.operations),
            "live_mutation_enabled": LIVE_MUTATION_ENABLED,
        }
    finally:
        backend.close()


def live_reconcile(transaction: Transaction, journal_path: Path, *,
                   backend_factory=UsbReadBackend, progress: bool = True
                   ) -> dict[str, object]:
    validate_journal_path(transaction, journal_path)
    journal: dict[str, object] | None
    journal_error: str | None = None
    try:
        journal = load_journal(journal_path)
    except ExecutorError as error:
        journal = None
        journal_error = str(error)
    else:
        # A parsed journal with a stale bundle/source binding is not equivalent
        # to a torn or missing file. Changing implementation between stages
        # must fail closed instead of silently rebinding the transaction.
        validate_journal(transaction, journal)

    backend = backend_factory()
    try:
        identity = backend.identity()
        observed = _two_stable_full_reads(backend, progress=progress)
        _validate_live_immutable(transaction, observed)
        bound_identity = _identity_fields(identity, observed)
        if journal is not None:
            validate_journal(transaction, journal, bound_identity)
        result = classify_observed_image(transaction, observed, journal)
        boundary = result["boundary_index"]
        if boundary is not None:
            repaired = boundary_journal(transaction, bound_identity, boundary)
            write_journal_atomic(journal_path, repaired)
            result["journal_rebuilt"] = journal_error is not None
        else:
            result["journal_rebuilt"] = False
        result.update({
            "bundle_id": transaction.bundle_id,
            "observed_sha256": _planner.sha256(observed),
            "device_path": bound_identity["device_path"],
            "journal_error_before_reconciliation": journal_error,
            "live_mutation_enabled": LIVE_MUTATION_ENABLED,
        })
        return result
    finally:
        backend.close()


def run_one_modeled_operation(transaction: Transaction, operation_index: int,
                              backend, journal_path: Path, *,
                              fault: Callable[[str], None] | None = None
                              ) -> bytes:
    """Exercise one journaled operation with an injected non-live backend.

    This is the state machine used by offline fault tests.  The public CLI does
    not construct a mutation backend, and ``LockedUsbMutationBackend`` refuses
    all mutations while ``LIVE_MUTATION_ENABLED`` remains false.
    """
    if fault is None:
        fault = lambda _site: None
    validate_journal_path(transaction, journal_path)
    if not 0 <= operation_index < len(transaction.operations):
        raise ExecutorError("operation index is outside the transaction")
    current_journal = load_journal(journal_path)
    validate_journal(transaction, current_journal)
    if (current_journal["status"] not in {"preflight_verified", "boundary_verified"} or
            current_journal["boundary_index"] != operation_index):
        raise ExecutorError("journal is not at the requested operation boundary")

    preimage = expected_boundary_image(transaction, operation_index)
    postimage = bytearray(preimage)
    operation = transaction.operations[operation_index]
    _planner.apply_operation(postimage, operation)
    intent_durable = False
    try:
        reported_identity = backend.identity()
        observed_preimage = _two_stable_full_reads(backend, progress=False)
        _writer.require_exact_image(
            "operation preimage after reconciliation", preimage, observed_preimage)
        identity = _identity_fields(reported_identity, observed_preimage)
        validate_journal(transaction, current_journal, identity)
        intent = intent_journal(transaction, identity, operation_index)
        fault("before_intent")
        write_journal_atomic(
            journal_path, intent, fault=fault, during_site="during_intent")
        intent_durable = True
        fault("after_intent")
        fault("during_f6_18")
        backend.set_mode(operation)
        fault("during_cbw")
        fault("during_data_or_erase")
        backend.mutate(operation)
        fault("before_csw")
        fault("bad_csw")
        fault("during_poll")
        backend.poll()
        fault("poll_timeout")
        fault("before_readback")
        first = backend.capture(progress=False)
        fault("short_readback")
        second = backend.capture(progress=False)
        _writer.require_exact_image("operation full-chip readback stability", first, second)
        _writer.require_exact_image("operation exact postimage", bytes(postimage), first)
        fault("after_compare")
        verified = boundary_journal(transaction, identity, operation_index + 1)
        write_journal_atomic(
            journal_path, verified, fault=fault,
            during_site="during_verified_journal")
        fault("after_verified_journal")
        return bytes(postimage)
    except BaseException as error:
        if intent_durable:
            raise ReconciliationRequired(
                f"operation {operation_index} stopped after durable intent: {error}") from error
        raise


def _arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--baseline-a", required=True, type=Path)
    parser.add_argument("--baseline-b", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    _arguments(commands.add_parser(
        "preflight", help="read and bind an exact stock device; no mutation"))
    _arguments(commands.add_parser(
        "reconcile", help="classify two stable full reads; no mutation"))
    arguments = parser.parse_args()
    try:
        transaction = load_transaction(
            arguments.bundle, arguments.baseline_a, arguments.baseline_b)
        if arguments.command == "preflight":
            result = live_preflight(transaction, arguments.journal)
        else:
            result = live_reconcile(transaction, arguments.journal)
        print(json.dumps(result, indent=2, sort_keys=True))
        if result.get("classification") == "spi_recovery_required":
            return 3
        if str(result.get("classification", "")).startswith("modeled_partial_"):
            return 4
        return 0
    except (ExecutorError, SafetyError, _planner.PlanError, OSError,
            RuntimeError, ValueError) as error:
        print(f"updater executor error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
