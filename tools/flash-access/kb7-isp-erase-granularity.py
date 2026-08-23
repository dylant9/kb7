#!/usr/bin/env python3
"""Guarded KB7 USB-ISP erase-footprint experiment.

This is a fixed, four-stage laboratory test, not a firmware flasher.  It uses
the strict, hardware-validated transport in ``kb7-isp-write2.py`` to:

1. ``prepare``: program two boundary guards and all eight 512-byte blocks of
   one otherwise unused 4-KiB sector;
2. ``erase-target``: erase the populated target sector and prove that every
   target byte became 0xff while both adjacent guards survived;
3. ``cleanup-lower``: erase the lower guard sector; and
4. ``cleanup-upper``: erase the upper guard sector and require the exact
   original 32-MiB image.

The target and payloads are not caller-selectable.  Every mutation is preceded
by the vendor's sub-16-MiB ``F6 18`` mode command, uses one reviewed 512-byte
``F6 06`` program or one reviewed ``F6 15`` erase, polls WIP to completion,
and is followed by an exact full-chip read.  State is bound to the loader,
USB topology, manifest, owner baseline, plan and every expected image.

Dry-run is the default.  A failed or interrupted committed mutation consumes
its authorization state and must not be retried over USB.  Keep the proven SPI
recovery path and two matching full-chip backups available, but physically
disconnect the programmer during this USB experiment.  Do not power-cycle the
keyboard while test markers remain.
"""

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import struct
import sys


_spec = importlib.util.spec_from_file_location(
    "kb7isp_write2_for_granularity",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "kb7-isp-write2.py"))
_writer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _writer
_spec.loader.exec_module(_writer)

SafetyError = _writer.SafetyError
MutationResultUnknown = _writer.MutationResultUnknown
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
load_state = _writer.load_state
write_state_atomic = _writer.write_state_atomic
clear_state = _writer.clear_state
_paths_are_same = _writer._paths_are_same

FLASH_SIZE = _writer.FLASH_SIZE
BLOCK = _writer.BLOCK
SECTOR = _writer.SECTOR
SUB_EN4B = _writer.SUB_EN4B
SUB_EX4B = _writer.SUB_EX4B

STATE_SCHEMA = "kb7-isp-erase-granularity-state-v1"
DEFAULT_STATE = os.path.expanduser(
    "~/.kb7-isp-erase-granularity-state.json")
LOADER_OFFSET = 0x00001000
LOADER_SIZE = 0x0000F000
EXPECTED_LOADER_SHA256 = (
    "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56")

# Fixed V1.22 geometry.  The 256-KiB aligned envelope is wholly inside the
# manifest-derived application-to-assets gap.  The target's aligned 64/128/256-
# KiB containers all remain inside that envelope, bounding those plausible
# erase mistakes to already-erased scratch rather than declared firmware.
EXPECTED_REGION_GEOMETRY = (
    (0x00000000, 0x00011000, 0x0000F35C),
    (0x10000000, 0x00021000, 0x0006B168),
    (0x60100000, 0x00100000, 0x0146AF8C),
)
EXPECTED_SCRATCH = (0x0008D000, 0x00100000)
ENVELOPE_LO = 0x000C0000
ENVELOPE_HI = 0x00100000
TARGET_SECTOR = 0x000C6000
LOWER_SECTOR = TARGET_SECTOR - SECTOR
UPPER_SECTOR = TARGET_SECTOR + SECTOR
LOWER_GUARD_OFFSET = TARGET_SECTOR - BLOCK
UPPER_GUARD_OFFSET = UPPER_SECTOR

STAGES = ("prepare", "erase-target", "cleanup-lower", "cleanup-upper")
STAGE_INPUT_STATUS = {
    "erase-target": "prepared_verified",
    "cleanup-lower": "target_erased_verified",
    "cleanup-upper": "lower_cleaned_verified",
}
STAGE_STARTED_STATUS = {
    "erase-target": "target_erase_started",
    "cleanup-lower": "lower_cleanup_started",
    "cleanup-upper": "upper_cleanup_started",
}
STAGE_OUTPUT_STATUS = {
    "erase-target": "target_erased_verified",
    "cleanup-lower": "lower_cleaned_verified",
}


def _pattern(slot):
    """Return a domain-separated block with exactly one cleared bit per byte."""
    output = bytearray()
    counter = 0
    while len(output) < BLOCK:
        digest = hashlib.sha256(
            b"kb7-erase-granularity-v1\x00"
            + bytes([slot])
            + struct.pack(">I", counter)).digest()
        output.extend(0xFF ^ (1 << (value & 7)) for value in digest)
        counter += 1
    return bytes(output[:BLOCK])


PATTERNS = tuple(_pattern(slot) for slot in range(10))
PREPARE_WRITES = (
    ((LOWER_GUARD_OFFSET, PATTERNS[0]),)
    + tuple(
        (TARGET_SECTOR + index * BLOCK, PATTERNS[index + 1])
        for index in range(SECTOR // BLOCK))
    + ((UPPER_GUARD_OFFSET, PATTERNS[9]),)
)
LOWER_GUARD = PATTERNS[0]
TARGET_PAYLOAD = b"".join(PATTERNS[1:9])
UPPER_GUARD = PATTERNS[9]


def _source_sha256(path):
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def plan_descriptor():
    """Return every command and implementation input bound by stage state."""
    return {
        "schema": STATE_SCHEMA,
        "loader_sha256": EXPECTED_LOADER_SHA256,
        "flash_size": FLASH_SIZE,
        "block_size": BLOCK,
        "sector_size": SECTOR,
        "sub16_address_mode": SUB_EX4B,
        "envelope": [ENVELOPE_LO, ENVELOPE_HI],
        "lower_sector": LOWER_SECTOR,
        "target_sector": TARGET_SECTOR,
        "upper_sector": UPPER_SECTOR,
        "writes": [
            {
                "offset": offset,
                "sha256": sha256_bytes(payload),
                "cdb_hex": cdb_program(offset, BLOCK).hex(),
            }
            for offset, payload in PREPARE_WRITES
        ],
        "erases": [
            {"offset": offset, "cdb_hex": cdb_erase(offset).hex()}
            for offset in (TARGET_SECTOR, LOWER_SECTOR, UPPER_SECTOR)
        ],
        "source_sha256": {
            "experiment": _source_sha256(__file__),
            "writer": _source_sha256(_writer.__file__),
            "verifier": _source_sha256(_writer._verify.__file__),
        },
    }


def _plan_sha256():
    descriptor = plan_descriptor()
    encoded = json.dumps(
        descriptor, sort_keys=True, separators=(",", ":")).encode("ascii")
    return sha256_bytes(encoded)


PLAN_SHA256 = _plan_sha256()


def validate_v122_layout(manifest):
    """Refuse layouts other than the geometry used to bound this experiment."""
    geometry = tuple(
        (region.load, region.offset, region.length)
        for region in sorted(manifest.regions, key=lambda item: item.index))
    if geometry != EXPECTED_REGION_GEOMETRY:
        raise SafetyError(
            "manifest region geometry is not the reviewed V1.22 layout")
    if (manifest.scratch_lo, manifest.scratch_hi) != EXPECTED_SCRATCH:
        raise SafetyError(
            "manifest scratch gap is not the reviewed V1.22 gap")
    if not (manifest.scratch_lo <= ENVELOPE_LO
            and ENVELOPE_HI <= manifest.scratch_hi):
        raise SafetyError("guarded envelope is not wholly inside manifest scratch")


def validate_loader_window(image):
    """Pin the actual preserved loader bytes, not only its USB replies."""
    if len(image) != FLASH_SIZE:
        raise SafetyError("loader validation requires an exact 32-MiB image")
    loader_hash = sha256_bytes(
        image[LOADER_OFFSET:LOADER_OFFSET + LOADER_SIZE])
    if not hmac.compare_digest(loader_hash, EXPECTED_LOADER_SHA256):
        raise SafetyError(
            "preserved ISP loader hash is not the reviewed V1.22 loader: "
            f"expected {EXPECTED_LOADER_SHA256}, got {loader_hash}")
    return loader_hash


def validate_baseline_window(baseline, manifest):
    """Require the complete aligned containment envelope to be erased."""
    if len(baseline) != FLASH_SIZE:
        raise SafetyError("granularity test requires an exact 32-MiB baseline")
    validate_loader_window(baseline)
    validate_v122_layout(manifest)
    window = baseline[ENVELOPE_LO:ENVELOPE_HI]
    if window != b"\xff" * (ENVELOPE_HI - ENVELOPE_LO):
        first = next(index for index, value in enumerate(window) if value != 0xFF)
        raise SafetyError(
            "entire 256-KiB containment envelope must be erased; first "
            f"programmed byte is 0x{ENVELOPE_LO + first:x}")


def image_after_prepare_count(baseline, count):
    if not 0 <= count <= len(PREPARE_WRITES):
        raise ValueError("prepare count is outside the fixed plan")
    image = bytearray(baseline)
    for offset, payload in PREPARE_WRITES[:count]:
        image[offset:offset + BLOCK] = payload
    return bytes(image)


def prepared_image(baseline):
    return image_after_prepare_count(baseline, len(PREPARE_WRITES))


def target_erased_image(baseline):
    image = bytearray(baseline)
    image[LOWER_GUARD_OFFSET:LOWER_GUARD_OFFSET + BLOCK] = LOWER_GUARD
    image[UPPER_GUARD_OFFSET:UPPER_GUARD_OFFSET + BLOCK] = UPPER_GUARD
    return bytes(image)


def lower_cleaned_image(baseline):
    image = bytearray(baseline)
    image[UPPER_GUARD_OFFSET:UPPER_GUARD_OFFSET + BLOCK] = UPPER_GUARD
    return bytes(image)


def _image_hashes(baseline):
    return {
        "prepared_image_sha256": sha256_bytes(prepared_image(baseline)),
        "target_erased_image_sha256": sha256_bytes(
            target_erased_image(baseline)),
        "lower_cleaned_image_sha256": sha256_bytes(
            lower_cleaned_image(baseline)),
    }


def _static_state_fields(manifest, baseline_hash, image_hashes,
                         status, current_image_hash):
    return {
        "schema": STATE_SCHEMA,
        "status": status,
        "device_path": None,
        "identify_hex": None,
        "descriptor_sha256": None,
        "loader_fingerprint_sha256": None,
        "manifest_sha256": manifest.sha256,
        "loader_window_sha256": EXPECTED_LOADER_SHA256,
        "baseline_sha256": baseline_hash,
        "current_image_sha256": current_image_hash,
        "plan_sha256": PLAN_SHA256,
        "lower_guard_sha256": sha256_bytes(LOWER_GUARD),
        "target_payload_sha256": sha256_bytes(TARGET_PAYLOAD),
        "upper_guard_sha256": sha256_bytes(UPPER_GUARD),
        "prepared_image_sha256": image_hashes["prepared_image_sha256"],
        "target_erased_image_sha256": image_hashes[
            "target_erased_image_sha256"],
        "lower_cleaned_image_sha256": image_hashes[
            "lower_cleaned_image_sha256"],
        "envelope_lo": ENVELOPE_LO,
        "envelope_hi": ENVELOPE_HI,
        "lower_sector_offset": LOWER_SECTOR,
        "target_sector_offset": TARGET_SECTOR,
        "upper_sector_offset": UPPER_SECTOR,
        "block_size": BLOCK,
        "sector_size": SECTOR,
    }


def _state_fields(identity, manifest, baseline_hash, image_hashes,
                  status, current_image_hash):
    state = _static_state_fields(
        manifest, baseline_hash, image_hashes, status, current_image_hash)
    for key in (
            "device_path", "identify_hex", "descriptor_sha256",
            "loader_fingerprint_sha256"):
        state[key] = identity[key]
    return state


def _compare_state_value(key, got, wanted):
    if isinstance(wanted, str):
        if not isinstance(got, str) or not hmac.compare_digest(got, wanted):
            raise SafetyError(f"stage state {key} does not match this experiment")
    elif got != wanted or type(got) is not type(wanted):
        raise SafetyError(f"stage state {key} does not match this experiment")


def validate_static_state(state, manifest, baseline_hash, image_hashes,
                          status, current_image_hash):
    expected = _static_state_fields(
        manifest, baseline_hash, image_hashes, status, current_image_hash)
    if set(state) != set(expected):
        missing = sorted(set(expected) - set(state))
        extra = sorted(set(state) - set(expected))
        raise SafetyError(
            f"stage state fields differ (missing={missing}, extra={extra})")
    for key, wanted in expected.items():
        if key in (
                "device_path", "identify_hex", "descriptor_sha256",
                "loader_fingerprint_sha256"):
            continue
        _compare_state_value(key, state[key], wanted)

    device_path = state["device_path"]
    if not isinstance(device_path, str) or not device_path or len(device_path) > 256:
        raise SafetyError("stage state device_path is malformed")
    path_parts = device_path.split("-", 1)
    if (len(path_parts) != 2 or not path_parts[0].isdigit()
            or not path_parts[1]
            or any(not part.isdigit() for part in path_parts[1].split("."))):
        raise SafetyError("stage state device_path is malformed")

    if state["identify_hex"] != _writer.LOADER_IDENT.hex():
        raise SafetyError("stage state identify_hex is malformed")
    for key in ("descriptor_sha256", "loader_fingerprint_sha256"):
        value = state[key]
        if (not isinstance(value, str) or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)):
            raise SafetyError(f"stage state {key} is malformed")


def validate_connected_state(state, identity, manifest, baseline_hash,
                             image_hashes, status, current_image_hash):
    expected = _state_fields(
        identity, manifest, baseline_hash, image_hashes,
        status, current_image_hash)
    if set(state) != set(expected):
        raise SafetyError("stage state fields differ from the connected experiment")
    for key, wanted in expected.items():
        _compare_state_value(key, state[key], wanted)


def _require_absent_state(path):
    if os.path.lexists(path):
        raise SafetyError(
            "state file already exists; do not overwrite or replay an experiment")


def _write_initial_state(path, state):
    """Create the first started state without replacing any existing path."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise SafetyError("state file appeared before the mutation") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        raise


def _expected_stage_images(stage, baseline):
    if stage == "prepare":
        return baseline, prepared_image(baseline)
    if stage == "erase-target":
        return prepared_image(baseline), target_erased_image(baseline)
    if stage == "cleanup-lower":
        return target_erased_image(baseline), lower_cleaned_image(baseline)
    if stage == "cleanup-upper":
        return lower_cleaned_image(baseline), baseline
    raise ValueError("unknown experiment stage")


def _erase_offset(stage):
    return {
        "erase-target": TARGET_SECTOR,
        "cleanup-lower": LOWER_SECTOR,
        "cleanup-upper": UPPER_SECTOR,
    }[stage]


def _load_stage_state(stage, state_path, manifest, baseline_hash,
                      image_hashes, expected_before):
    if stage == "prepare":
        _require_absent_state(state_path)
        return None
    state = load_state(state_path)
    validate_static_state(
        state, manifest, baseline_hash, image_hashes,
        STAGE_INPUT_STATUS[stage], sha256_bytes(expected_before))
    return state


def execute_stage(stage, baseline, baseline_manifest, state_path,
                  progress=True, device_factory=WriteDevice, read_full_fn=None):
    """Execute one committed stage after all offline preconditions pass."""
    if stage not in STAGES:
        raise ValueError("unknown experiment stage")
    validate_baseline_window(baseline, baseline_manifest)
    baseline_hash = sha256_bytes(baseline)
    image_hashes = _image_hashes(baseline)
    expected_before, expected_after = _expected_stage_images(stage, baseline)
    saved_state = _load_stage_state(
        stage, state_path, baseline_manifest, baseline_hash,
        image_hashes, expected_before)

    dev = device_factory()
    mutation_attempted = False
    try:
        identity = query_loader_identity(dev)
        print(f"connected : {identity['device_path']} (loader identity accepted)")

        print("preflight : reading all 32 MiB through the SoC ...")
        before = capture_full_chip(
            dev, progress=progress, read_full_fn=read_full_fn)
        before_hash = require_exact_image(
            "fresh stage preimage", expected_before, before)
        print(f"preflight : exact expected image, sha256 {before_hash}")

        live_manifest = parse_manifest(before)
        validate_loader_window(before)
        validate_v122_layout(live_manifest)
        if not hmac.compare_digest(
                live_manifest.sha256, baseline_manifest.sha256):
            raise SafetyError("connected manifest differs from the baseline manifest")

        if stage == "prepare":
            _require_absent_state(state_path)
            current = before
            for index, (offset, payload) in enumerate(PREPARE_WRITES):
                started = _state_fields(
                    identity, live_manifest, baseline_hash, image_hashes,
                    f"prepare_block_{index + 1:02d}_started",
                    sha256_bytes(current))
                if index == 0:
                    _write_initial_state(state_path, started)
                else:
                    write_state_atomic(state_path, started)

                mode = set_address_mode_for_range(dev, offset, BLOCK)
                if mode != SUB_EX4B:
                    raise SafetyError(
                        "sub-16-MiB program did not select vendor F6 18 mode")
                print(
                    f"program   : block {index + 1:02d}/10 at 0x{offset:08x} "
                    "after F6 18")
                mutation_attempted = True
                dev.program(cdb_program(offset, BLOCK), payload)
                poll_ready(dev)

                expected = image_after_prepare_count(baseline, index + 1)
                current = capture_full_chip(
                    dev, progress=progress, read_full_fn=read_full_fn)
                current_hash = require_exact_image(
                    f"post-program block {index + 1:02d} full-chip image",
                    expected, current)
                mutation_attempted = False
                status = (
                    "prepared_verified" if index + 1 == len(PREPARE_WRITES)
                    else f"prepare_block_{index + 1:02d}_verified")
                write_state_atomic(
                    state_path,
                    _state_fields(
                        identity, live_manifest, baseline_hash, image_hashes,
                        status, current_hash))

            print("PASS: target sector and both boundary guards prepared exactly.")
            print("A fresh USB session may now run stage erase-target.")
            return 0

        validate_connected_state(
            saved_state, identity, live_manifest, baseline_hash,
            image_hashes, STAGE_INPUT_STATUS[stage], before_hash)
        offset = _erase_offset(stage)
        started = _state_fields(
            identity, live_manifest, baseline_hash, image_hashes,
            STAGE_STARTED_STATUS[stage], before_hash)
        write_state_atomic(state_path, started)

        mode = set_address_mode_for_range(dev, offset, SECTOR)
        if mode != SUB_EX4B:
            raise SafetyError(
                "sub-16-MiB erase did not select vendor F6 18 mode")
        print(f"erase     : sector 0x{offset:08x} after F6 18")
        mutation_attempted = True
        dev.cmd(cdb_erase(offset))
        poll_ready(dev)

        print("postflight: reading all 32 MiB through the SoC ...")
        after = capture_full_chip(
            dev, progress=progress, read_full_fn=read_full_fn)
        after_hash = require_exact_image(
            "post-erase full-chip image", expected_after, after)
        mutation_attempted = False
        print(f"postflight: exact expected image, sha256 {after_hash}")

        if stage == "cleanup-upper":
            clear_state(state_path)
            if os.path.lexists(state_path):
                raise SafetyError("final state authorization could not be removed")
            print("PASS: exact original 32-MiB baseline restored; state cleared.")
        else:
            write_state_atomic(
                state_path,
                _state_fields(
                    identity, live_manifest, baseline_hash, image_hashes,
                    STAGE_OUTPUT_STATUS[stage], after_hash))
            if stage == "erase-target":
                print(
                    "PASS: all 4,096 target bytes erased and both boundary "
                    "guards survived exactly.")
            else:
                print("PASS: lower guard sector cleaned; upper guard remains.")
        return 0
    except KeyboardInterrupt as exc:
        if mutation_attempted:
            raise MutationResultUnknown(
                "operator interruption occurred after the mutation began") from exc
        raise
    except Exception as exc:
        if mutation_attempted and not isinstance(exc, MutationResultUnknown):
            raise MutationResultUnknown(
                "mutation may have occurred, but exact verification did not "
                f"complete: {exc}") from exc
        raise
    finally:
        dev.close()


def _print_plan(stage, baseline, baseline_hash, manifest, image_hashes):
    before, after = _expected_stage_images(stage, baseline)
    print(f"stage     : {stage}")
    print(f"target    : 0x{TARGET_SECTOR:08x}")
    print(
        f"guards    : 0x{LOWER_GUARD_OFFSET:08x}, "
        f"0x{UPPER_GUARD_OFFSET:08x}")
    print(
        f"envelope  : [0x{ENVELOPE_LO:x},0x{ENVELOPE_HI:x}) all 0xff")
    print(
        f"scratch   : [0x{manifest.scratch_lo:x},0x{manifest.scratch_hi:x}) "
        "from V1.22 manifest")
    print(f"loader    : sha256 {EXPECTED_LOADER_SHA256}")
    print(f"baseline  : sha256 {baseline_hash}")
    print(f"preimage  : sha256 {sha256_bytes(before)}")
    print(f"postimage : sha256 {sha256_bytes(after)}")
    print("pre/post  : F6 17, exact 32-MiB reads")
    if stage == "prepare":
        print("mutation  : ten separate F6 18 + one-block F6 06 operations")
        for offset, _payload in PREPARE_WRITES:
            print(f"            {cdb_program(offset, BLOCK).hex(' ')}")
    else:
        offset = _erase_offset(stage)
        print(f"mutation  : F6 18, then {cdb_erase(offset).hex(' ')}")
    print(f"plan      : sha256 {PLAN_SHA256}")
    if stage != "prepare":
        print(
            f"state     : requires {STAGE_INPUT_STATUS[stage]} "
            f"({sha256_bytes(before)[:12]}... preimage binding)")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--baseline", required=True,
                        help="fresh exact 32-MiB baseline from this keyboard")
    parser.add_argument("--state-file", default=DEFAULT_STATE,
                        help=f"stage authorization file (default: {DEFAULT_STATE})")
    parser.add_argument("--commit", action="store_true",
                        help="actually send the fixed reviewed mutation commands")
    args = parser.parse_args()

    try:
        if _paths_are_same(args.baseline, args.state_file):
            raise SafetyError("baseline and state file must be different paths")
        baseline = load_baseline(args.baseline)
        manifest = parse_manifest(baseline)
        validate_baseline_window(baseline, manifest)
        baseline_hash = sha256_bytes(baseline)
        image_hashes = _image_hashes(baseline)
        expected_before, _expected_after = _expected_stage_images(
            args.stage, baseline)
        _load_stage_state(
            args.stage, args.state_file, manifest, baseline_hash,
            image_hashes, expected_before)

        _print_plan(
            args.stage, baseline, baseline_hash, manifest, image_hashes)
        if not args.commit:
            print("\nDRY RUN -- baseline, layout, envelope, plan and state checks only.")
            print("No USB device was opened and nothing was sent or changed.")
            return 0

        print("\nCOMMIT REQUESTED -- external SPI recovery may still be required.")
        return execute_stage(
            args.stage, baseline, manifest, args.state_file)
    except MutationResultUnknown as exc:
        print(f"\nUNKNOWN RESULT: {exc}", file=sys.stderr)
        print(
            "Do not retry or advance this USB experiment. Read the whole chip "
            "externally and restore", file=sys.stderr)
        print(
            "the verified baseline over the proven SPI path if any byte differs.",
            file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nABORT: interrupted before a flash mutation began", file=sys.stderr)
        return 130
    except (SafetyError, RuntimeError, ValueError, OSError) as exc:
        print(f"\nABORT: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
