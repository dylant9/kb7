#!/usr/bin/env python3
"""KB7 USB-ISP write-path validation -- destructive, dry-run by default.

This is a two-stage laboratory experiment, not a firmware flasher:

1. ``program`` writes one 512-byte marker into a manifest-derived scratch
   sector and verifies the exact expected 32-MiB image.
2. ``erase`` is unlocked only by that verified result. It issues the vendor's
   sector-erase path for the marked target and again requires an exact 32-MiB
   image match.

Both stages require an exact 32-MiB owner-supplied baseline which is compared
with a fresh full-chip USB read before any mutation. The program and erase
encodings are recovered, but the erase handler has not been exercised on this
loader. If it interprets F6 15 differently, it can erase the boot chain. Keep a
tested SPI programmer and two matching full-chip backups available.

Examples (the first invocation is dry-run only):

  sudo python3 kb7-isp-write2.py --stage program \
      --baseline <full-chip-backup.bin>
  sudo python3 kb7-isp-write2.py --stage program \
      --baseline <full-chip-backup.bin> --commit
  sudo python3 kb7-isp-write2.py --stage erase \
      --baseline <full-chip-backup.bin> --commit
"""

import argparse
import ctypes as ct
from dataclasses import dataclass
import hashlib
import hmac
import importlib.util
import json
import os
import struct
import sys
import tempfile
import time


_spec = importlib.util.spec_from_file_location(
    "kb7isp_verify",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "kb7-isp-verify.py"))
_verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_verify)

Device = _verify.Device
cdb_read = _verify.cdb_read
cdb_simple = _verify.cdb_simple
parse_csw = _verify.parse_csw
fwin = _verify.fwin

FLASH_BASE = _verify.FLASH_BASE
FLASH_SIZE = _verify.FLASH_SIZE
BLOCK = _verify.BLOCK
CHUNK = _verify.CHUNK
SECTOR = 0x1000
ADDRESS_MODE_BOUNDARY = 0x61000000

SUB_IDENTIFY = _verify.SUB_IDENTIFY
SUB_STATUS = _verify.SUB_STATUS
SUB_READ = _verify.SUB_READ
SUB_EN4B = _verify.SUB_EN4B
SUB_DESC = _verify.SUB_DESC
SUB_PROGRAM = 0x06
SUB_ERASE = 0x15
SUB_EX4B = 0x18

MANIFEST_OFFSET = 0x10000
MANIFEST_SIZE = 0x1000
FIXED_BOOT_END = MANIFEST_OFFSET + MANIFEST_SIZE
BOOT_CONFIGURATION_OFFSET = 0x200
BOOT_CONFIGURATION_MAGIC = b"SN_BCFG\x00"
MANIFEST_PREFIX = b"SN_FWIN\x00v1.0.00\x00"
HEADER_MAGIC = b"SNC7320A"
LOADER_IDENT_PREFIX = b"\x01\x01"
LOADER_DESCRIPTOR_MARKER = b"v0.001 test!"
EXPECTED_LOADS = (0x00000000, 0x10000000, 0x60100000, 0x18000000)
MANIFEST_ENTRIES = (0x20, 0x30, 0x40, 0x50)

STATE_SCHEMA = "kb7-isp-write2-state-v2"
STATE_READY = "program_verified"
STATE_ERASE_STARTED = "erase_started"
DEFAULT_STATE = os.path.expanduser("~/.kb7-isp-write2-state.json")

# One block, mostly 0xff. No byte clears more than two bits.
MARKER = bytes((0xFF ^ ((i * 7 + 1) & 0x03)) for i in range(BLOCK))


class SafetyError(RuntimeError):
    """A fail-closed precondition or verification failure."""


class MutationResultUnknown(SafetyError):
    """A command may have mutated flash but could not be verified."""


@dataclass(frozen=True)
class Region:
    index: int
    load: int
    store: int
    offset: int
    length: int
    checksum: int

    @property
    def end(self):
        return self.offset + self.length


@dataclass(frozen=True)
class ManifestInfo:
    sha256: str
    regions: tuple
    scratch_lo: int
    scratch_hi: int


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def load_baseline(path):
    """Read one immutable, exact-size baseline or refuse it."""
    with open(path, "rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        if size != FLASH_SIZE:
            raise SafetyError(
                f"baseline must be exactly {FLASH_SIZE} bytes (32 MiB); got {size}")
        data = stream.read()
    if len(data) != FLASH_SIZE:
        raise SafetyError(
            f"baseline changed or was short while reading: got {len(data)} bytes")
    return data


def _align_up(value, alignment):
    return (value + alignment - 1) & ~(alignment - 1)


def _align_down(value, alignment):
    return value & ~(alignment - 1)


def _ranges_overlap(a_lo, a_hi, b_lo, b_hi):
    return a_lo < b_hi and b_lo < a_hi


def parse_manifest(image):
    """Validate the KB7 header, manifest mappings, and every declared CRC."""
    if len(image) != FLASH_SIZE:
        raise SafetyError(
            f"manifest source must be an exact 32-MiB image; got {len(image)} bytes")
    if image[:len(HEADER_MAGIC)] != HEADER_MAGIC:
        raise SafetyError("unexpected flash header; expected SNC7320A")

    boot_configuration = image[
        BOOT_CONFIGURATION_OFFSET:BOOT_CONFIGURATION_OFFSET + 16]
    if boot_configuration[:8] != BOOT_CONFIGURATION_MAGIC:
        raise SafetyError("unexpected SN_BCFG boot configuration")
    primary_manifest, secondary_manifest = struct.unpack_from(
        "<II", boot_configuration, 8)
    if primary_manifest != FLASH_BASE + MANIFEST_OFFSET or secondary_manifest != 0:
        raise SafetyError("boot configuration does not select the expected manifest")

    manifest = image[MANIFEST_OFFSET:MANIFEST_OFFSET + MANIFEST_SIZE]
    if manifest[:len(MANIFEST_PREFIX)] != MANIFEST_PREFIX:
        raise SafetyError("unexpected SN_FWIN manifest magic or version")

    first_store, marker, generation, reserved = struct.unpack_from(
        "<IIII", manifest, 0x10)
    if marker != 0xFFFFFFFF or generation != 1 or reserved != 0xFFFFFFFF:
        raise SafetyError("unexpected SN_FWIN manifest header fields")

    regions = []
    zero_mapping = None
    for index, (entry_offset, expected_load) in enumerate(
            zip(MANIFEST_ENTRIES, EXPECTED_LOADS)):
        load, store, length, checksum = struct.unpack_from(
            "<IIII", manifest, entry_offset)
        if load != expected_load:
            raise SafetyError(
                f"manifest mapping {index} has unexpected load address 0x{load:08x}")
        if not (FLASH_BASE <= store <= FLASH_BASE + FLASH_SIZE):
            raise SafetyError(
                f"manifest mapping {index} store address is outside flash")
        offset = store - FLASH_BASE

        if index == 3:
            if length != 0 or checksum != 0:
                raise SafetyError("manifest zero-length SRAM mapping is malformed")
            zero_mapping = (load, store)
            continue

        if length == 0:
            raise SafetyError(f"manifest region {index} is empty")
        if offset < FIXED_BOOT_END or offset + length > FLASH_SIZE:
            raise SafetyError(f"manifest region {index} lies outside its flash window")
        if offset % BLOCK:
            raise SafetyError(f"manifest region {index} store address is unaligned")
        calculated = fwin(image[offset:offset + length])
        if calculated != checksum:
            raise SafetyError(
                f"manifest region {index} checksum mismatch: "
                f"declared 0x{checksum:08x}, calculated 0x{calculated:08x}")
        regions.append(Region(index, load, store, offset, length, checksum))

    if first_store != regions[0].store:
        raise SafetyError("manifest first-store field does not match region 0")
    if zero_mapping is None or zero_mapping[1] != regions[1].store:
        raise SafetyError("manifest zero-length SRAM mapping has an unexpected store")

    ordered = sorted(regions, key=lambda item: item.offset)
    for left, right in zip(ordered, ordered[1:]):
        if left.end > right.offset:
            raise SafetyError(
                f"manifest regions {left.index} and {right.index} overlap")

    app = next((region for region in regions if region.load == 0x10000000), None)
    assets = next((region for region in regions if region.load == 0x60100000), None)
    if app is None or assets is None or app.end > assets.offset:
        raise SafetyError("cannot derive the application-to-assets scratch gap")
    scratch_lo = _align_up(app.end, SECTOR)
    scratch_hi = _align_down(assets.offset, SECTOR)
    if scratch_hi - scratch_lo < SECTOR:
        raise SafetyError("manifest exposes no complete scratch sector")

    return ManifestInfo(
        sha256=sha256_bytes(manifest),
        regions=tuple(regions),
        scratch_lo=scratch_lo,
        scratch_hi=scratch_hi)


def validate_target(manifest, baseline, offset):
    """Require one wholly erased sector in the manifest-derived scratch gap."""
    if offset % SECTOR:
        raise SafetyError("the coupled program/erase target must be sector-aligned")
    end = offset + SECTOR
    if offset < 0 or end > FLASH_SIZE:
        raise SafetyError("target sector lies outside the 32-MiB flash")
    if not (manifest.scratch_lo <= offset and end <= manifest.scratch_hi):
        raise SafetyError(
            f"target 0x{offset:x}..0x{end:x} is outside manifest-derived scratch "
            f"[0x{manifest.scratch_lo:x},0x{manifest.scratch_hi:x})")
    if _ranges_overlap(offset, end, 0, FIXED_BOOT_END):
        raise SafetyError("target overlaps the header, loader, or manifest")
    for region in manifest.regions:
        if _ranges_overlap(offset, end, region.offset, region.end):
            raise SafetyError(f"target overlaps manifest region {region.index}")
    sector = baseline[offset:end]
    if sector != b"\xff" * SECTOR:
        first = next(i for i, value in enumerate(sector) if value != 0xFF)
        raise SafetyError(
            f"entire target sector must be erased; first programmed byte is "
            f"0x{offset + first:x}")


def _validate_flash_range(offset, length):
    if offset < 0 or length <= 0 or offset + length > FLASH_SIZE:
        raise ValueError("operation lies outside the 32-MiB flash")


def cdb_program(offset, nbytes):
    """F6 06: BE32 absolute raw address, BE16 count of 512-byte blocks."""
    _validate_flash_range(offset, nbytes)
    if offset % BLOCK or nbytes % BLOCK:
        raise ValueError("program offset and length must be 512-byte aligned")
    count = nbytes // BLOCK
    if count > 0xFFFF:
        raise ValueError("program block count does not fit the CDB")
    address = FLASH_BASE + offset
    if address > 0xFFFFFFFF:
        raise ValueError("program address does not fit the CDB")
    return (bytes([0xF6, SUB_PROGRAM, 0x00])
            + struct.pack(">I", address)
            + struct.pack(">H", count)
            + bytes(7))


def cdb_erase(offset):
    """F6 15: BE16 512-byte block index; vendor 4-KiB path, no count."""
    _validate_flash_range(offset, SECTOR)
    if offset % SECTOR:
        raise ValueError("erase offset must be sector-aligned")
    index = offset >> 9
    if index > 0xFFFF:
        raise ValueError("erase block index does not fit F6 15")
    return (bytes([0xF6, SUB_ERASE, 0x00])
            + struct.pack(">H", index)
            + bytes(11))


def address_mode_subcode(offset, length):
    """Mirror the vendor's strict absolute-end boundary decision."""
    _validate_flash_range(offset, length)
    absolute_end = FLASH_BASE + offset + length
    return SUB_EN4B if absolute_end > ADDRESS_MODE_BOUNDARY else SUB_EX4B


class WriteDevice(Device):
    """Strict BOT transport with only the two reviewed mutation subcodes added."""

    clear_halt_on_error = False

    # F6 06 is deliberately absent: it can only be sent through program(),
    # which enforces the data-OUT length against the encoded block count.
    _WRITE_ALLOWED = frozenset(
        set(_verify._ALLOWED) | {SUB_ERASE, SUB_EX4B})

    def cmd(self, cdb, data_len=0):
        return self._command(cdb, data_len, self._WRITE_ALLOWED)

    def program(self, cdb, data):
        if len(cdb) != 16 or cdb[0] != 0xF6 or cdb[1] != SUB_PROGRAM:
            raise ValueError("program requires one reviewed 16-byte F6 06 CDB")
        expected = int.from_bytes(cdb[7:9], "big") * BLOCK
        if expected != len(data):
            raise ValueError(
                f"program data length {len(data)} does not match CDB length {expected}")
        self.tag = (self.tag + 1) & 0xFFFFFFFF
        cbw = (struct.pack(
            "<IIIBBB", 0x43425355, self.tag, len(data), 0x00, 0, 16) + cdb)
        self._xfer_exact(
            self.ep_out, ct.create_string_buffer(cbw, 31), 31, "CBW")
        self._xfer_exact(
            self.ep_out, ct.create_string_buffer(bytes(data), len(data)),
            len(data), "data-OUT")
        csw = ct.create_string_buffer(13)
        self._xfer_exact(self.ep_in, csw, 13, "CSW")
        return parse_csw(bytes(csw.raw[:13]), self.tag)


def set_address_mode_for_range(dev, offset, length):
    subcode = address_mode_subcode(offset, length)
    dev.cmd(cdb_simple(subcode))
    return subcode


def read_range(dev, offset, length, chunk=CHUNK, progress=False):
    _validate_flash_range(offset, length)
    if offset % BLOCK or length % BLOCK:
        raise ValueError("read offset and length must be 512-byte aligned")
    if chunk <= 0 or chunk % BLOCK or chunk > 0x1000:
        raise ValueError("read chunk must be a 512-byte multiple no larger than 4 KiB")

    output = bytearray()
    next_report = 0x200000
    while len(output) < length:
        count = min(chunk, length - len(output))
        data, _status, _residue = dev.cmd(
            cdb_read(offset + len(output), count), count)
        if len(data) != count:
            raise RuntimeError(
                f"short verification read at 0x{offset + len(output):x}: "
                f"got {len(data)}/{count}")
        output.extend(data)
        if progress and len(output) >= next_report:
            print(f"\r    {100.0 * len(output) / length:5.1f}%", end="", flush=True)
            next_report += 0x200000
    if progress:
        print("\r    100.0%")
    if len(output) != length:
        raise RuntimeError("verification read returned an unexpected total length")
    return bytes(output)


def capture_full_chip(dev, progress=True, read_full_fn=None):
    mode = set_address_mode_for_range(dev, 0, FLASH_SIZE)
    if mode != SUB_EN4B:
        raise AssertionError("full-chip capture did not select F6 17")
    if read_full_fn is None:
        return read_range(dev, 0, FLASH_SIZE, progress=progress)
    data = read_full_fn(dev)
    if len(data) != FLASH_SIZE:
        raise RuntimeError(
            f"short full-chip capture: got {len(data)}/{FLASH_SIZE}")
    return bytes(data)


def poll_ready(dev, timeout=30.0, interval=0.02,
               clock=time.monotonic, sleeper=time.sleep):
    deadline = clock() + timeout
    while True:
        status, _csw_status, _residue = dev.cmd(cdb_simple(SUB_STATUS), 1)
        if len(status) != 1:
            raise RuntimeError(f"status command returned {len(status)} bytes, expected 1")
        if not (status[0] & 0x01):
            return
        if clock() >= deadline:
            raise RuntimeError(f"flash remained busy for more than {timeout:.1f} seconds")
        sleeper(interval)


def query_loader_identity(dev):
    identify, _status, _residue = dev.cmd(cdb_simple(SUB_IDENTIFY), 8)
    descriptor, _status, _residue = dev.cmd(cdb_simple(SUB_DESC), 36)
    if len(identify) != 8 or not identify.startswith(LOADER_IDENT_PREFIX):
        raise SafetyError("unexpected F6 00 loader identity")
    if len(descriptor) != 36 or LOADER_DESCRIPTOR_MARKER not in descriptor:
        raise SafetyError("unexpected F6 F1 loader descriptor")
    device_path = getattr(dev, "device_path", "")
    if not device_path:
        raise SafetyError("USB topology path is unavailable; device binding is impossible")
    return {
        "device_path": device_path,
        "identify_hex": identify.hex(),
        "descriptor_sha256": sha256_bytes(descriptor),
        "loader_fingerprint_sha256": sha256_bytes(identify + descriptor),
    }


def image_with_marker(baseline, offset):
    image = bytearray(baseline)
    image[offset:offset + len(MARKER)] = MARKER
    return bytes(image)


def difference_summary(expected, actual, limit=8):
    if len(expected) != len(actual):
        return abs(len(expected) - len(actual)), [(0, max(len(expected), len(actual)) - 1)]
    count = 0
    ranges = []
    start = previous = None
    for index, (wanted, got) in enumerate(zip(expected, actual)):
        if wanted == got:
            continue
        count += 1
        if start is None:
            start = previous = index
        elif index == previous + 1:
            previous = index
        else:
            if len(ranges) < limit:
                ranges.append((start, previous))
            start = previous = index
    if start is not None and len(ranges) < limit:
        ranges.append((start, previous))
    return count, ranges


def require_exact_image(label, expected, actual):
    if len(expected) != FLASH_SIZE or len(actual) != FLASH_SIZE:
        raise SafetyError(
            f"{label} requires two exact 32-MiB images; got "
            f"{len(expected)} and {len(actual)} bytes")
    expected_hash = sha256_bytes(expected)
    actual_hash = sha256_bytes(actual)
    if not hmac.compare_digest(expected_hash, actual_hash) or expected != actual:
        count, ranges = difference_summary(expected, actual)
        locations = ", ".join(
            f"0x{start:x}-0x{end:x}" for start, end in ranges)
        raise SafetyError(
            f"{label} mismatch: {count} differing bytes; first ranges: "
            f"{locations or 'unavailable'}; expected {expected_hash}, got {actual_hash}")
    return actual_hash


def _state_fields(identity, manifest, baseline_hash, offset, programmed_hash, status):
    return {
        "schema": STATE_SCHEMA,
        "status": status,
        "offset": offset,
        "sector_size": SECTOR,
        "marker_length": len(MARKER),
        "device_path": identity["device_path"],
        "identify_hex": identity["identify_hex"],
        "descriptor_sha256": identity["descriptor_sha256"],
        "loader_fingerprint_sha256": identity["loader_fingerprint_sha256"],
        "manifest_sha256": manifest.sha256,
        "baseline_sha256": baseline_hash,
        "marker_sha256": sha256_bytes(MARKER),
        "programmed_image_sha256": programmed_hash,
    }


def _static_state_fields(manifest, baseline_hash, offset, programmed_hash):
    return {
        "schema": STATE_SCHEMA,
        "status": STATE_READY,
        "offset": offset,
        "sector_size": SECTOR,
        "marker_length": len(MARKER),
        "manifest_sha256": manifest.sha256,
        "baseline_sha256": baseline_hash,
        "marker_sha256": sha256_bytes(MARKER),
        "programmed_image_sha256": programmed_hash,
    }


def load_state(path):
    if os.path.islink(path):
        raise SafetyError("state file may not be a symbolic link")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            if os.fstat(stream.fileno()).st_size > 16384:
                raise SafetyError("state file is unexpectedly large")
            state = json.load(stream)
    except FileNotFoundError as exc:
        raise SafetyError("no verified program-stage state; run stage program first") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SafetyError(f"cannot read a valid stage state: {exc}") from exc
    if not isinstance(state, dict):
        raise SafetyError("stage state is not a JSON object")
    return state


def validate_state(state, expected):
    if set(state) != set(expected):
        missing = sorted(set(expected) - set(state))
        extra = sorted(set(state) - set(expected))
        raise SafetyError(f"stage state fields differ (missing={missing}, extra={extra})")
    for key, wanted in expected.items():
        got = state[key]
        if isinstance(wanted, str):
            if not isinstance(got, str) or not hmac.compare_digest(got, wanted):
                raise SafetyError(f"stage state {key} does not match this experiment")
        elif got != wanted or type(got) is not type(wanted):
            raise SafetyError(f"stage state {key} does not match this experiment")


def validate_static_state(state, manifest, baseline_hash, offset, programmed_hash):
    expected = _static_state_fields(
        manifest, baseline_hash, offset, programmed_hash)
    required_keys = set(expected) | {
        "device_path",
        "identify_hex",
        "descriptor_sha256",
        "loader_fingerprint_sha256",
    }
    if set(state) != required_keys:
        missing = sorted(required_keys - set(state))
        extra = sorted(set(state) - required_keys)
        raise SafetyError(
            f"stage state fields differ (missing={missing}, extra={extra})")
    for key, wanted in expected.items():
        got = state[key]
        if isinstance(wanted, str):
            if not isinstance(got, str) or not hmac.compare_digest(got, wanted):
                raise SafetyError(f"stage state {key} does not match this experiment")
        elif got != wanted or type(got) is not type(wanted):
            raise SafetyError(f"stage state {key} does not match this experiment")

    device_path = state["device_path"]
    if not isinstance(device_path, str) or not device_path or len(device_path) > 256:
        raise SafetyError("stage state device_path is malformed")
    path_parts = device_path.split("-", 1)
    if (len(path_parts) != 2 or not path_parts[0].isdigit()
            or not path_parts[1]
            or any(not part.isdigit() for part in path_parts[1].split("."))):
        raise SafetyError("stage state device_path is malformed")

    hexadecimal_fields = {
        "identify_hex": 16,
        "descriptor_sha256": 64,
        "loader_fingerprint_sha256": 64,
    }
    for key, length in hexadecimal_fields.items():
        value = state[key]
        if (not isinstance(value, str) or len(value) != length
                or any(character not in "0123456789abcdef" for character in value)):
            raise SafetyError(f"stage state {key} is malformed")


def write_state_atomic(path, state):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".kb7-isp-write2-state.", dir=directory, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def clear_state(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _paths_are_same(first, second):
    if os.path.abspath(first) == os.path.abspath(second):
        return True
    try:
        return os.path.samefile(first, second)
    except (FileNotFoundError, OSError):
        return False


def execute_stage(stage, offset, baseline, baseline_manifest, state_path,
                  progress=True, device_factory=WriteDevice, read_full_fn=None):
    """Execute one committed stage. All callers must validate baseline first."""
    if stage not in ("program", "erase"):
        raise ValueError("stage must be program or erase")
    if len(baseline) != FLASH_SIZE:
        raise SafetyError("committed stage requires an exact 32-MiB baseline")
    validate_target(baseline_manifest, baseline, offset)
    baseline_hash = sha256_bytes(baseline)
    programmed = image_with_marker(baseline, offset)
    programmed_hash = sha256_bytes(programmed)
    saved_state = None
    if stage == "erase":
        saved_state = load_state(state_path)
        validate_static_state(
            saved_state, baseline_manifest, baseline_hash, offset, programmed_hash)

    dev = device_factory()
    mutation_attempted = False
    try:
        identity = query_loader_identity(dev)
        print(f"connected : {identity['device_path']} (loader identity accepted)")

        print("preflight : reading all 32 MiB through the SoC ...")
        before = capture_full_chip(
            dev, progress=progress, read_full_fn=read_full_fn)
        expected_before = baseline if stage == "program" else programmed
        before_hash = require_exact_image(
            "fresh pre-mutation device image", expected_before, before)
        print(f"preflight : exact expected image, sha256 {before_hash}")

        live_manifest = parse_manifest(before)
        if not hmac.compare_digest(live_manifest.sha256, baseline_manifest.sha256):
            raise SafetyError("connected manifest differs from the baseline manifest")
        validate_target(live_manifest, baseline, offset)

        if stage == "erase":
            expected_state = _state_fields(
                identity, live_manifest, baseline_hash, offset,
                programmed_hash, STATE_READY)
            validate_state(saved_state, expected_state)
            expected_sector = bytearray(b"\xff" * SECTOR)
            expected_sector[:len(MARKER)] = MARKER
            if before[offset:offset + SECTOR] != bytes(expected_sector):
                raise SafetyError(
                    "erase precondition failed: sector is not exactly marker plus 0xff")
        else:
            # A ready state from an older run must never authorize this new run.
            clear_state(state_path)

        mutation_length = len(MARKER) if stage == "program" else SECTOR
        mode = set_address_mode_for_range(dev, offset, mutation_length)
        if mode != SUB_EX4B:
            raise SafetyError("sub-16-MiB mutation did not select vendor F6 18 mode")
        print("mode      : F6 18 (vendor sub-16-MiB path)")

        if stage == "program":
            command = cdb_program(offset, len(MARKER))
            mutation_attempted = True
            dev.program(command, MARKER)
        else:
            command = cdb_erase(offset)
            started_state = dict(saved_state)
            started_state["status"] = STATE_ERASE_STARTED
            write_state_atomic(state_path, started_state)
            mutation_attempted = True
            dev.cmd(command)

        poll_ready(dev)
        print("postflight: reading all 32 MiB through the SoC ...")
        after = capture_full_chip(
            dev, progress=progress, read_full_fn=read_full_fn)
        expected_after = programmed if stage == "program" else baseline
        after_hash = require_exact_image(
            "post-mutation full-chip image", expected_after, after)
        print(f"postflight: exact expected image, sha256 {after_hash}")

        if stage == "program":
            ready_state = _state_fields(
                identity, live_manifest, baseline_hash, offset,
                programmed_hash, STATE_READY)
            write_state_atomic(state_path, ready_state)
            print("PASS: marker programmed exactly; erase stage is now authorized.")
        else:
            clear_state(state_path)
            print("PASS: marker removed at the encoded target; exact baseline restored.")
        return 0
    except KeyboardInterrupt as exc:
        if mutation_attempted:
            raise MutationResultUnknown(
                "operator interruption occurred after the mutation began") from exc
        raise
    except Exception as exc:
        if mutation_attempted and not isinstance(exc, MutationResultUnknown):
            raise MutationResultUnknown(
                f"mutation may have occurred, but verification did not complete: {exc}") from exc
        raise
    finally:
        dev.close()


def _print_plan(stage, offset, baseline_hash, manifest):
    mutation_length = len(MARKER) if stage == "program" else SECTOR
    mode = address_mode_subcode(offset, mutation_length)
    command = (cdb_program(offset, len(MARKER))
               if stage == "program" else cdb_erase(offset))
    print(f"stage     : {stage}")
    print(f"target    : 0x{offset:08x}")
    print(f"scratch   : [0x{manifest.scratch_lo:x},0x{manifest.scratch_hi:x}) from manifest")
    print(f"baseline  : sha256 {baseline_hash}")
    print("pre/post  : F6 17, exact 32-MiB read")
    print(f"mutation  : F6 {mode:02x}, then {command.hex(' ')}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=("program", "erase"), required=True)
    parser.add_argument("--offset", type=lambda value: int(value, 0), default=0x8E000)
    parser.add_argument("--baseline", required=True,
                        help="exact 32-MiB baseline captured from this keyboard")
    parser.add_argument("--state-file", default=DEFAULT_STATE,
                        help=f"stage authorization file (default: {DEFAULT_STATE})")
    parser.add_argument("--commit", action="store_true",
                        help="actually send the reviewed mutation command")
    args = parser.parse_args()

    try:
        if _paths_are_same(args.baseline, args.state_file):
            raise SafetyError("baseline and state file must be different paths")
        baseline = load_baseline(args.baseline)
        manifest = parse_manifest(baseline)
        validate_target(manifest, baseline, args.offset)
        baseline_hash = sha256_bytes(baseline)
        programmed_hash = sha256_bytes(image_with_marker(baseline, args.offset))

        if args.stage == "erase":
            state = load_state(args.state_file)
            validate_static_state(
                state, manifest, baseline_hash, args.offset, programmed_hash)

        _print_plan(args.stage, args.offset, baseline_hash, manifest)
        if not args.commit:
            print("\nDRY RUN -- baseline, manifest, target, and state checks only.")
            print("No USB device was opened and nothing was sent or changed.")
            return 0

        print("\nCOMMIT REQUESTED -- this operation can require full-chip SPI recovery.")
        return execute_stage(
            args.stage, args.offset, baseline, manifest, args.state_file)
    except MutationResultUnknown as exc:
        print(f"\nUNKNOWN RESULT: {exc}", file=sys.stderr)
        print("Do not retry over USB. Read the chip externally and recover with the",
              file=sys.stderr)
        print("verified full-chip SPI procedure if any byte differs.", file=sys.stderr)
        return 3
    except (SafetyError, RuntimeError, ValueError, OSError) as exc:
        print(f"\nABORT: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
