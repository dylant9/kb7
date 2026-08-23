#!/usr/bin/env python3
"""Fixed KB7 USB-ISP multi-sector/restart experiment.

This is a laboratory experiment, not a firmware updater.  It operates only in
the reviewed, erased V1.22 scratch envelope and is dry-run by default.  Two
commands deliberately stop after a completed flash command but before
readback.  A separate process must then reconcile the durable intent against
two byte-identical full-chip reads.  Only the exact preimage or exact postimage
is accepted; every other result requires external SPI recovery.

The caller cannot choose addresses, payloads, CDBs, sizes, ordering, or a
recovery policy.  Do not power-cycle the keyboard while markers remain.
"""

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile


# Dynamic imports must not create public-tree policy failures when the tools
# are run directly from a checkout.
sys.dont_write_bytecode = True

_TOOL_DIR = Path(__file__).resolve().parent
_WRITER_PATH = _TOOL_DIR / "kb7-isp-write2.py"
_spec = importlib.util.spec_from_file_location(
    "kb7isp_write2_for_scratch_restart", _WRITER_PATH)
_writer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _writer
_spec.loader.exec_module(_writer)

SafetyError = _writer.SafetyError
WriteDevice = _writer.WriteDevice
load_baseline = _writer.load_baseline
parse_manifest = _writer.parse_manifest
sha256_bytes = _writer.sha256_bytes
query_loader_identity = _writer.query_loader_identity
capture_full_chip = _writer.capture_full_chip
require_exact_image = _writer.require_exact_image
set_address_mode_for_range = _writer.set_address_mode_for_range
cdb_program = _writer.cdb_program
cdb_erase = _writer.cdb_erase
poll_ready = _writer.poll_ready

FLASH_SIZE = _writer.FLASH_SIZE
BLOCK = _writer.BLOCK
SECTOR = _writer.SECTOR
SUB_EN4B = _writer.SUB_EN4B
SUB_EX4B = _writer.SUB_EX4B

STATE_SCHEMA = "kb7-isp-scratch-restart-state-v1"
DEFAULT_STATE = os.path.expanduser("~/.kb7-isp-scratch-restart-state.json")
LOADER_OFFSET = 0x00001000
LOADER_SIZE = 0x0000F000
EXPECTED_LOADER_SHA256 = (
    "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56")

EXPECTED_REGION_GEOMETRY = (
    (0x00000000, 0x00011000, 0x0000F35C),
    (0x10000000, 0x00021000, 0x0006B168),
    (0x60100000, 0x00100000, 0x0146AF8C),
)
EXPECTED_SCRATCH = (0x0008D000, 0x00100000)
ENVELOPE_LO = 0x000C0000
ENVELOPE_HI = 0x00100000

LOWER_GUARD_SECTOR = 0x000C4000
WORK_A_SECTOR = 0x000C5000
WORK_B_SECTOR = 0x000C6000
UPPER_GUARD_SECTOR = 0x000C7000
LOWER_GUARD_OFFSET = WORK_A_SECTOR - BLOCK
UPPER_GUARD_OFFSET = UPPER_GUARD_SECTOR

STAGES = (
    "prepare-a",
    "program-cut",
    "reconcile",
    "prepare-b",
    "erase-cut",
    "erase-b",
    "cleanup-lower",
    "cleanup-upper",
)


class ReconciliationRequired(RuntimeError):
    """A durable intent must be classified in a new USB session."""


class RecoveryRequired(RuntimeError):
    """The live image is outside the two exact authorized outcomes."""


def _pattern(slot):
    """Return one block with one deterministic cleared bit in every byte."""
    output = bytearray()
    counter = 0
    while len(output) < BLOCK:
        digest = hashlib.sha256(
            b"kb7-scratch-restart-v1\x00"
            + bytes([slot])
            + struct.pack(">I", counter)).digest()
        output.extend(0xFF ^ (1 << (value & 7)) for value in digest)
        counter += 1
    return bytes(output[:BLOCK])


PATTERNS = tuple(_pattern(slot) for slot in range(18))
LOWER_GUARD = PATTERNS[0]
WORK_A_WRITES = tuple(
    (WORK_A_SECTOR + index * BLOCK, PATTERNS[index + 1])
    for index in range(SECTOR // BLOCK))
WORK_B_WRITES = tuple(
    (WORK_B_SECTOR + index * BLOCK, PATTERNS[index + 9])
    for index in range(SECTOR // BLOCK))
UPPER_GUARD = PATTERNS[17]

PREPARE_A_WRITES = ((LOWER_GUARD_OFFSET, LOWER_GUARD),) + WORK_A_WRITES
PROGRAM_CUT_WRITE = WORK_B_WRITES[0]
PREPARE_B_WRITES = WORK_B_WRITES[1:] + ((UPPER_GUARD_OFFSET, UPPER_GUARD),)


def _source_sha256(path):
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def plan_descriptor():
    """Return all fixed inputs whose drift invalidates durable state."""
    writes = PREPARE_A_WRITES + (PROGRAM_CUT_WRITE,) + PREPARE_B_WRITES
    erases = (
        ("erase-cut", WORK_A_SECTOR),
        ("erase-b", WORK_B_SECTOR),
        ("cleanup-lower", LOWER_GUARD_SECTOR),
        ("cleanup-upper", UPPER_GUARD_SECTOR),
    )
    return {
        "schema": STATE_SCHEMA,
        "loader_sha256": EXPECTED_LOADER_SHA256,
        "flash_size": FLASH_SIZE,
        "block_size": BLOCK,
        "sector_size": SECTOR,
        "sub16_address_mode": SUB_EX4B,
        "envelope": [ENVELOPE_LO, ENVELOPE_HI],
        "geometry": {
            "lower_guard_sector": LOWER_GUARD_SECTOR,
            "work_a_sector": WORK_A_SECTOR,
            "work_b_sector": WORK_B_SECTOR,
            "upper_guard_sector": UPPER_GUARD_SECTOR,
            "lower_guard_offset": LOWER_GUARD_OFFSET,
            "upper_guard_offset": UPPER_GUARD_OFFSET,
        },
        "writes": [
            {
                "offset": offset,
                "sha256": sha256_bytes(payload),
                "cdb_hex": cdb_program(offset, BLOCK).hex(),
            }
            for offset, payload in writes
        ],
        "erases": [
            {
                "stage": stage,
                "offset": offset,
                "cdb_hex": cdb_erase(offset).hex(),
            }
            for stage, offset in erases
        ],
        "controlled_unknown_checkpoints": ["program-cut", "erase-cut"],
        "source_sha256": {
            "experiment": _source_sha256(__file__),
            "writer": _source_sha256(_writer.__file__),
            "verifier": _source_sha256(_writer._verify.__file__),
        },
    }


def _plan_sha256():
    encoded = json.dumps(
        plan_descriptor(), sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("ascii")
    return sha256_bytes(encoded)


PLAN_SHA256 = _plan_sha256()


def validate_v122_layout(manifest):
    geometry = tuple(
        (region.load, region.offset, region.length)
        for region in sorted(manifest.regions, key=lambda item: item.index))
    if geometry != EXPECTED_REGION_GEOMETRY:
        raise SafetyError("manifest is not the reviewed V1.22 layout")
    if (manifest.scratch_lo, manifest.scratch_hi) != EXPECTED_SCRATCH:
        raise SafetyError("manifest does not expose the reviewed V1.22 scratch gap")
    if not (manifest.scratch_lo <= ENVELOPE_LO
            and ENVELOPE_HI <= manifest.scratch_hi):
        raise SafetyError("containment envelope is outside manifest scratch")


def validate_loader_window(image):
    if len(image) != FLASH_SIZE:
        raise SafetyError("loader validation requires exactly 32 MiB")
    loader_hash = sha256_bytes(
        image[LOADER_OFFSET:LOADER_OFFSET + LOADER_SIZE])
    if not hmac.compare_digest(loader_hash, EXPECTED_LOADER_SHA256):
        raise SafetyError(
            "preserved ISP loader is not the reviewed V1.22 loader: "
            f"expected {EXPECTED_LOADER_SHA256}, got {loader_hash}")
    return loader_hash


def validate_baselines(baseline_a, baseline_b):
    if len(baseline_a) != FLASH_SIZE or len(baseline_b) != FLASH_SIZE:
        raise SafetyError("both baselines must be exact 32-MiB images")
    if baseline_a != baseline_b:
        raise SafetyError("the two owner baseline captures are not byte-identical")
    manifest = parse_manifest(baseline_a)
    validate_v122_layout(manifest)
    validate_loader_window(baseline_a)
    envelope = baseline_a[ENVELOPE_LO:ENVELOPE_HI]
    if envelope != b"\xff" * (ENVELOPE_HI - ENVELOPE_LO):
        first = next(index for index, value in enumerate(envelope)
                     if value != 0xFF)
        raise SafetyError(
            "the complete 256-KiB containment envelope must be erased; "
            f"first non-0xff byte is 0x{ENVELOPE_LO + first:x}")
    return manifest


def _overlay(image, writes):
    output = bytearray(image)
    for offset, payload in writes:
        output[offset:offset + len(payload)] = payload
    return bytes(output)


def image_prepare_a_count(baseline, count):
    if not 0 <= count <= len(PREPARE_A_WRITES):
        raise ValueError("prepare-a count is outside the fixed plan")
    return _overlay(baseline, PREPARE_A_WRITES[:count])


def image_after_program_cut(baseline):
    return _overlay(
        image_prepare_a_count(baseline, len(PREPARE_A_WRITES)),
        (PROGRAM_CUT_WRITE,))


def image_prepare_b_count(baseline, count):
    if not 0 <= count <= len(PREPARE_B_WRITES):
        raise ValueError("prepare-b count is outside the fixed plan")
    return _overlay(image_after_program_cut(baseline), PREPARE_B_WRITES[:count])


def image_prepared_all(baseline):
    return image_prepare_b_count(baseline, len(PREPARE_B_WRITES))


def image_after_erase_a(baseline):
    output = bytearray(image_prepared_all(baseline))
    output[WORK_A_SECTOR:WORK_A_SECTOR + SECTOR] = b"\xff" * SECTOR
    return bytes(output)


def image_after_erase_b(baseline):
    output = bytearray(image_after_erase_a(baseline))
    output[WORK_B_SECTOR:WORK_B_SECTOR + SECTOR] = b"\xff" * SECTOR
    return bytes(output)


def image_after_cleanup_lower(baseline):
    output = bytearray(image_after_erase_b(baseline))
    output[
        LOWER_GUARD_SECTOR:LOWER_GUARD_SECTOR + SECTOR] = b"\xff" * SECTOR
    return bytes(output)


def checkpoint_hashes(baseline):
    return {
        "stock": sha256_bytes(baseline),
        "prepare_a": sha256_bytes(
            image_prepare_a_count(baseline, len(PREPARE_A_WRITES))),
        "program_cut": sha256_bytes(image_after_program_cut(baseline)),
        "prepared_all": sha256_bytes(image_prepared_all(baseline)),
        "erase_a": sha256_bytes(image_after_erase_a(baseline)),
        "erase_b": sha256_bytes(image_after_erase_b(baseline)),
        "cleanup_lower": sha256_bytes(image_after_cleanup_lower(baseline)),
    }


_CANONICAL_MODEL_CACHE = {}


def _intent_from_hashes(kind, offset, payload, pre_hash, post_hash,
                        previous_status, next_status):
    cdb = cdb_program(offset, BLOCK) if kind == "program" else cdb_erase(offset)
    return {
        "kind": kind,
        "offset": offset,
        "cdb_hex": cdb.hex(),
        "payload_sha256": None if payload is None else sha256_bytes(payload),
        "pre_image_sha256": pre_hash,
        "post_image_sha256": post_hash,
        "previous_status": previous_status,
        "next_status": next_status,
    }


def _canonical_model(baseline):
    """Build canonical hashes incrementally without retaining image copies."""
    baseline_hash = sha256_bytes(baseline)
    cached = _CANONICAL_MODEL_CACHE.get(baseline_hash)
    if cached is not None:
        return cached

    image = bytearray(baseline)
    current_hash = baseline_hash
    operations = []
    stable = {"stock": current_hash}

    def program(offset, payload, previous, next_status):
        nonlocal current_hash
        image[offset:offset + BLOCK] = payload
        post_hash = sha256_bytes(image)
        operations.append(_intent_from_hashes(
            "program", offset, payload, current_hash, post_hash,
            previous, next_status))
        current_hash = post_hash
        stable[next_status] = post_hash

    def erase(offset, previous, next_status):
        nonlocal current_hash
        image[offset:offset + SECTOR] = b"\xff" * SECTOR
        post_hash = sha256_bytes(image)
        operations.append(_intent_from_hashes(
            "erase", offset, None, current_hash, post_hash,
            previous, next_status))
        current_hash = post_hash
        if next_status != "complete":
            stable[next_status] = post_hash

    previous = "stock"
    for index, (offset, payload) in enumerate(PREPARE_A_WRITES):
        next_status = _stable_status_for_prepare(
            "prepare_a", index + 1, len(PREPARE_A_WRITES),
            "prepare_a_verified")
        program(offset, payload, previous, next_status)
        previous = next_status

    program(
        PROGRAM_CUT_WRITE[0], PROGRAM_CUT_WRITE[1],
        "prepare_a_verified", "program_cut_verified")
    previous = "program_cut_verified"
    for index, (offset, payload) in enumerate(PREPARE_B_WRITES):
        next_status = _stable_status_for_prepare(
            "prepare_b", index + 1, len(PREPARE_B_WRITES),
            "prepared_all_verified")
        program(offset, payload, previous, next_status)
        previous = next_status

    erase(
        WORK_A_SECTOR, "prepared_all_verified", "work_a_erased_verified")
    erase(
        WORK_B_SECTOR, "work_a_erased_verified", "work_b_erased_verified")
    erase(
        LOWER_GUARD_SECTOR, "work_b_erased_verified",
        "lower_cleanup_verified")
    erase(UPPER_GUARD_SECTOR, "lower_cleanup_verified", "complete")

    result = (tuple(operations), stable)
    _CANONICAL_MODEL_CACHE.clear()
    _CANONICAL_MODEL_CACHE[baseline_hash] = result
    return result


def canonical_operations(baseline):
    """Return every state transition the fixed experiment can authorize."""
    return _canonical_model(baseline)[0]


def canonical_stable_states(baseline):
    """Map every resumable stable status to its exact full-chip hash."""
    return _canonical_model(baseline)[1]


def _is_hex(value, length):
    return (isinstance(value, str) and len(value) == length
            and all(character in "0123456789abcdef" for character in value))


def _validate_device_path(value):
    if not isinstance(value, str) or not value or len(value) > 256:
        raise SafetyError("state device_path is malformed")
    pieces = value.split("-", 1)
    if (len(pieces) != 2 or not pieces[0].isdigit() or not pieces[1]
            or any(not item.isdigit() for item in pieces[1].split("."))):
        raise SafetyError("state device_path is malformed")


def _state(identity, manifest, baseline_hash, hashes, status,
           current_hash, intent=None):
    return {
        "schema": STATE_SCHEMA,
        "status": status,
        "device_path": identity["device_path"],
        "identify_hex": identity["identify_hex"],
        "descriptor_sha256": identity["descriptor_sha256"],
        "loader_fingerprint_sha256": identity[
            "loader_fingerprint_sha256"],
        "loader_window_sha256": EXPECTED_LOADER_SHA256,
        "manifest_sha256": manifest.sha256,
        "baseline_sha256": baseline_hash,
        "current_image_sha256": current_hash,
        "checkpoint_sha256": hashes,
        "plan_sha256": PLAN_SHA256,
        "intent": intent,
    }


STATE_KEYS = {
    "schema", "status", "device_path", "identify_hex",
    "descriptor_sha256", "loader_fingerprint_sha256",
    "loader_window_sha256", "manifest_sha256", "baseline_sha256",
    "current_image_sha256", "checkpoint_sha256", "plan_sha256", "intent",
}
INTENT_KEYS = {
    "kind", "offset", "cdb_hex", "payload_sha256", "pre_image_sha256",
    "post_image_sha256", "previous_status", "next_status",
}


def validate_state_static(state, manifest, baseline_hash, hashes,
                          baseline=None):
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        raise SafetyError("state fields do not match this experiment")
    exact = {
        "schema": STATE_SCHEMA,
        "loader_window_sha256": EXPECTED_LOADER_SHA256,
        "manifest_sha256": manifest.sha256,
        "baseline_sha256": baseline_hash,
        "checkpoint_sha256": hashes,
        "plan_sha256": PLAN_SHA256,
    }
    for key, wanted in exact.items():
        got = state[key]
        if isinstance(wanted, str):
            if not isinstance(got, str) or not hmac.compare_digest(got, wanted):
                raise SafetyError(f"state {key} does not match this experiment")
        elif got != wanted or type(got) is not type(wanted):
            raise SafetyError(f"state {key} does not match this experiment")
    if not isinstance(state["status"], str) or not state["status"]:
        raise SafetyError("state status is malformed")
    _validate_device_path(state["device_path"])
    if state["identify_hex"] != _writer.LOADER_IDENT.hex():
        raise SafetyError("state identify_hex is malformed")
    for key in ("descriptor_sha256", "loader_fingerprint_sha256",
                "current_image_sha256"):
        if not _is_hex(state[key], 64):
            raise SafetyError(f"state {key} is malformed")
    intent = state["intent"]
    if intent is not None:
        if not isinstance(intent, dict) or set(intent) != INTENT_KEYS:
            raise SafetyError("state intent is malformed")
        if intent["kind"] not in ("program", "erase"):
            raise SafetyError("state intent kind is malformed")
        if (type(intent["offset"]) is not int
                or intent["offset"] not in _all_mutation_offsets()):
            raise SafetyError("state intent offset is outside the fixed plan")
        if not _is_hex(intent["cdb_hex"], 32):
            raise SafetyError("state intent CDB is malformed")
        payload_hash = intent["payload_sha256"]
        if payload_hash is not None and not _is_hex(payload_hash, 64):
            raise SafetyError("state intent payload hash is malformed")
        for key in ("pre_image_sha256", "post_image_sha256"):
            if not _is_hex(intent[key], 64):
                raise SafetyError(f"state intent {key} is malformed")
        for key in ("previous_status", "next_status"):
            if not isinstance(intent[key], str) or not intent[key]:
                raise SafetyError(f"state intent {key} is malformed")
        if not hmac.compare_digest(
                state["current_image_sha256"], intent["pre_image_sha256"]):
            raise SafetyError("intent preimage does not match current state")
        if state["status"] != "intent_pending":
            raise SafetyError("state with an intent must be intent_pending")
    elif state["status"] == "intent_pending":
        raise SafetyError("intent_pending state has no intent")

    if baseline is not None:
        stable = canonical_stable_states(baseline)
        if intent is None:
            if (state["status"] not in stable
                    or not hmac.compare_digest(
                        state["current_image_sha256"], stable[state["status"]])):
                raise SafetyError("state is not a canonical stable checkpoint")
        elif not any(intent == candidate
                     for candidate in canonical_operations(baseline)):
            raise SafetyError("state intent is not a canonical fixed operation")
    return state


def validate_connected_state(state, identity):
    for key in ("device_path", "identify_hex", "descriptor_sha256",
                "loader_fingerprint_sha256"):
        if not hmac.compare_digest(state[key], identity[key]):
            raise SafetyError(f"connected device {key} differs from state")


def _strict_json_load(path):
    if os.path.islink(path):
        raise SafetyError("state file may not be a symbolic link")
    try:
        information = os.lstat(path)
        if not stat.S_ISREG(information.st_mode):
            raise SafetyError("state path is not a regular file")

        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError(f"duplicate JSON key {key!r}")
                value[key] = item
            return value

        with open(path, "r", encoding="utf-8") as stream:
            if os.fstat(stream.fileno()).st_size > 32768:
                raise SafetyError("state file is unexpectedly large")
            value = json.load(
                stream,
                object_pairs_hook=unique_object,
                parse_constant=lambda token: (_ for _ in ()).throw(
                    ValueError(f"invalid JSON constant {token}")))
    except FileNotFoundError as exc:
        raise SafetyError("required scratch experiment state is absent") from exc
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SafetyError(f"cannot load strict state JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SafetyError("state is not a JSON object")
    return value


def _safe_state_parent(path):
    absolute = Path(path).absolute()
    parent = absolute.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    information = parent.lstat()
    if (parent.is_symlink() or not stat.S_ISDIR(information.st_mode)
            or parent.resolve(strict=True) != parent):
        raise SafetyError("state parent must be a real directory")
    return absolute, parent


def write_state_atomic(path, state, require_absent=False):
    absolute, parent = _safe_state_parent(path)
    if absolute.is_symlink():
        raise SafetyError("state file may not be a symbolic link")
    if absolute.exists() and not absolute.is_file():
        raise SafetyError("state path is not a regular file")
    if require_absent and os.path.lexists(absolute):
        raise SafetyError("state file already exists")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".kb7-scratch-restart-state.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        encoded = (json.dumps(
            state, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if require_absent and os.path.lexists(absolute):
            raise SafetyError("state file appeared concurrently")
        os.replace(temporary, absolute)
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


def clear_state(path):
    absolute, parent = _safe_state_parent(path)
    try:
        absolute.unlink()
    except FileNotFoundError:
        return
    directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _all_mutation_offsets():
    return {
        *(offset for offset, _payload in PREPARE_A_WRITES),
        PROGRAM_CUT_WRITE[0],
        *(offset for offset, _payload in PREPARE_B_WRITES),
        WORK_A_SECTOR,
        WORK_B_SECTOR,
        LOWER_GUARD_SECTOR,
        UPPER_GUARD_SECTOR,
    }


def _stable_status_for_prepare(prefix, count, total, final_status):
    if count == total:
        return final_status
    return f"{prefix}_step_{count:02d}_verified"


def _prepare_a_progress(state):
    if state is None:
        return 0
    if state["intent"] is not None:
        raise SafetyError("unresolved intent requires stage reconcile")
    if state["status"] == "stock":
        return 0
    if state["status"] == "prepare_a_verified":
        return len(PREPARE_A_WRITES)
    prefix = "prepare_a_step_"
    suffix = "_verified"
    status = state["status"]
    if status.startswith(prefix) and status.endswith(suffix):
        value = status[len(prefix):-len(suffix)]
        if value.isdigit() and 1 <= int(value) < len(PREPARE_A_WRITES):
            return int(value)
    raise SafetyError("state is not a valid prepare-a checkpoint")


def _prepare_b_progress(state):
    if state["intent"] is not None:
        raise SafetyError("unresolved intent requires stage reconcile")
    if state["status"] == "prepared_all_verified":
        return len(PREPARE_B_WRITES)
    if state["status"] == "program_cut_verified":
        return 0
    prefix = "prepare_b_step_"
    suffix = "_verified"
    status = state["status"]
    if status.startswith(prefix) and status.endswith(suffix):
        value = status[len(prefix):-len(suffix)]
        if value.isdigit() and 1 <= int(value) < len(PREPARE_B_WRITES):
            return int(value)
    raise SafetyError("state is not a valid prepare-b checkpoint")


def _make_intent(kind, offset, payload, before, after,
                 previous_status, next_status):
    cdb = cdb_program(offset, BLOCK) if kind == "program" else cdb_erase(offset)
    return {
        "kind": kind,
        "offset": offset,
        "cdb_hex": cdb.hex(),
        "payload_sha256": None if payload is None else sha256_bytes(payload),
        "pre_image_sha256": sha256_bytes(before),
        "post_image_sha256": sha256_bytes(after),
        "previous_status": previous_status,
        "next_status": next_status,
    }


def _require_live_image(image, expected, baseline_manifest, label):
    require_exact_image(label, expected, image)
    validate_loader_window(image)
    manifest = parse_manifest(image)
    validate_v122_layout(manifest)
    if not hmac.compare_digest(manifest.sha256, baseline_manifest.sha256):
        raise RecoveryRequired("live manifest changed during scratch experiment")
    return sha256_bytes(image)


def _open_and_preflight(expected, baseline_manifest, saved_state,
                        device_factory, read_full_fn, progress):
    device = device_factory()
    try:
        identity = query_loader_identity(device)
        if saved_state is not None:
            validate_connected_state(saved_state, identity)
        observed = capture_full_chip(
            device, progress=progress, read_full_fn=read_full_fn)
        observed_hash = _require_live_image(
            observed, expected, baseline_manifest, "stage preimage")
        return device, identity, observed_hash
    except BaseException:
        device.close()
        raise


def _persist_intent(state_path, identity, manifest, baseline_hash, hashes,
                    previous_status, before, intent, require_absent=False):
    state = _state(
        identity, manifest, baseline_hash, hashes,
        "intent_pending", sha256_bytes(before), intent)
    write_state_atomic(state_path, state, require_absent=require_absent)
    return state


def _perform_operation(*, device, identity, manifest, baseline_hash, hashes,
                       state_path, previous_status, next_status, before, after,
                       kind, offset, payload, controlled_cut, progress,
                       read_full_fn, require_absent=False):
    intent = _make_intent(
        kind, offset, payload, before, after, previous_status, next_status)
    _persist_intent(
        state_path, identity, manifest, baseline_hash, hashes,
        previous_status, before, intent, require_absent=require_absent)

    try:
        mode = set_address_mode_for_range(
            device, offset, BLOCK if kind == "program" else SECTOR)
        if mode != SUB_EX4B:
            raise RuntimeError("fixed scratch operation did not select F6 18")
        if kind == "program":
            device.program(cdb_program(offset, BLOCK), payload)
        else:
            device.cmd(cdb_erase(offset))
        poll_ready(device)
    except BaseException as exc:
        raise ReconciliationRequired(
            "flash intent is durable but command completion is unknown; "
            "close this session and run stage reconcile") from exc

    if controlled_cut:
        raise ReconciliationRequired(
            "planned no-readback checkpoint reached; run stage reconcile in "
            "a new process")

    try:
        observed = capture_full_chip(
            device, progress=progress, read_full_fn=read_full_fn)
        try:
            observed_hash = _require_live_image(
                observed, after, manifest, "operation postimage")
        except (SafetyError, ValueError) as exc:
            raise RecoveryRequired(
                f"post-mutation image is not the exact authorized postimage: "
                f"{exc}") from exc
    except RecoveryRequired:
        raise
    except BaseException as exc:
        raise ReconciliationRequired(
            "mutation completed but exact readback did not; run stage "
            "reconcile in a new process") from exc

    if next_status == "complete":
        clear_state(state_path)
    else:
        try:
            write_state_atomic(
                state_path,
                _state(identity, manifest, baseline_hash, hashes,
                       next_status, observed_hash, None))
        except BaseException as exc:
            raise ReconciliationRequired(
                "postimage was exact but the verified state was not durably "
                "published; run stage reconcile in a new process") from exc
    return observed


def _load_valid_state(path, manifest, baseline_hash, hashes, baseline):
    state = _strict_json_load(path)
    return validate_state_static(
        state, manifest, baseline_hash, hashes, baseline)


def _expected_stable_image(stage, state, baseline):
    if stage == "prepare-a":
        count = _prepare_a_progress(state)
        return image_prepare_a_count(baseline, count)
    if stage == "program-cut":
        if state["intent"] is not None or state["status"] != "prepare_a_verified":
            raise SafetyError("program-cut requires prepare_a_verified")
        return image_prepare_a_count(baseline, len(PREPARE_A_WRITES))
    if stage == "prepare-b":
        count = _prepare_b_progress(state)
        return image_prepare_b_count(baseline, count)
    required = {
        "erase-cut": ("prepared_all_verified", image_prepared_all),
        "erase-b": ("work_a_erased_verified", image_after_erase_a),
        "cleanup-lower": ("work_b_erased_verified", image_after_erase_b),
        "cleanup-upper": ("lower_cleanup_verified", image_after_cleanup_lower),
    }
    status, image_fn = required[stage]
    if state["intent"] is not None or state["status"] != status:
        raise SafetyError(f"{stage} requires state {status}")
    return image_fn(baseline)


def reconcile_intent(baseline, manifest, baseline_hash, hashes, state_path,
                     progress=True, device_factory=WriteDevice,
                     read_full_fn=None):
    state = _load_valid_state(
        state_path, manifest, baseline_hash, hashes, baseline)
    intent = state["intent"]
    if state["status"] != "intent_pending" or intent is None:
        raise SafetyError("reconcile requires one unresolved durable intent")

    device = device_factory()
    try:
        identity = query_loader_identity(device)
        validate_connected_state(state, identity)
        print("reconcile : first exact 32-MiB classification read ...")
        first = capture_full_chip(
            device, progress=progress, read_full_fn=read_full_fn)
        print("reconcile : second exact 32-MiB stability read ...")
        second = capture_full_chip(
            device, progress=progress, read_full_fn=read_full_fn)
        if first != second:
            raise RecoveryRequired(
                "the two reconciliation captures differ; do not mutate")
        try:
            validate_loader_window(first)
            live_manifest = parse_manifest(first)
            validate_v122_layout(live_manifest)
            if not hmac.compare_digest(live_manifest.sha256, manifest.sha256):
                raise SafetyError("manifest differs")
        except (SafetyError, ValueError) as exc:
            raise RecoveryRequired(
                f"stable reconciliation image failed live validation: {exc}") from exc

        observed_hash = sha256_bytes(first)
        if hmac.compare_digest(observed_hash, intent["pre_image_sha256"]):
            next_status = intent["previous_status"]
            classification = "exact_preimage_no_observable_effect"
        elif hmac.compare_digest(observed_hash, intent["post_image_sha256"]):
            next_status = intent["next_status"]
            classification = "exact_postimage_completed"
        else:
            raise RecoveryRequired(
                "stable flash image is neither the exact intent preimage nor "
                "the exact intent postimage")

        if next_status == "complete":
            clear_state(state_path)
        else:
            write_state_atomic(
                state_path,
                _state(identity, manifest, baseline_hash, hashes,
                       next_status, observed_hash, None))
        print(json.dumps({
            "classification": classification,
            "observed_sha256": observed_hash,
            "next_status": next_status,
            "automatic_retry": False,
        }, sort_keys=True, indent=2))
        return 0
    finally:
        device.close()


def _run_prepare_group(stage, writes, start_count, baseline, manifest,
                       baseline_hash, hashes, state_path, state,
                       device_factory, read_full_fn, progress):
    if stage == "prepare-a":
        image_fn = image_prepare_a_count
        prefix = "prepare_a"
        final_status = "prepare_a_verified"
    else:
        image_fn = image_prepare_b_count
        prefix = "prepare_b"
        final_status = "prepared_all_verified"
    before = image_fn(baseline, start_count)
    device, identity, _observed_hash = _open_and_preflight(
        before, manifest, state, device_factory, read_full_fn, progress)
    try:
        for index in range(start_count, len(writes)):
            offset, payload = writes[index]
            after = image_fn(baseline, index + 1)
            previous_status = (
                "stock" if stage == "prepare-a" and index == 0
                else ("program_cut_verified" if stage == "prepare-b" and index == 0
                      else _stable_status_for_prepare(
                          prefix, index, len(writes), final_status)))
            next_status = _stable_status_for_prepare(
                prefix, index + 1, len(writes), final_status)
            print(
                f"program   : {stage} block {index + 1}/{len(writes)} "
                f"at 0x{offset:08x}")
            _perform_operation(
                device=device, identity=identity, manifest=manifest,
                baseline_hash=baseline_hash, hashes=hashes,
                state_path=state_path, previous_status=previous_status,
                next_status=next_status, before=before, after=after,
                kind="program", offset=offset, payload=payload,
                controlled_cut=False, progress=progress,
                read_full_fn=read_full_fn,
                require_absent=(
                    stage == "prepare-a" and index == 0 and state is None))
            before = after
        print(f"PASS: {stage} reached its exact full-chip checkpoint.")
        return 0
    finally:
        device.close()


def execute_stage(stage, baseline, manifest, state_path, progress=True,
                  device_factory=WriteDevice, read_full_fn=None):
    baseline_hash = sha256_bytes(baseline)
    hashes = checkpoint_hashes(baseline)
    if stage == "reconcile":
        return reconcile_intent(
            baseline, manifest, baseline_hash, hashes, state_path,
            progress=progress, device_factory=device_factory,
            read_full_fn=read_full_fn)

    state = None
    if os.path.lexists(state_path):
        state = _load_valid_state(
            state_path, manifest, baseline_hash, hashes, baseline)
    elif stage != "prepare-a":
        raise SafetyError("only prepare-a may begin without experiment state")
    if state is not None and state["intent"] is not None:
        raise SafetyError("unresolved intent requires stage reconcile")

    expected = _expected_stable_image(stage, state, baseline)
    if state is not None and not hmac.compare_digest(
            state["current_image_sha256"], sha256_bytes(expected)):
        raise SafetyError("state current image does not match stage checkpoint")

    if stage == "prepare-a":
        start = _prepare_a_progress(state)
        if start == len(PREPARE_A_WRITES):
            raise SafetyError("prepare-a is already complete")
        return _run_prepare_group(
            stage, PREPARE_A_WRITES, start, baseline, manifest,
            baseline_hash, hashes, state_path, state,
            device_factory, read_full_fn, progress)
    if stage == "prepare-b":
        start = _prepare_b_progress(state)
        if start == len(PREPARE_B_WRITES):
            raise SafetyError("prepare-b is already complete")
        return _run_prepare_group(
            stage, PREPARE_B_WRITES, start, baseline, manifest,
            baseline_hash, hashes, state_path, state,
            device_factory, read_full_fn, progress)

    operations = {
        "program-cut": (
            "program", PROGRAM_CUT_WRITE[0], PROGRAM_CUT_WRITE[1],
            image_after_program_cut(baseline), "prepare_a_verified",
            "program_cut_verified", True),
        "erase-cut": (
            "erase", WORK_A_SECTOR, None, image_after_erase_a(baseline),
            "prepared_all_verified", "work_a_erased_verified", True),
        "erase-b": (
            "erase", WORK_B_SECTOR, None, image_after_erase_b(baseline),
            "work_a_erased_verified", "work_b_erased_verified", False),
        "cleanup-lower": (
            "erase", LOWER_GUARD_SECTOR, None,
            image_after_cleanup_lower(baseline), "work_b_erased_verified",
            "lower_cleanup_verified", False),
        "cleanup-upper": (
            "erase", UPPER_GUARD_SECTOR, None, baseline,
            "lower_cleanup_verified", "complete", False),
    }
    kind, offset, payload, after, previous_status, next_status, cut = (
        operations[stage])
    device, identity, _observed_hash = _open_and_preflight(
        expected, manifest, state, device_factory, read_full_fn, progress)
    try:
        print(f"{kind:10}: {stage} at 0x{offset:08x}")
        _perform_operation(
            device=device, identity=identity, manifest=manifest,
            baseline_hash=baseline_hash, hashes=hashes,
            state_path=state_path, previous_status=previous_status,
            next_status=next_status, before=expected, after=after,
            kind=kind, offset=offset, payload=payload,
            controlled_cut=cut, progress=progress,
            read_full_fn=read_full_fn)
        print(f"PASS: {stage} reached its exact full-chip checkpoint.")
        return 0
    finally:
        device.close()


def _load_offline(stage, baseline, manifest, state_path):
    baseline_hash = sha256_bytes(baseline)
    hashes = checkpoint_hashes(baseline)
    state = None
    if os.path.lexists(state_path):
        state = _load_valid_state(
            state_path, manifest, baseline_hash, hashes, baseline)
    if stage == "reconcile":
        if state is None or state["intent"] is None:
            raise SafetyError("reconcile requires an unresolved intent")
        return state, None
    if state is None and stage != "prepare-a":
        raise SafetyError("only prepare-a may begin without state")
    if state is not None and state["intent"] is not None:
        raise SafetyError("unresolved intent requires stage reconcile")
    expected = _expected_stable_image(stage, state, baseline)
    if state is not None and not hmac.compare_digest(
            state["current_image_sha256"], sha256_bytes(expected)):
        raise SafetyError("state current image does not match stage checkpoint")
    return state, expected


def _print_plan(stage, baseline, manifest, state, expected):
    print(f"stage     : {stage}")
    print(f"scratch   : [0x{manifest.scratch_lo:x},0x{manifest.scratch_hi:x})")
    print(f"envelope  : [0x{ENVELOPE_LO:x},0x{ENVELOPE_HI:x}) all 0xff")
    print(
        f"work      : A=0x{WORK_A_SECTOR:08x}, B=0x{WORK_B_SECTOR:08x}")
    print(
        f"guards    : 0x{LOWER_GUARD_OFFSET:08x}, "
        f"0x{UPPER_GUARD_OFFSET:08x}")
    print(f"baseline  : sha256 {sha256_bytes(baseline)}")
    print(f"loader    : sha256 {EXPECTED_LOADER_SHA256}")
    print(f"plan      : sha256 {PLAN_SHA256}")
    if expected is not None:
        print(f"preimage  : sha256 {sha256_bytes(expected)}")
    if stage == "reconcile":
        print(f"intent    : {state['intent']['kind']} at "
              f"0x{state['intent']['offset']:08x}")
        print(f"preimage  : sha256 {state['intent']['pre_image_sha256']}")
        print(f"postimage : sha256 {state['intent']['post_image_sha256']}")
        print("reads     : two exact 32-MiB captures; preimage or postimage only")
    elif stage in ("program-cut", "erase-cut"):
        print("checkpoint: command + WIP poll, then intentional close without readback")
    print("mode      : F6 18 before every fixed program/erase")


def _paths_same(first, second):
    try:
        return os.path.samefile(first, second)
    except FileNotFoundError:
        return os.path.abspath(first) == os.path.abspath(second)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--baseline-a", required=True)
    parser.add_argument("--baseline-b", required=True)
    parser.add_argument("--state-file", default=DEFAULT_STATE)
    parser.add_argument(
        "--commit", action="store_true",
        help="open USB and perform this fixed stage; dry-run is the default")
    args = parser.parse_args()

    try:
        if _paths_same(args.baseline_a, args.baseline_b):
            raise SafetyError("baseline A and B must be distinct files")
        if (_paths_same(args.baseline_a, args.state_file)
                or _paths_same(args.baseline_b, args.state_file)):
            raise SafetyError("state file must not alias either baseline")
        baseline_a = load_baseline(args.baseline_a)
        baseline_b = load_baseline(args.baseline_b)
        manifest = validate_baselines(baseline_a, baseline_b)
        state, expected = _load_offline(
            args.stage, baseline_a, manifest, args.state_file)
        _print_plan(args.stage, baseline_a, manifest, state, expected)
        if not args.commit:
            print("\nDRY RUN -- no USB device was opened and nothing was changed.")
            return 0
        print("\nCOMMIT REQUESTED -- keep proven external SPI recovery available.")
        return execute_stage(
            args.stage, baseline_a, manifest, args.state_file)
    except ReconciliationRequired as exc:
        print(f"\nRECONCILIATION REQUIRED: {exc}", file=sys.stderr)
        print(
            "Do not run another mutation. Start a new process with --stage "
            "reconcile --commit.", file=sys.stderr)
        return 4
    except RecoveryRequired as exc:
        print(f"\nSPI RECOVERY REQUIRED: {exc}", file=sys.stderr)
        print(
            "Do not retry a USB mutation. Verify or restore the exact owner "
            "baseline through the proven external SPI path.", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nABORT: interrupted before durable mutation intent", file=sys.stderr)
        return 130
    except (SafetyError, RuntimeError, ValueError, OSError) as exc:
        print(f"\nABORT: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
