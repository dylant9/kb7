#!/usr/bin/env python3
"""Fixed loader-reentry proof installer/restorer; dry-run by default.

This is intentionally separate from ``kb7-updater-executor.py``.  It accepts
only a campaign independently rederived by ``kb7-loader-reentry-campaign.py``;
there is no offset, payload, CDB, operation-index, retry, or general firmware
execution option.  One committed ``step`` executes exactly one internally
selected canonical operation in the Core-0 envelope or the one fixed Core-1
barrier sector.

The exact owner-baseline campaign and reviewed implementation hashes are
pinned below.  Its fixed proof campaign is live only for the reviewed owner
artifacts; the general paired-firmware executor remains independently
hard-locked.
"""

from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import ctypes as ct
from dataclasses import dataclass
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import MappingProxyType
from typing import Callable


TOOL_DIRECTORY = Path(__file__).resolve().parent
CHECKOUT_ROOT = TOOL_DIRECTORY.parents[1]


def _load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load required module: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


_campaign = _load_module(
    "kb7_loader_reentry_campaign_for_executor",
    TOOL_DIRECTORY / "kb7-loader-reentry-campaign.py")
_planner = _campaign._planner
_writer = _load_module(
    "kb7_isp_writer_for_loader_reentry_executor",
    TOOL_DIRECTORY / "kb7-isp-write2.py")

SafetyError = _writer.SafetyError
PlanError = _planner.PlanError

JOURNAL_SCHEMA = "kb7-loader-reentry-proof-journal-v1"
LIVE_READ_ONLY_PREFLIGHT_ENABLED = False
LIVE_PROOF_CAMPAIGN_ENABLED = False
EXPECTED_CAMPAIGN_ID = (
    "3fa076a69bb04ab2ef11c9369d80976e293d1d57a52ddeb63f9d8d71b004d82f")
EXPECTED_IMPLEMENTATION_HASHES: dict[str, str] = {
    "campaign_source_sha256":
        "085dd0c2087e258d880824f657e37ecde08f4fd05234ab14d948af245d8de765",
    "planner_source_sha256":
        "618bed76c236390c8203ef5395db2317dfce9cce620035bda05231fc05727d0a",
    "verifier_source_sha256":
        "9b19d393cf64c66168e08de2f3d4fe352a85a2fd69545e374dee0fa015dea338",
    "writer_source_sha256":
        "f706cb355297e4b010fd49f10a1c0e68834d73e99a33005780046ced4e1dc6e5",
}
EXPECTED_POLICY_SHA256 = (
    "2f2e46ae5f9460c0f37100f111fe528e6649dd806475938e09351ed0b5db510c")
EXPECTED_EXECUTOR_DESCRIPTOR_SHA256 = "ef17000a9941409fb0c463e92b4cbb6317523ead3b831492f6b96224a41249be"

PREFLIGHT_STARTED = "preflight_started"
BOUNDARY_VERIFIED = "boundary_verified"
INTENT = "intent"
PROOF_INSTALLED = "proof_installed"
REENTRY_STARTED = "reentry_started"
RESTORE_READY = "restore_ready"
COMPLETE = "complete"
FINALIZE_STARTED = "finalize_started"

JOURNAL_KEYS = {
    "schema", "status", "campaign_id", "baseline_sha256",
    "proof_full_sha256", "implementation_sha256", "operation_count",
    "executor_source_sha256",
    "install_operation_count", "boundary_index", "active_operation_index",
    "active_operation_sha256", "pre_full_sha256", "post_full_sha256",
    "last_observed_sha256", "device_path", "usb_bus_number",
    "initial_usb_address", "current_usb_address", "identify_hex",
    "descriptor_sha256", "loader_fingerprint_sha256",
    "loader_window_sha256", "manifest_sha256",
}


class ExecutorError(SafetyError):
    """Fixed-campaign validation or state error."""


class ExecutionLocked(ExecutorError):
    """The exact owner campaign has not been reviewed and enabled."""


class StateInspectionRequired(ExecutorError):
    """An atomic local-state outcome must be inspected without USB."""


class ReadOnlyPreflightStopped(ExecutorError):
    """A read-only preflight consumed this powered USB session."""

    def __init__(self, phase: str, cause: BaseException) -> None:
        self.phase = phase
        self.root_cause = cause
        detail = " ".join(str(cause).split()) or "no exception detail"
        if len(detail) > 240:
            detail = detail[:237] + "..."
        super().__init__(
            f"phase={phase}; cause={type(cause).__name__}: {detail}")


class ReadOnlyPreflightVerificationStopped(ReadOnlyPreflightStopped):
    """Read-only USB evidence did not establish the exact stock image."""


class RecoveryRequired(ExecutorError):
    """The campaign is consumed; issue no further USB command."""


@dataclass(frozen=True)
class Transaction:
    campaign: object
    campaign_dir: Path
    baseline_paths: tuple[Path, Path]
    proof_elf: Path

    @property
    def descriptor(self) -> dict[str, object]:
        return self.campaign.descriptor

    @property
    def operations(self) -> tuple[object, ...]:
        return self.campaign.operations

    @property
    def install_count(self) -> int:
        return self.campaign.install_operation_count

    @property
    def campaign_id(self) -> str:
        return str(self.descriptor["campaign_id"])


def _source_sha256(path: str | os.PathLike[str]) -> str:
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def implementation_hashes() -> dict[str, str]:
    return {
        "campaign_source_sha256": _source_sha256(_campaign.__file__),
        "planner_source_sha256": _source_sha256(_planner.__file__),
        "writer_source_sha256": _source_sha256(_writer.__file__),
        "verifier_source_sha256": _source_sha256(_writer._verify.__file__),
    }


def _executor_descriptor_sha256() -> str:
    """Hash this source with only its reviewed self-pin value normalized."""
    source = Path(__file__).read_text(encoding="utf-8")
    prefix = 'EXPECTED_EXECUTOR_DESCRIPTOR_SHA256 = "'
    lines = source.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines)
               if line.startswith(prefix)]
    if len(matches) != 1:
        raise ExecutionLocked("executor self-pin assignment is not canonical")
    ending = "\n" if lines[matches[0]].endswith("\n") else ""
    lines[matches[0]] = prefix + "<reviewed-self-pin>\"" + ending
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


# Bind the bytes that supplied this process's executing imports. A later disk
# edit cannot silently become the identity written by the already-running
# process; live authorization also checks that disk and import-time identities
# still agree.
EXECUTOR_SOURCE_SHA256 = _source_sha256(__file__)
IMPLEMENTATION_HASHES = MappingProxyType(implementation_hashes())


def policy_descriptor() -> dict[str, object]:
    return {
        "schema": JOURNAL_SCHEMA,
        "domain": "fixed V1.22 proof Core0 install and exact stock restore",
        "mutation_ranges": [
            "Core0 envelope [0x00011000,0x00021000)",
            "one campaign-bound Core1 barrier sector",
        ],
        "one_operation_per_cli_invocation": True,
        "durable_terminal_intent_before_backend_or_usb": True,
        "two_exact_full_chip_reads_before_and_after": True,
        "strict_close_before_authorizing_publication": True,
        "reattach_not_found_or_busy_accepted_only_if_kernel_driver_is_active":
            True,
        "automatic_retry": False,
        "ordinary_intent_reconciliation": False,
        "read_only_preflight_transport_or_close_anomaly": (
            "no_flash_mutation_power_cycle_before_new_journal"),
        "read_only_preflight_image_verification_anomaly": (
            "external_spi_verify_no_automatic_write"),
        "post_intent_transport_or_verification_anomaly": (
            "external_spi_no_further_usb"),
        "proof_validation": {
            "exact_proof_full_image": True,
            "same_usb_topology": True,
            "new_usb_device_address": True,
            "cause_of_reenumeration_is_operator_evidence": True,
        },
        "finalization": "exact full baseline then clear state",
        "read_only_preflight_diagnostic_authorized": False,
        "fixed_proof_hardware_test_authorized": False,
        "authorized_campaign_id": EXPECTED_CAMPAIGN_ID,
        "authorization_scope": (
            "paused pending exact short-chunk USB read-reliability evidence"),
        "usb_read_reliability_gate": (
            "fixed baseline-aware 512/1024/2048/4096-byte sweep required"),
        "generic_executor_live_mutation_enabled": False,
    }


def _policy_sha256() -> str:
    return _planner.canonical_sha256(policy_descriptor())


def _implementation_sha256() -> str:
    return _planner.canonical_sha256(dict(IMPLEMENTATION_HASHES))


def load_transaction(campaign_dir: Path, baseline_a: Path, baseline_b: Path,
                     proof_elf: Path, prefix: str = "arm-none-eabi-",
                     **testing: object) -> Transaction:
    campaign = _campaign.load_campaign(
        campaign_dir, baseline_a, baseline_b, proof_elf, prefix, **testing)
    return Transaction(
        campaign=campaign,
        campaign_dir=campaign_dir.resolve(strict=True),
        baseline_paths=(baseline_a.resolve(strict=True),
                        baseline_b.resolve(strict=True)),
        proof_elf=proof_elf.resolve(strict=True),
    )


def _require_reviewed_authorization(transaction: Transaction) -> None:
    if not EXPECTED_CAMPAIGN_ID or transaction.campaign_id != EXPECTED_CAMPAIGN_ID:
        raise ExecutionLocked("campaign identifier is not the reviewed live pin")
    current = implementation_hashes()
    if (not EXPECTED_IMPLEMENTATION_HASHES or
            current != EXPECTED_IMPLEMENTATION_HASHES or
            current != dict(IMPLEMENTATION_HASHES)):
        raise ExecutionLocked("reviewed implementation source hashes do not match")
    if (_source_sha256(__file__) != EXECUTOR_SOURCE_SHA256 or
            not EXPECTED_EXECUTOR_DESCRIPTOR_SHA256 or
            _executor_descriptor_sha256() !=
            EXPECTED_EXECUTOR_DESCRIPTOR_SHA256):
        raise ExecutionLocked("reviewed executor source descriptor does not match")
    if not EXPECTED_POLICY_SHA256 or _policy_sha256() != EXPECTED_POLICY_SHA256:
        raise ExecutionLocked("reviewed executor policy hash does not match")
    # Preserve the general firmware executor's independent hard lock.
    general_source = (TOOL_DIRECTORY / "kb7-updater-executor.py").read_text(
        encoding="utf-8")
    assignments = []
    for node in ast.walk(ast.parse(general_source)):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            if any(isinstance(target, ast.Name) and
                   target.id == "LIVE_MUTATION_ENABLED" for target in targets):
                assignments.append(node.value)
    if (len(assignments) != 1 or
            not isinstance(assignments[0], ast.Constant) or
            assignments[0].value is not False):
        raise ExecutionLocked("general firmware executor is not mutation-locked")


def require_read_only_preflight_authorization(transaction: Transaction) -> None:
    if not LIVE_READ_ONLY_PREFLIGHT_ENABLED:
        raise ExecutionLocked(
            "fixed proof read-only preflight is hard-disabled in this source revision")
    _require_reviewed_authorization(transaction)


def require_live_authorization(transaction: Transaction) -> None:
    if not LIVE_PROOF_CAMPAIGN_ENABLED:
        raise ExecutionLocked(
            "fixed proof campaign mutation is hard-disabled in this source revision")
    _require_reviewed_authorization(transaction)


def expected_boundary_image(transaction: Transaction, index: int) -> bytes:
    if not 0 <= index <= len(transaction.operations):
        raise ExecutorError("boundary index is outside the campaign")
    image = bytearray(transaction.campaign.baseline)
    for operation in transaction.operations[:index]:
        _planner.apply_operation(image, operation)
    return bytes(image)


def _operation_sha256(transaction: Transaction, index: int) -> str:
    return _planner.canonical_sha256(transaction.descriptor["operations"][index])


def _identity(device) -> dict[str, object]:
    identity = _writer.query_loader_identity(device)
    bus = getattr(device, "bus_number", None)
    address = getattr(device, "device_address", None)
    if type(bus) is not int or not 0 <= bus <= 255:
        raise ExecutorError("USB bus number is unavailable")
    if type(address) is not int or not 1 <= address <= 255:
        raise ExecutorError("USB device address is unavailable")
    return {**identity, "usb_bus_number": bus, "usb_device_address": address}


def _identity_window(image: bytes) -> dict[str, str]:
    return {
        "loader_window_sha256": _planner.sha256(image[
            _planner.LOADER_START:_planner.MANIFEST_START]),
        "manifest_sha256": _planner.sha256(image[
            _planner.MANIFEST_START:_planner.CORE0_START]),
    }


def _unbound_identity(transaction: Transaction) -> dict[str, object]:
    windows = _identity_window(transaction.campaign.baseline)
    return {
        "device_path": "unbound-preflight",
        "usb_bus_number": -1,
        "initial_usb_address": -1,
        "current_usb_address": -1,
        "identify_hex": _writer.LOADER_IDENT.hex(),
        "descriptor_sha256": "0" * 64,
        "loader_fingerprint_sha256": "0" * 64,
        **windows,
    }


def _bound_identity(raw: dict[str, object], image: bytes,
                    *, initial_address: int | None = None) -> dict[str, object]:
    required = {
        "device_path", "identify_hex", "descriptor_sha256",
        "loader_fingerprint_sha256", "usb_bus_number", "usb_device_address",
    }
    if set(raw) != required:
        raise ExecutorError("loader identity has missing or unknown fields")
    if not isinstance(raw["device_path"], str) or not raw["device_path"]:
        raise ExecutorError("loader topology path is malformed")
    bus = raw["usb_bus_number"]
    address = raw["usb_device_address"]
    if type(bus) is not int or type(address) is not int:
        raise ExecutorError("loader bus/address identity is malformed")
    if not 0 <= bus <= 255 or not 1 <= address <= 255:
        raise ExecutorError("loader bus/address identity is out of range")
    topology = raw["device_path"].split("-", 1)
    if (len(topology) != 2 or topology[0] != str(bus) or
            not topology[1] or any(
                not component.isdigit() for component in topology[1].split("."))):
        raise ExecutorError("loader topology path does not match its bus")
    if raw["identify_hex"] != _writer.LOADER_IDENT.hex():
        raise ExecutorError("loader identify bytes are not canonical")
    for key in ("descriptor_sha256", "loader_fingerprint_sha256"):
        value = raw[key]
        if not isinstance(value, str) or len(value) != 64:
            raise ExecutorError(f"loader {key} is malformed")
        try:
            decoded = bytes.fromhex(value)
        except ValueError as error:
            raise ExecutorError(f"loader {key} is not hexadecimal") from error
        if len(decoded) != 32 or value != value.lower():
            raise ExecutorError(f"loader {key} is not canonical hexadecimal")
    return {
        "device_path": raw["device_path"],
        "usb_bus_number": bus,
        "initial_usb_address": address if initial_address is None else initial_address,
        "current_usb_address": address,
        "identify_hex": raw["identify_hex"],
        "descriptor_sha256": raw["descriptor_sha256"],
        "loader_fingerprint_sha256": raw["loader_fingerprint_sha256"],
        **_identity_window(image),
    }


def _journal_common(transaction: Transaction, identity: dict[str, object],
                    boundary: int) -> dict[str, object]:
    return {
        "schema": JOURNAL_SCHEMA,
        "status": BOUNDARY_VERIFIED,
        "campaign_id": transaction.campaign_id,
        "baseline_sha256": _planner.sha256(transaction.campaign.baseline),
        "proof_full_sha256": _planner.sha256(transaction.campaign.proof_image),
        "implementation_sha256": _implementation_sha256(),
        "executor_source_sha256": EXECUTOR_SOURCE_SHA256,
        "operation_count": len(transaction.operations),
        "install_operation_count": transaction.install_count,
        "boundary_index": boundary,
        "active_operation_index": None,
        "active_operation_sha256": None,
        "pre_full_sha256": None,
        "post_full_sha256": None,
        "last_observed_sha256": _planner.sha256(
            expected_boundary_image(transaction, boundary)),
        **identity,
    }


def boundary_journal(transaction: Transaction, identity: dict[str, object],
                     boundary: int, *, status: str | None = None
                     ) -> dict[str, object]:
    journal = _journal_common(transaction, identity, boundary)
    if status is not None:
        journal["status"] = status
    return journal


def preflight_started_journal(transaction: Transaction) -> dict[str, object]:
    return boundary_journal(
        transaction, _unbound_identity(transaction), 0,
        status=PREFLIGHT_STARTED)


def intent_journal(transaction: Transaction, source: dict[str, object],
                   index: int) -> dict[str, object]:
    if not 0 <= index < len(transaction.operations):
        raise ExecutorError("cannot create intent outside the campaign")
    result = dict(source)
    result.update({
        "status": INTENT,
        "boundary_index": index,
        "active_operation_index": index,
        "active_operation_sha256": _operation_sha256(transaction, index),
        "pre_full_sha256": transaction.descriptor["operations"][index][
            "pre_full_sha256"],
        "post_full_sha256": transaction.descriptor["operations"][index][
            "post_full_sha256"],
        "last_observed_sha256": transaction.descriptor["operations"][index][
            "pre_full_sha256"],
    })
    return result


def _identity_from_journal(journal: dict[str, object]) -> dict[str, object]:
    return {key: journal[key] for key in (
        "device_path", "usb_bus_number", "initial_usb_address",
        "current_usb_address", "identify_hex", "descriptor_sha256",
        "loader_fingerprint_sha256", "loader_window_sha256", "manifest_sha256")}


def validate_journal(transaction: Transaction, journal: dict[str, object]) -> None:
    if set(journal) != JOURNAL_KEYS or journal.get("schema") != JOURNAL_SCHEMA:
        raise ExecutorError("journal schema is not the fixed proof domain")
    expected_common = {
        "campaign_id": transaction.campaign_id,
        "baseline_sha256": _planner.sha256(transaction.campaign.baseline),
        "proof_full_sha256": _planner.sha256(transaction.campaign.proof_image),
        "implementation_sha256": _implementation_sha256(),
        "executor_source_sha256": EXECUTOR_SOURCE_SHA256,
        "operation_count": len(transaction.operations),
        "install_operation_count": transaction.install_count,
    }
    for key, expected in expected_common.items():
        if journal.get(key) != expected:
            raise ExecutorError(f"journal {key} does not match this campaign")
    boundary = journal.get("boundary_index")
    if type(boundary) is not int or not 0 <= boundary <= len(transaction.operations):
        raise ExecutorError("journal boundary is invalid")
    for key in ("baseline_sha256", "proof_full_sha256", "implementation_sha256",
                "executor_source_sha256", "descriptor_sha256", "loader_fingerprint_sha256",
                "loader_window_sha256", "manifest_sha256"):
        value = journal.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise ExecutorError(f"journal {key} is malformed")
        try:
            decoded = bytes.fromhex(value)
        except ValueError as error:
            raise ExecutorError(f"journal {key} is not hexadecimal") from error
        if len(decoded) != 32 or value != value.lower():
            raise ExecutorError(f"journal {key} is not canonical hexadecimal")
    for key in ("usb_bus_number", "initial_usb_address", "current_usb_address"):
        if type(journal.get(key)) is not int:
            raise ExecutorError(f"journal {key} is malformed")
    status = journal.get("status")
    if status == PREFLIGHT_STARTED:
        if journal != preflight_started_journal(transaction):
            raise ExecutorError("preflight-started journal is not canonical")
        return
    if not 0 <= journal["usb_bus_number"] <= 255 or not \
            1 <= journal["initial_usb_address"] <= 255 or not \
            1 <= journal["current_usb_address"] <= 255:
        raise ExecutorError("bound journal USB identity is invalid")
    if journal["identify_hex"] != _writer.LOADER_IDENT.hex():
        raise ExecutorError("bound journal identify bytes are invalid")
    topology = (journal["device_path"].split("-", 1)
                if isinstance(journal["device_path"], str) else [])
    if (len(topology) != 2 or
            topology[0] != str(journal["usb_bus_number"]) or
            not topology[1] or any(
                not component.isdigit() for component in topology[1].split("."))):
        raise ExecutorError("bound journal topology path is invalid")
    expected_windows = _identity_window(transaction.campaign.baseline)
    if any(journal[key] != value for key, value in expected_windows.items()):
        raise ExecutorError("bound journal loader/manifest window is invalid")
    if status == INTENT:
        index = journal["active_operation_index"]
        if index != boundary or type(index) is not int or not 0 <= index < len(
                transaction.operations):
            raise ExecutorError("intent operation index is invalid")
        expected = transaction.descriptor["operations"][index]
        if (journal["active_operation_sha256"] !=
                _operation_sha256(transaction, index) or
                journal["pre_full_sha256"] != expected["pre_full_sha256"] or
                journal["post_full_sha256"] != expected["post_full_sha256"] or
                journal["last_observed_sha256"] != expected["pre_full_sha256"]):
            raise ExecutorError("intent journal is not canonical")
        if (index < transaction.install_count) != (
                journal["current_usb_address"] ==
                journal["initial_usb_address"]):
            raise ExecutorError("intent USB enumeration phase is inconsistent")
        return
    if any(journal[key] is not None for key in (
            "active_operation_index", "active_operation_sha256",
            "pre_full_sha256", "post_full_sha256")):
        raise ExecutorError("stable journal contains active operation fields")
    if journal["last_observed_sha256"] != _planner.sha256(
            expected_boundary_image(transaction, boundary)):
        raise ExecutorError("stable journal boundary hash is stale")
    if status == BOUNDARY_VERIFIED:
        if boundary == transaction.install_count or boundary == len(
                transaction.operations):
            raise ExecutorError("special boundary has a generic status")
        if (boundary < transaction.install_count) != (
                journal["current_usb_address"] ==
                journal["initial_usb_address"]):
            raise ExecutorError("boundary USB enumeration phase is inconsistent")
    elif status in (PROOF_INSTALLED, REENTRY_STARTED, RESTORE_READY):
        if boundary != transaction.install_count:
            raise ExecutorError("proof transition state has the wrong boundary")
        same_address = (journal["current_usb_address"] ==
                        journal["initial_usb_address"])
        if (status == RESTORE_READY) == same_address:
            raise ExecutorError("proof transition USB enumeration is inconsistent")
    elif status in (COMPLETE, FINALIZE_STARTED):
        if boundary != len(transaction.operations):
            raise ExecutorError("final state has the wrong boundary")
        if journal["current_usb_address"] == journal["initial_usb_address"]:
            raise ExecutorError("final state lacks the proof re-enumeration")
    else:
        raise ExecutorError("journal status is invalid")


def _safe_parent(path: Path) -> Path:
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or parent.is_symlink():
        raise ExecutorError("journal parent is not a regular directory")
    return parent.resolve(strict=True)


def validate_journal_path(transaction: Transaction, path: Path) -> None:
    parent = _safe_parent(path)
    resolved = parent / path.name
    if resolved == CHECKOUT_ROOT or CHECKOUT_ROOT in resolved.parents:
        raise ExecutorError("proof journal must remain outside the checkout")
    inputs = (*transaction.baseline_paths, transaction.campaign_dir,
              transaction.proof_elf)
    for source in inputs:
        if resolved == source or source in resolved.parents:
            raise ExecutorError("journal must not alias a campaign input")


def journal_lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


@contextmanager
def journal_lock(transaction: Transaction, journal_path: Path):
    validate_journal_path(transaction, journal_path)
    lock_path = journal_lock_path(journal_path)
    validate_journal_path(transaction, lock_path)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or \
                info.st_size != 0:
            raise ExecutorError("journal lock is not a private empty regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ExecutorError("another proof executor holds this journal lock") from error
        yield
    finally:
        os.close(fd)


def _duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ExecutorError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ExecutorError(f"non-finite JSON value is forbidden: {value}")


def write_journal_atomic(path: Path, journal: dict[str, object], *,
                         require_absent: bool = False,
                         fault: Callable[[str], None] | None = None) -> None:
    parent = _safe_parent(path)
    if path.is_symlink():
        raise ExecutorError("refusing a symbolic-link journal")
    if require_absent and path.exists():
        raise ExecutorError("refusing to replace existing proof state")
    data = (json.dumps(journal, indent=2, sort_keys=True, allow_nan=False) +
            "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(
        prefix=".kb7-loader-reentry-journal.", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if fault is not None:
            fault("before_replace")
        os.replace(temporary, path)
        if fault is not None:
            fault("after_replace")
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_journal(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ExecutorError("cannot safely open proof journal") from error
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or
                stat.S_IMODE(before.st_mode) != 0o600 or
                before.st_size > 16384):
            raise ExecutorError(
                "proof journal is not a private small regular file")
        raw = os.read(fd, 16385)
        after = os.fstat(fd)
        if before.st_ino != after.st_ino or before.st_size != after.st_size or \
                len(raw) != before.st_size:
            raise ExecutorError("proof journal changed while being read")
    finally:
        os.close(fd)
    try:
        value = json.loads(
            raw, object_pairs_hook=_duplicate_object,
            parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ExecutorError("proof journal is not strict JSON") from error
    if not isinstance(value, dict):
        raise ExecutorError("proof journal is not an object")
    return value


def _visible_state(transaction: Transaction, path: Path,
                   source: dict[str, object], target: dict[str, object]) -> str:
    try:
        visible = load_journal(path)
        validate_journal(transaction, visible)
    except BaseException as error:
        raise StateInspectionRequired(
            "journal visibility is ambiguous; inspect locally before any USB action") from error
    if visible == target:
        return "target"
    if visible == source:
        return "source"
    raise StateInspectionRequired(
        "journal exposes an unexpected valid state; inspect locally")


def publish_transition(transaction: Transaction, path: Path,
                       source: dict[str, object], target: dict[str, object], *,
                       fault: Callable[[str], None] | None = None) -> str:
    validate_journal(transaction, source)
    validate_journal(transaction, target)
    try:
        write_journal_atomic(path, target, fault=fault)
    except BaseException:
        visible = _visible_state(transaction, path, source, target)
        return ("target_visible_after_error" if visible == "target" else
                "source_retained_after_error")
    outcome = _visible_state(transaction, path, source, target)
    if outcome != "target":
        raise StateInspectionRequired("journal transition did not publish its target")
    return "target_confirmed"


def publish_initial(transaction: Transaction, path: Path,
                    target: dict[str, object], *,
                    fault: Callable[[str], None] | None = None) -> str:
    validate_journal(transaction, target)
    if path.exists() or path.is_symlink():
        raise ExecutorError("preflight refuses existing proof state")
    try:
        write_journal_atomic(path, target, require_absent=True, fault=fault)
    except BaseException as error:
        if not path.exists():
            raise StateInspectionRequired(
                "initial publication failed with journal absent; no USB was opened") from error
        try:
            visible = load_journal(path)
            validate_journal(transaction, visible)
        except BaseException as inspect_error:
            raise StateInspectionRequired(
                "initial journal visibility is ambiguous; no USB was opened") from inspect_error
        if visible == target:
            raise StateInspectionRequired(
                "preflight-started became visible after a publication error; no USB was opened")
        raise StateInspectionRequired("initial publication exposed unexpected state")
    visible = load_journal(path)
    validate_journal(transaction, visible)
    if visible != target:
        raise StateInspectionRequired("preflight-started readback is not exact")
    return "target"


def clear_journal(path: Path) -> None:
    if path.is_symlink():
        raise ExecutorError("refusing to clear a symbolic-link journal")
    parent = _safe_parent(path)
    os.unlink(path)
    directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _journal_exactly_absent(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError as error:
        raise StateInspectionRequired(
            "journal absence cannot be inspected exactly") from error
    return False


class _ProofUsbEnumerationMixin:
    """Add local bus/address evidence without changing the shared verifier."""

    def __init__(self) -> None:
        super().__init__()
        api = _writer._verify.lib
        api.libusb_get_device_address.argtypes = [ct.c_void_p]
        api.libusb_get_device_address.restype = ct.c_uint8
        usb_device = api.libusb_get_device(self.h)
        self.bus_number = int(self.device_path.split("-", 1)[0])
        self.device_address = int(api.libusb_get_device_address(usb_device))


_LIBUSB_ERROR_NAMES = {
    -1: "LIBUSB_ERROR_IO",
    -2: "LIBUSB_ERROR_INVALID_PARAM",
    -3: "LIBUSB_ERROR_ACCESS",
    -4: "LIBUSB_ERROR_NO_DEVICE",
    -5: "LIBUSB_ERROR_NOT_FOUND",
    -6: "LIBUSB_ERROR_BUSY",
    -7: "LIBUSB_ERROR_TIMEOUT",
    -8: "LIBUSB_ERROR_OVERFLOW",
    -9: "LIBUSB_ERROR_PIPE",
    -10: "LIBUSB_ERROR_INTERRUPTED",
    -11: "LIBUSB_ERROR_NO_MEM",
    -12: "LIBUSB_ERROR_NOT_SUPPORTED",
    -99: "LIBUSB_ERROR_OTHER",
}


def _libusb_result(result: int) -> str:
    return f"{result} {_LIBUSB_ERROR_NAMES.get(result, 'LIBUSB_ERROR_UNKNOWN')}"


def _strict_close_proof_device(device) -> None:
    """Close a clean proof BOT session and verify host-driver ownership.

    A nonzero attach result is not by itself a failure: on Linux, libusb may
    report BUSY because a kernel driver has already claimed the released
    interface.  Accept that result only when a direct host-side query reports
    that a kernel driver is active.  No retry, reset, halt clear or later CDB is
    issued here.
    """
    api = _writer._verify.lib
    first_error: BaseException | None = None
    release_succeeded = False
    try:
        result = api.libusb_release_interface(device.h, device.iface)
        if result != 0:
            first_error = RuntimeError(
                "libusb_release_interface failed "
                f"({_libusb_result(result)})")
        else:
            release_succeeded = True
        if release_succeeded and device.reattach:
            result = api.libusb_attach_kernel_driver(device.h, device.iface)
            if result != 0:
                try:
                    active = api.libusb_kernel_driver_active(
                        device.h, device.iface)
                except BaseException as error:
                    first_error = RuntimeError(
                        "libusb_attach_kernel_driver failed "
                        f"({_libusb_result(result)}); "
                        "kernel-driver-active check raised "
                        f"{type(error).__name__}: {error}")
                else:
                    if result not in (-5, -6) or active != 1:
                        first_error = RuntimeError(
                            "libusb_attach_kernel_driver failed "
                            f"({_libusb_result(result)}); "
                            "kernel-driver-active check returned "
                            f"{_libusb_result(active) if active < 0 else active}")
    except BaseException as error:
        first_error = error
    try:
        api.libusb_close(device.h)
    except BaseException as error:
        if first_error is None:
            first_error = RuntimeError(
                f"libusb_close raised {type(error).__name__}: {error}")
    try:
        api.libusb_exit(device.ctx)
    except BaseException as error:
        if first_error is None:
            first_error = RuntimeError(
                f"libusb_exit raised {type(error).__name__}: {error}")
    if first_error is not None:
        raise first_error


class _ProofStrictCloseMixin:
    def close(self) -> None:
        _strict_close_proof_device(self)


class FixedProofStrictWriteDevice(
        _ProofUsbEnumerationMixin, _ProofStrictCloseMixin,
        _writer.WriteDevice):
    """Strict mutation BOT transport; no endpoint recovery on anomaly."""


class FixedProofNoRecoveryReadOnlyDevice(
        _ProofUsbEnumerationMixin, _ProofStrictCloseMixin,
        _writer._verify.Device):
    """Read-only BOT transport; no endpoint recovery on anomaly."""

    clear_halt_on_error = False


class FixedProofMutationBackend:
    def __init__(self, transaction: Transaction, index: int, *,
                 device_factory=FixedProofStrictWriteDevice) -> None:
        if not 0 <= index < len(transaction.operations):
            raise ExecutorError("operation index is outside the fixed campaign")
        self._transaction = transaction
        self._index = index
        self._operation = transaction.operations[index]
        trace = transaction.descriptor["operations"][index]
        if trace["offset"] != f"0x{self._operation.offset:08x}" or \
                trace["action"] != self._operation.action:
            raise ExecutorError("operation descriptor is not canonical")
        self._device = device_factory()
        self._phase = "opened"

    def identity(self) -> dict[str, object]:
        if self._phase not in ("opened", "ready"):
            raise ExecutorError("identity unavailable during mutation")
        return _identity(self._device)

    def capture(self, *, progress: bool = True) -> bytes:
        if self._phase not in ("opened", "ready"):
            raise ExecutorError("capture unavailable during mutation")
        return _writer.capture_full_chip(self._device, progress=progress)

    def execute(self) -> None:
        if self._phase != "opened":
            raise ExecutorError("mutation backend phase is invalid")
        operation = self._operation
        trace = self._transaction.descriptor["operations"][self._index]
        try:
            mode = _writer.set_address_mode_for_range(
                self._device, operation.offset, operation.length)
            if mode != _writer.SUB_EX4B:
                raise ExecutorError("Core-0 operation did not select F6 18")
            if operation.action == "program":
                cdb = _writer.cdb_program(operation.offset, _planner.BLOCK_BYTES)
                if cdb.hex() != trace["cdb_hex"] or operation.payload is None or \
                        _planner.sha256(operation.payload) != trace["payload_sha256"]:
                    raise ExecutorError("internal program command does not match campaign")
                self._device.program(cdb, operation.payload)
            else:
                cdb = _writer.cdb_erase(operation.offset)
                if cdb.hex() != trace["cdb_hex"]:
                    raise ExecutorError("internal erase command does not match campaign")
                self._device.cmd(cdb)
            _writer.poll_ready(self._device)
            self._phase = "ready"
        except BaseException:
            self._phase = "failed"
            raise

    def close(self) -> None:
        if self._phase != "closed":
            try:
                self._device.close()
            finally:
                self._phase = "closed"


class FixedProofReadOnlyBackend:
    def __init__(self, _transaction: Transaction, *,
                 device_factory=FixedProofNoRecoveryReadOnlyDevice) -> None:
        self._device = device_factory()
        self._closed = False

    def identity(self) -> dict[str, object]:
        if self._closed:
            raise ExecutorError("identity unavailable after close")
        return _identity(self._device)

    def capture(self, *, progress: bool = True) -> bytes:
        if self._closed:
            raise ExecutorError("capture unavailable after close")
        return _writer.capture_full_chip(self._device, progress=progress)

    def close(self) -> None:
        if not self._closed:
            try:
                self._device.close()
            finally:
                self._closed = True


def _two_reads(backend, *, progress: bool) -> bytes:
    first = backend.capture(progress=progress)
    second = backend.capture(progress=progress)
    _writer.require_exact_image("two exact full-chip reads", first, second)
    return first


def _require_image(transaction: Transaction, expected: bytes, observed: bytes,
                   label: str) -> None:
    _writer.require_exact_image(label, expected, observed)
    if len(observed) != _planner.FLASH_BYTES:
        raise RecoveryRequired(f"{label} is not an exact full-chip image")
    slices = {
        "header": observed[_planner.HEADER_START:_planner.LOADER_START],
        "loader": observed[_planner.LOADER_START:_planner.MANIFEST_START],
        "manifest": observed[_planner.MANIFEST_START:_planner.CORE0_START],
    }
    anchors = transaction.descriptor["source_anchors"]
    for name, data in slices.items():
        if _planner.sha256(data) != anchors[name]:
            raise RecoveryRequired(f"{label} changed the stock {name}")
    _planner.parse_manifest(slices["manifest"])
    if _identity_window(observed) != _identity_window(expected):
        raise RecoveryRequired(f"{label} changed loader or manifest identity")


def _require_bound_loader(journal: dict[str, object], raw: dict[str, object]) -> None:
    if raw["device_path"] != journal["device_path"] or \
            raw["usb_bus_number"] != journal["usb_bus_number"] or \
            raw["identify_hex"] != journal["identify_hex"] or \
            raw["descriptor_sha256"] != journal["descriptor_sha256"] or \
            raw["loader_fingerprint_sha256"] != journal["loader_fingerprint_sha256"]:
        raise RecoveryRequired("live loader identity differs from the journal")


def _next_stable_journal(transaction: Transaction, source: dict[str, object],
                         boundary: int, observed: bytes) -> dict[str, object]:
    identity = _identity_from_journal(source)
    if boundary == transaction.install_count:
        status = PROOF_INSTALLED
    elif boundary == len(transaction.operations):
        status = COMPLETE
    else:
        status = BOUNDARY_VERIFIED
    target = boundary_journal(transaction, identity, boundary, status=status)
    target["last_observed_sha256"] = _planner.sha256(observed)
    return target


def _require_step_state(transaction: Transaction,
                        journal: dict[str, object]) -> int:
    validate_journal(transaction, journal)
    status = journal["status"]
    if status == PROOF_INSTALLED:
        raise ExecutorError(
            "proof image is installed; cold boot, then run validate-reentry")
    if status == RESTORE_READY:
        return transaction.install_count
    if status != BOUNDARY_VERIFIED:
        if status == PREFLIGHT_STARTED:
            raise ReadOnlyPreflightVerificationStopped(
                "terminal_state",
                RuntimeError(
                    "the stop phase is not journal-bound; follow the original "
                    "output or independently verify through SPI"))
        if status in (INTENT, REENTRY_STARTED, FINALIZE_STARTED):
            raise RecoveryRequired("terminal campaign state requires external SPI")
        raise ExecutorError("journal is not step-authorizing")
    return int(journal["boundary_index"])


def live_preflight(transaction: Transaction, journal_path: Path, *,
                   backend_factory=FixedProofReadOnlyBackend,
                   progress: bool = True,
                   journal_fault: Callable[[str], None] | None = None
                   ) -> dict[str, object]:
    with journal_lock(transaction, journal_path):
        started = preflight_started_journal(transaction)
        publish_initial(
            transaction, journal_path, started, fault=journal_fault)
        backend = None
        phase = "backend_open"
        try:
            backend = backend_factory(transaction)
            phase = "loader_identity"
            raw_identity = backend.identity()
            phase = "first_full_chip_read"
            first = backend.capture(progress=progress)
            phase = "second_full_chip_read"
            second = backend.capture(progress=progress)
            phase = "exact_read_pair_verification"
            _writer.require_exact_image(
                "two exact full-chip reads", first, second)
            observed = first
            phase = "exact_baseline_verification"
            _require_image(transaction, transaction.campaign.baseline, observed,
                           "proof preflight baseline")
            phase = "identity_binding"
            identity = _bound_identity(raw_identity, observed)
            phase = "strict_close"
            backend.close()
            backend = None
        except BaseException as error:
            if phase in ("exact_read_pair_verification",
                         "exact_baseline_verification"):
                raise ReadOnlyPreflightVerificationStopped(
                    phase, error) from error
            raise ReadOnlyPreflightStopped(phase, error) from error
        target = boundary_journal(transaction, identity, 0)
        outcome = publish_transition(
            transaction, journal_path, started, target, fault=journal_fault)
        if outcome == "source_retained_after_error":
            raise ReadOnlyPreflightStopped(
                "boundary_publication",
                RuntimeError("verified preflight boundary was not published"))
        if outcome != "target_confirmed":
            raise StateInspectionRequired(
                "verified preflight state is visible after a publication error")
        return target


def live_step(transaction: Transaction, journal_path: Path, *,
              backend_factory=FixedProofMutationBackend,
              progress: bool = True,
              journal_fault: Callable[[str], None] | None = None
              ) -> dict[str, object]:
    with journal_lock(transaction, journal_path):
        source = load_journal(journal_path)
        index = _require_step_state(transaction, source)
        intent = intent_journal(transaction, source, index)
        outcome = publish_transition(
            transaction, journal_path, source, intent, fault=journal_fault)
        if outcome != "target_confirmed":
            raise StateInspectionRequired(
                "raw intent publication did not return exact target; no USB opened")
        backend = None
        try:
            backend = backend_factory(transaction, index)
            raw_identity = backend.identity()
            _require_bound_loader(source, raw_identity)
            pre = _two_reads(backend, progress=progress)
            expected_pre = expected_boundary_image(transaction, index)
            _require_image(transaction, expected_pre, pre, "operation preimage")
            backend.execute()
            post = _two_reads(backend, progress=progress)
            expected_post = expected_boundary_image(transaction, index + 1)
            _require_image(transaction, expected_post, post, "operation postimage")
            backend.close()
            backend = None
        except BaseException as error:
            raise RecoveryRequired(
                "post-intent mutation, verification, or close anomaly; do not "
                "issue another USB command and recover through external SPI") from error
        target = _next_stable_journal(transaction, source, index + 1, post)
        outcome = publish_transition(
            transaction, journal_path, intent, target, fault=journal_fault)
        if outcome == "source_retained_after_error":
            raise RecoveryRequired(
                "verified image was not published; raw intent remains terminal")
        if outcome != "target_confirmed":
            raise StateInspectionRequired(
                "verified boundary is visible after a publication error")
        return target


def live_validate_reentry(transaction: Transaction, journal_path: Path, *,
                          backend_factory=FixedProofReadOnlyBackend,
                          progress: bool = True,
                          journal_fault: Callable[[str], None] | None = None
                          ) -> dict[str, object]:
    with journal_lock(transaction, journal_path):
        source = load_journal(journal_path)
        validate_journal(transaction, source)
        if source["status"] != PROOF_INSTALLED:
            raise ExecutorError("journal is not awaiting proof re-entry validation")
        started = dict(source)
        started["status"] = REENTRY_STARTED
        outcome = publish_transition(
            transaction, journal_path, source, started, fault=journal_fault)
        if outcome != "target_confirmed":
            raise StateInspectionRequired(
                "re-entry start was not exactly published; no USB opened")
        try:
            backend = backend_factory(transaction)
            raw_identity = backend.identity()
            _require_bound_loader(source, raw_identity)
            if raw_identity["usb_device_address"] == source["current_usb_address"]:
                raise RecoveryRequired(
                    "USB device address did not change; a new enumeration is unproved")
            observed = _two_reads(backend, progress=progress)
            _require_image(transaction, transaction.campaign.proof_image, observed,
                           "post-boot proof image")
            identity = _bound_identity(
                raw_identity, observed,
                initial_address=int(source["initial_usb_address"]))
            backend.close()
        except BaseException as error:
            if isinstance(error, RecoveryRequired):
                raise
            raise RecoveryRequired(
                "re-entry validation transport, image, or close failed; use SPI") from error
        target = boundary_journal(
            transaction, identity, transaction.install_count,
            status=RESTORE_READY)
        outcome = publish_transition(
            transaction, journal_path, started, target, fault=journal_fault)
        if outcome == "source_retained_after_error":
            raise RecoveryRequired("restore-ready state was not published")
        if outcome != "target_confirmed":
            raise StateInspectionRequired(
                "restore-ready is visible after a publication error")
        return target


def live_finalize(transaction: Transaction, journal_path: Path, *,
                  backend_factory=FixedProofReadOnlyBackend,
                  progress: bool = True,
                  journal_fault: Callable[[str], None] | None = None,
                  clear_fn: Callable[[Path], None] = clear_journal
                  ) -> dict[str, object]:
    with journal_lock(transaction, journal_path):
        source = load_journal(journal_path)
        validate_journal(transaction, source)
        if source["status"] != COMPLETE:
            raise ExecutorError("journal is not ready for finalization")
        started = dict(source)
        started["status"] = FINALIZE_STARTED
        outcome = publish_transition(
            transaction, journal_path, source, started, fault=journal_fault)
        if outcome != "target_confirmed":
            raise StateInspectionRequired(
                "finalization start was not exactly published; no USB opened")
        try:
            backend = backend_factory(transaction)
            raw_identity = backend.identity()
            _require_bound_loader(source, raw_identity)
            observed = _two_reads(backend, progress=progress)
            _require_image(transaction, transaction.campaign.baseline, observed,
                           "final exact baseline")
            backend.close()
        except BaseException as error:
            if isinstance(error, RecoveryRequired):
                raise
            raise RecoveryRequired(
                "final verification transport, image, or close failed; use SPI") from error
        try:
            clear_fn(journal_path)
        except BaseException as error:
            if _journal_exactly_absent(journal_path):
                raise StateInspectionRequired(
                    "final state is absent after a clear error; exact baseline was "
                    "verified and no USB action is authorized by this result") from error
            try:
                visible = load_journal(journal_path)
                validate_journal(transaction, visible)
            except BaseException as inspect_error:
                raise StateInspectionRequired(
                    "final journal visibility is ambiguous after a clear error") from inspect_error
            if visible == started:
                raise RecoveryRequired(
                    "final exact baseline was verified but terminal state remains") from error
            raise StateInspectionRequired(
                "final clear exposed an unexpected valid state") from error
        if not _journal_exactly_absent(journal_path):
            raise StateInspectionRequired("final journal clear did not expose exact absence")
        return {
            "status": "state_cleared",
            "boundary_index": len(transaction.operations),
            "observed_sha256": _planner.sha256(observed),
            "state_cleared": True,
        }


def inspect_state(transaction: Transaction, journal_path: Path) -> dict[str, object]:
    validate_journal_path(transaction, journal_path)
    if _journal_exactly_absent(journal_path):
        return {"journal_status": "absent", "permitted_next": "preflight_dry_run",
                "usb_opened": False}
    journal = load_journal(journal_path)
    validate_journal(transaction, journal)
    status = journal["status"]
    mapping = {
        BOUNDARY_VERIFIED: "step_dry_run",
        PROOF_INSTALLED: "cold_boot_then_validate_reentry_dry_run",
        RESTORE_READY: "step_dry_run",
        COMPLETE: "finalize_dry_run",
        PREFLIGHT_STARTED: "follow_recorded_preflight_stop_no_usb",
        INTENT: "external_spi_only",
        REENTRY_STARTED: "external_spi_only",
        FINALIZE_STARTED: "external_spi_only",
    }
    return {
        "journal_status": status,
        "boundary_index": journal["boundary_index"],
        "permitted_next": mapping[status],
        "usb_opened": False,
    }


def _print_plan(command: str, transaction: Transaction,
                journal: dict[str, object] | None = None) -> None:
    print(f"command   : {command}")
    print(f"campaign  : sha256 {transaction.campaign_id}")
    print(f"baseline  : sha256 {_planner.sha256(transaction.campaign.baseline)}")
    print(f"proof     : sha256 {_planner.sha256(transaction.campaign.proof_image)}")
    print(f"operations: {transaction.install_count} install + "
          f"{len(transaction.operations) - transaction.install_count} restore")
    print("mutable   : Core0 envelope + one fixed Core1 barrier sector")
    print("preserved : header, loader, manifest, all flash after Core1")
    print("general fw: mutation hard-disabled")
    print("read preflight: hard-disabled" if
          not LIVE_READ_ONLY_PREFLIGHT_ENABLED else
          "read preflight: exact campaign enabled")
    print("proof write: mutation hard-disabled" if
          not LIVE_PROOF_CAMPAIGN_ENABLED else
          "proof write: fixed campaign enabled")
    if journal is not None:
        print(f"status    : {journal['status']}")
        print(f"boundary  : {journal['boundary_index']}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "step", "validate-reentry", "finalize", "inspect"):
        sub = commands.add_parser(name)
        sub.add_argument("--baseline-a", required=True, type=Path)
        sub.add_argument("--baseline-b", required=True, type=Path)
        sub.add_argument("--proof-core0-elf", required=True, type=Path)
        sub.add_argument("--campaign", required=True, type=Path)
        sub.add_argument("--journal", required=True, type=Path)
        if name != "inspect":
            sub.add_argument("--commit", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        transaction = load_transaction(
            args.campaign, args.baseline_a, args.baseline_b,
            args.proof_core0_elf)
        journal = None
        if args.command != "preflight" and args.journal.exists():
            journal = load_journal(args.journal)
            validate_journal(transaction, journal)
        _print_plan(args.command, transaction, journal)
        if args.command == "inspect":
            print(json.dumps(
                inspect_state(transaction, args.journal), indent=2,
                sort_keys=True))
            return 0
        if not args.commit:
            if args.command == "preflight":
                if args.journal.exists():
                    raise ExecutorError("preflight refuses existing state")
            elif args.command == "step":
                if journal is None:
                    raise ExecutorError("step requires an existing journal")
                _require_step_state(transaction, journal)
            elif args.command == "validate-reentry":
                if journal is None or journal["status"] != PROOF_INSTALLED:
                    raise ExecutorError("validate-reentry requires proof_installed")
            elif args.command == "finalize":
                if journal is None or journal["status"] != COMPLETE:
                    raise ExecutorError("finalize requires complete state")
            print("\nDRY RUN -- no USB device was opened and nothing was changed.")
            return 0
        if args.command == "preflight":
            require_read_only_preflight_authorization(transaction)
            print("\nREAD-ONLY PREFLIGHT REQUESTED -- no program or erase command "
                  "is authorized.")
            result = live_preflight(transaction, args.journal)
        else:
            require_live_authorization(transaction)
            print("\nCOMMIT REQUESTED -- keep proven external SPI recovery available.")
            if args.command == "step":
                result = live_step(transaction, args.journal)
            elif args.command == "validate-reentry":
                result = live_validate_reentry(transaction, args.journal)
            else:
                result = live_finalize(transaction, args.journal)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except StateInspectionRequired as error:
        print(f"\nSTATE INSPECTION REQUIRED: {error}", file=sys.stderr)
        print("This result authorizes no USB action. Run inspect locally.",
              file=sys.stderr)
        return 4
    except ReadOnlyPreflightVerificationStopped as error:
        print(f"\nREAD-ONLY PREFLIGHT VERIFICATION STOPPED: {error}",
              file=sys.stderr)
        print("No program or erase command was sent, but USB readback did not "
              "establish the exact baseline. Do not boot or issue another USB "
              "command in this powered session. Verify independently through "
              "external SPI; write only if that independent read differs from "
              "the baseline.", file=sys.stderr)
        return 6
    except ReadOnlyPreflightStopped as error:
        print(f"\nREAD-ONLY PREFLIGHT STOPPED: {error}", file=sys.stderr)
        print("No program or erase command was sent. Do not issue another USB "
              "command in this powered session; power-cycle before using a new "
              "journal. External SPI is optional independent verification, not "
              "a required flash restore.", file=sys.stderr)
        return 5
    except RecoveryRequired as error:
        print(f"\nEXTERNAL SPI RECOVERY REQUIRED: {error}", file=sys.stderr)
        print("Do not issue another USB command; restore and verify by external SPI.",
              file=sys.stderr)
        return 3
    except ExecutionLocked as error:
        print(f"proof executor locked: {error}", file=sys.stderr)
        return 2
    except (OSError, ExecutorError, PlanError, ValueError) as error:
        print(f"proof executor error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
