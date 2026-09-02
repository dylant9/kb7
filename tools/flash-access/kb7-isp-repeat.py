#!/usr/bin/env python3
"""
KB7 fixed ISP read-reliability gate -- STRICTLY READ-ONLY.

The preserved V1.22 loader can complete an F6 05/BOT exchange with a valid CSW
while returning incorrect data. A captured failure contained corruption on
exact 4-KiB command boundaries: zero-filled pages, stale pages and pages read
from half the requested address. Repetition alone is therefore insufficient;
stable-but-wrong data must also fail against the exact owner baseline.

Default execution is a local dry run. ``--commit`` opens 10f5:5037 and uses
only F6 00, F6 F1, F6 17 and F6 05. Program and erase commands are
unrepresentable. The fixed sweep tests five reviewed 4-KiB ranges at 512-B,
1-KiB, 2-KiB and 4-KiB command sizes. Every pass must be byte-exact against
the pinned baseline. Any transport error, distinct result or stable wrong
result makes the process fail.

Usage:
    sudo python3 kb7-isp-repeat.py \
        --reference /absolute/path/kb7-usb-full-cswfix-1.bin
    sudo python3 kb7-isp-repeat.py \
        --reference /absolute/path/kb7-usb-full-cswfix-1.bin --commit
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


TOOL_DIRECTORY = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "kb7isp_for_read_reliability", TOOL_DIRECTORY / "kb7-isp-verify.py")
if _spec is None or _spec.loader is None:
    raise RuntimeError("could not load the read-only ISP transport")
_verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_verify)

FLASH_SIZE = _verify.FLASH_SIZE
BLOCK = _verify.BLOCK
EXPECTED_REFERENCE_SHA256 = (
    "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f")
EXPECTED_VERIFIER_SOURCE_SHA256 = (
    "9b19d393cf64c66168e08de2f3d4fe352a85a2fd69545e374dee0fa015dea338")
EXPECTED_PLAN_SHA256 = "b1f80b218d832d323873ae2225847caf01c280694aa5df10c90c041a3dbe6f94"
EXPECTED_TOOL_DESCRIPTOR_SHA256 = "c38b3ee1435734b483ec4fed3fe3315d31d427e2e6c4fa751b90806f75101a9c"
FIXED_LENGTH = 0x1000
FIXED_PASSES = 20
FIXED_CHUNKS = (0x200, 0x400, 0x800, 0x1000)
FIXED_RANGES = (
    ("first-observed-command-failure", 0x00015000),
    ("repaired-core1-instruction", 0x00040000),
    ("observed-half-address-page-low", 0x00072000),
    ("observed-half-address-page-high", 0x01012000),
    ("observed-tail-command-failure", 0x01FE9000),
)


class ReadSessionStopped(RuntimeError):
    """The read-only BOT session is not safe for another USB command."""


def _source_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tool_descriptor_sha256() -> str:
    """Hash this source with only its reviewed self-pin normalized."""
    source = Path(__file__).read_text(encoding="utf-8")
    prefix = 'EXPECTED_TOOL_DESCRIPTOR_SHA256 = "'
    lines = source.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines)
               if line.startswith(prefix)]
    if len(matches) != 1:
        raise RuntimeError("tool self-pin assignment is not canonical")
    ending = "\n" if lines[matches[0]].endswith("\n") else ""
    lines[matches[0]] = prefix + "<reviewed-self-pin>\"" + ending
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


TOOL_SOURCE_SHA256 = _source_sha256(__file__)


def _strict_close_read_device(device) -> None:
    """Close a completed BOT session and verify interface handoff results."""
    api = _verify.lib
    first_error: BaseException | None = None
    release_succeeded = False
    try:
        result = api.libusb_release_interface(device.h, device.iface)
        if result != 0:
            first_error = RuntimeError(
                f"libusb_release_interface failed (rc={result})")
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
                        f"(rc={result}); active check raised "
                        f"{type(error).__name__}: {error}")
                else:
                    if result not in (-5, -6) or active != 1:
                        first_error = RuntimeError(
                            "libusb_attach_kernel_driver failed "
                            f"(rc={result}); active={active}")
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


class NoRecoveryReadOnlyDevice(_verify.Device):
    """Read-only transport which emits no clear-halt traffic on an anomaly."""

    clear_halt_on_error = False

    def close(self) -> None:
        _strict_close_read_device(self)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_reference(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) != FLASH_SIZE:
        raise ValueError(
            f"reference must be exactly {FLASH_SIZE} bytes, got {len(data)}")
    digest = sha256(data)
    if digest != EXPECTED_REFERENCE_SHA256:
        raise ValueError(
            f"reference SHA-256 is {digest}, expected "
            f"{EXPECTED_REFERENCE_SHA256}")
    return data


def one_pass(device, offset: int, length: int, chunk: int) -> bytes:
    """Read ``[offset, offset + length)`` using exact F6 05 commands."""
    if offset < 0 or length <= 0 or offset + length > FLASH_SIZE:
        raise ValueError("read range lies outside the 32-MiB flash")
    if chunk < BLOCK or chunk % BLOCK or length % chunk:
        raise ValueError("chunk must divide the range and be 512-byte aligned")
    result = bytearray()
    while len(result) < length:
        command_offset = offset + len(result)
        data, status, _residue = device.cmd(
            _verify.cdb_read(command_offset, chunk), chunk)
        if status != 0 or len(data) != chunk:
            raise RuntimeError(
                f"read failed at 0x{command_offset:x} "
                f"(status {status}, got {len(data)}/{chunk})")
        result += data
    return bytes(result)


def exercise_range(device, reference: bytes, *, label: str, offset: int,
                   length: int, chunk: int, passes: int) -> dict[str, object]:
    expected = reference[offset:offset + length]
    expected_sha256 = sha256(expected)
    observed = collections.Counter()
    exact_passes = 0
    for _pass_index in range(passes):
        data = one_pass(device, offset, length, chunk)
        observed[sha256(data)] += 1
        exact_passes += data == expected
    result = {
        "label": label,
        "offset": f"0x{offset:08x}",
        "length": length,
        "chunk": chunk,
        "passes": passes,
        "expected_sha256": expected_sha256,
        "exact_passes": exact_passes,
        "distinct_results": len(observed),
        "observed_sha256_counts": dict(sorted(observed.items())),
    }
    result["passed"] = exact_passes == passes and len(observed) == 1
    return result


def fixed_plan(passes: int) -> list[dict[str, object]]:
    if passes <= 0 or passes > 100:
        raise ValueError("passes must be in the range 1..100")
    return [
        {
            "label": label,
            "offset": f"0x{offset:08x}",
            "length": FIXED_LENGTH,
            "chunk": chunk,
            "passes": passes,
        }
        for label, offset in FIXED_RANGES
        for chunk in FIXED_CHUNKS
    ]


def plan_descriptor() -> dict[str, object]:
    return {
        "schema": "kb7-fixed-isp-read-reliability-plan-v1",
        "reference_sha256": EXPECTED_REFERENCE_SHA256,
        "verifier_source_sha256": EXPECTED_VERIFIER_SOURCE_SHA256,
        "allowed_subcodes": ["F6 00", "F6 F1", "F6 17", "F6 05"],
        "program_or_erase_representable": False,
        "passes": FIXED_PASSES,
        "ranges": fixed_plan(FIXED_PASSES),
        "transport_failure_policy": "no_clear_halt_no_explicit_close_no_later_command",
        "clean_close_policy": "strict_release_and_driver_ownership_check",
    }


def _plan_sha256() -> str:
    encoded = json.dumps(
        plan_descriptor(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def require_reviewed_tool() -> None:
    if (_source_sha256(__file__) != TOOL_SOURCE_SHA256 or
            _tool_descriptor_sha256() != EXPECTED_TOOL_DESCRIPTOR_SHA256):
        raise RuntimeError("read-reliability tool source pin does not match")
    if (_source_sha256(_verify.__file__) != EXPECTED_VERIFIER_SOURCE_SHA256):
        raise RuntimeError("reviewed read-only transport source does not match")
    if _plan_sha256() != EXPECTED_PLAN_SHA256:
        raise RuntimeError("read-reliability plan pin does not match")


def identify(device) -> None:
    identity, status, _residue = device.cmd(
        _verify.cdb_simple(_verify.SUB_IDENTIFY), len(_verify.LOADER_IDENT))
    if status != 0 or identity != _verify.LOADER_IDENT:
        raise RuntimeError("unexpected F6 00 loader identity")
    descriptor, status, _residue = device.cmd(
        _verify.cdb_simple(_verify.SUB_DESC),
        _verify.LOADER_DESCRIPTOR_LENGTH)
    if status != 0:
        raise RuntimeError("F6 F1 loader descriptor command failed")
    _verify.stable_loader_descriptor(descriptor)
    _unused, status, _residue = device.cmd(
        _verify.cdb_simple(_verify.SUB_EN4B))
    if status != 0:
        raise RuntimeError("F6 17 address-mode command failed")


def run_live(reference: bytes, passes: int, *,
             device_factory=NoRecoveryReadOnlyDevice) -> dict[str, object]:
    device = None
    transport_failed = False
    results: list[dict[str, object]] = []
    try:
        device = device_factory()
        identify(device)
        for item in fixed_plan(passes):
            results.append(exercise_range(
                device, reference,
                label=str(item["label"]),
                offset=int(str(item["offset"]), 0),
                length=int(item["length"]),
                chunk=int(item["chunk"]),
                passes=int(item["passes"])))
    except BaseException as error:
        transport_failed = True
        raise ReadSessionStopped(
            f"read-only BOT transport stopped: {type(error).__name__}: "
            f"{error}") from error
    finally:
        # After an incomplete BOT exchange, do not release the interface,
        # reattach a driver, clear a halt or send any later command. Process
        # teardown releases the local handle. Clean completed sessions close
        # normally.
        if device is not None and not transport_failed:
            try:
                device.close()
            except BaseException as error:
                raise ReadSessionStopped(
                    f"strict clean-session close failed: "
                    f"{type(error).__name__}: {error}") from error
    passed = all(bool(result["passed"]) for result in results)
    return {
        "schema": "kb7-fixed-isp-read-reliability-v1",
        "reference_sha256": sha256(reference),
        "read_only": True,
        "program_or_erase_representable": False,
        "ranges": results,
        "passed": passed,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--reference", required=True, type=Path,
                        help="exact pinned 32-MiB owner baseline")
    result.add_argument("--commit", action="store_true",
                        help="open 10f5:5037 and perform the read-only sweep")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        require_reviewed_tool()
        reference = load_reference(args.reference)
        plan = fixed_plan(FIXED_PASSES)
        print(json.dumps({
            "schema": "kb7-fixed-isp-read-reliability-v1",
            "plan_sha256": _plan_sha256(),
            "tool_source_sha256": TOOL_SOURCE_SHA256,
            "reference_sha256": sha256(reference),
            "read_only": True,
            "program_or_erase_representable": False,
            "plan": plan,
        }, indent=2, sort_keys=True))
        if not args.commit:
            print("\nDRY RUN -- no USB device was opened and nothing was changed.")
            return 0
        print("\nREAD-ONLY SWEEP REQUESTED -- no program or erase command is "
              "representable.")
        result = run_live(reference, FIXED_PASSES)
        print(json.dumps(result, indent=2, sort_keys=True))
        if result["passed"]:
            print("\nPASS: every read was byte-exact against the baseline.")
            return 0
        print("\nFAIL: at least one completed read was unstable or incorrect.",
              file=sys.stderr)
        return 1
    except ReadSessionStopped as error:
        print(f"READ-ONLY USB SESSION STOPPED: {error}", file=sys.stderr)
        print("Do not issue another USB command in this powered session. "
              "Power-cycle before any later read-only attempt.",
              file=sys.stderr)
        return 3
    except (OSError, RuntimeError, ValueError) as error:
        print(f"read-reliability stop: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
