from __future__ import annotations

import importlib.util
import io
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "flash-access" / "kb7-isp-repeat.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


RELIABILITY = load_module("kb7_isp_read_reliability_tested", TOOL_PATH)
PUBLIC_FIXED_RANGES = RELIABILITY.FIXED_RANGES
PUBLIC_FIXED_CHUNKS = RELIABILITY.FIXED_CHUNKS
PRODUCTION_PLAN_SHA256 = RELIABILITY._plan_sha256()
PRODUCTION_TOOL_DESCRIPTOR_SHA256 = RELIABILITY._tool_descriptor_sha256()


class FakeDevice:
    def __init__(self, image: bytes, mode: str = "exact") -> None:
        self.image = image
        self.mode = mode
        self.read_count = 0
        self.close_count = 0
        self.subcodes: list[int] = []

    def cmd(self, cdb: bytes, data_len: int = 0):
        subcode = cdb[1]
        self.subcodes.append(subcode)
        if subcode == RELIABILITY._verify.SUB_IDENTIFY:
            return RELIABILITY._verify.LOADER_IDENT, 0, data_len
        if subcode == RELIABILITY._verify.SUB_DESC:
            raw = (RELIABILITY._verify.LOADER_DESCRIPTOR_VERSION +
                   RELIABILITY._verify.LOADER_DESCRIPTOR_DEVICE +
                   bytes(4) + RELIABILITY._verify.LOADER_DESCRIPTOR_MAGIC)
            return raw, 0, data_len
        if subcode == RELIABILITY._verify.SUB_EN4B:
            return b"", 0, 0
        if subcode != RELIABILITY._verify.SUB_READ:
            raise AssertionError(f"unexpected subcode {subcode:#x}")
        self.read_count += 1
        address = struct.unpack(">I", cdb[3:7])[0]
        offset = address - RELIABILITY._verify.FLASH_BASE
        if self.mode == "transport-error":
            raise RuntimeError("synthetic BOT failure")
        if self.mode == "stable-zero":
            return bytes(data_len), 0, data_len
        if self.mode == "half-address":
            offset //= 2
        data = self.image[offset:offset + data_len]
        if self.mode == "alternating" and self.read_count % 2 == 0:
            data = bytes(byte ^ 0xff for byte in data)
        return data, 0, data_len

    def close(self) -> None:
        self.close_count += 1


class FakeLibusb:
    def __init__(self, *, release: int = 0, attach: int = 0,
                 active: int = 0) -> None:
        self.release = release
        self.attach = attach
        self.active = active
        self.events: list[str] = []

    def libusb_release_interface(self, _handle, _iface):
        self.events.append("release")
        return self.release

    def libusb_attach_kernel_driver(self, _handle, _iface):
        self.events.append("attach")
        return self.attach

    def libusb_kernel_driver_active(self, _handle, _iface):
        self.events.append("active")
        return self.active

    def libusb_close(self, _handle):
        self.events.append("close")

    def libusb_exit(self, _context):
        self.events.append("exit")


class IspReadReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image = bytes((index * 37 + index // 7) & 0xff
                           for index in range(0x2000))
        self.fixed = mock.patch.multiple(
            RELIABILITY,
            FLASH_SIZE=len(self.image),
            FIXED_LENGTH=0x400,
            FIXED_CHUNKS=(0x200, 0x400),
            FIXED_RANGES=(("synthetic", 0x800),))
        self.fixed.start()

    def tearDown(self) -> None:
        self.fixed.stop()

    def test_fixed_public_plan_covers_observed_failure_classes(self) -> None:
        self.assertEqual(RELIABILITY.EXPECTED_REFERENCE_SHA256,
                         "2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f")
        expected_offsets = {0x15000, 0x40000, 0x72000, 0x1012000, 0x1fe9000}
        self.assertEqual(
            {offset for _label, offset in PUBLIC_FIXED_RANGES},
            expected_offsets)
        self.assertEqual(PUBLIC_FIXED_CHUNKS,
                         (0x200, 0x400, 0x800, 0x1000))
        self.assertEqual(RELIABILITY.FIXED_PASSES, 20)
        self.assertNotIn("--passes", RELIABILITY.parser().format_help())

    def test_exact_results_are_required_not_only_stability(self) -> None:
        exact = FakeDevice(self.image)
        result = RELIABILITY.exercise_range(
            exact, self.image, label="exact", offset=0x800,
            length=0x400, chunk=0x200, passes=3)
        self.assertTrue(result["passed"])
        self.assertEqual(result["exact_passes"], 3)
        self.assertEqual(result["distinct_results"], 1)

        wrong = FakeDevice(self.image, "stable-zero")
        result = RELIABILITY.exercise_range(
            wrong, self.image, label="wrong", offset=0x800,
            length=0x400, chunk=0x200, passes=3)
        self.assertFalse(result["passed"])
        self.assertEqual(result["exact_passes"], 0)
        self.assertEqual(result["distinct_results"], 1)

    def test_half_address_and_unstable_results_fail(self) -> None:
        half = FakeDevice(self.image, "half-address")
        result = RELIABILITY.exercise_range(
            half, self.image, label="half", offset=0x800,
            length=0x400, chunk=0x400, passes=2)
        self.assertFalse(result["passed"])
        self.assertEqual(result["exact_passes"], 0)

        alternating = FakeDevice(self.image, "alternating")
        result = RELIABILITY.exercise_range(
            alternating, self.image, label="unstable", offset=0x800,
            length=0x400, chunk=0x400, passes=4)
        self.assertFalse(result["passed"])
        self.assertEqual(result["distinct_results"], 2)

    def test_live_sweep_uses_only_read_only_commands_and_closes_cleanly(self) -> None:
        device = FakeDevice(self.image)
        result = RELIABILITY.run_live(
            self.image, 2, device_factory=lambda: device)
        self.assertTrue(result["passed"])
        self.assertEqual(device.close_count, 1)
        self.assertEqual(set(device.subcodes), {
            RELIABILITY._verify.SUB_IDENTIFY,
            RELIABILITY._verify.SUB_DESC,
            RELIABILITY._verify.SUB_EN4B,
            RELIABILITY._verify.SUB_READ,
        })
        self.assertNotIn(0x06, device.subcodes)
        self.assertNotIn(0x15, device.subcodes)
        self.assertNotIn(0x19, device.subcodes)

    def test_transport_failure_sends_no_close_or_later_command(self) -> None:
        device = FakeDevice(self.image, "transport-error")
        with self.assertRaisesRegex(
                RELIABILITY.ReadSessionStopped, "synthetic BOT failure"):
            RELIABILITY.run_live(
                self.image, 2, device_factory=lambda: device)
        self.assertEqual(device.close_count, 0)
        self.assertEqual(device.subcodes[-1], RELIABILITY._verify.SUB_READ)

    def test_reference_requires_exact_size_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.bin"
            path.write_bytes(self.image)
            with mock.patch.object(
                    RELIABILITY, "EXPECTED_REFERENCE_SHA256",
                    RELIABILITY.sha256(self.image)):
                self.assertEqual(RELIABILITY.load_reference(path), self.image)
            path.write_bytes(self.image[:-1])
            with self.assertRaisesRegex(ValueError, "exactly"):
                RELIABILITY.load_reference(path)

    def test_dry_run_opens_no_device_and_completed_wrong_read_exits_one(self) -> None:
        output = io.StringIO()
        with mock.patch.object(RELIABILITY, "load_reference",
                               return_value=self.image), \
                mock.patch.object(RELIABILITY, "require_reviewed_tool"), \
                mock.patch.object(RELIABILITY, "NoRecoveryReadOnlyDevice",
                                  side_effect=AssertionError("USB opened")), \
                redirect_stdout(output):
            self.assertEqual(RELIABILITY.main([
                "--reference", "/not/opened.bin"]), 0)
        self.assertIn("DRY RUN", output.getvalue())

        failed = {
            "schema": "kb7-fixed-isp-read-reliability-v1",
            "reference_sha256": RELIABILITY.sha256(self.image),
            "read_only": True,
            "program_or_erase_representable": False,
            "ranges": [],
            "passed": False,
        }
        with mock.patch.object(RELIABILITY, "load_reference",
                               return_value=self.image), \
                mock.patch.object(RELIABILITY, "require_reviewed_tool"), \
                mock.patch.object(RELIABILITY, "run_live",
                                  return_value=failed), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(RELIABILITY.main([
                "--reference", "/not/opened.bin", "--commit"]), 1)

    def test_no_recovery_device_disables_clear_halt(self) -> None:
        self.assertFalse(RELIABILITY.NoRecoveryReadOnlyDevice.clear_halt_on_error)

    def test_strict_close_checks_release_and_skips_attach_on_failure(self) -> None:
        device = RELIABILITY.NoRecoveryReadOnlyDevice.__new__(
            RELIABILITY.NoRecoveryReadOnlyDevice)
        device.h = object()
        device.ctx = object()
        device.iface = 0
        device.reattach = True
        api = FakeLibusb(release=-1)
        with mock.patch.object(RELIABILITY._verify, "lib", api):
            with self.assertRaisesRegex(RuntimeError, "release_interface"):
                device.close()
        self.assertEqual(api.events, ["release", "close", "exit"])

    def test_strict_close_verifies_driver_after_busy_attach(self) -> None:
        device = RELIABILITY.NoRecoveryReadOnlyDevice.__new__(
            RELIABILITY.NoRecoveryReadOnlyDevice)
        device.h = object()
        device.ctx = object()
        device.iface = 0
        device.reattach = True
        api = FakeLibusb(attach=-6, active=1)
        with mock.patch.object(RELIABILITY._verify, "lib", api):
            device.close()
        self.assertEqual(
            api.events, ["release", "attach", "active", "close", "exit"])

    def test_live_strict_close_failure_is_a_powered_session_stop(self) -> None:
        device = FakeDevice(self.image)
        device.close = mock.Mock(side_effect=RuntimeError("release failed"))
        with self.assertRaisesRegex(
                RELIABILITY.ReadSessionStopped, "strict.*close failed"):
            RELIABILITY.run_live(
                self.image, 2, device_factory=lambda: device)

        with mock.patch.object(RELIABILITY, "load_reference",
                               return_value=self.image), \
                mock.patch.object(RELIABILITY, "require_reviewed_tool"), \
                mock.patch.object(RELIABILITY, "run_live",
                                  side_effect=RELIABILITY.ReadSessionStopped(
                                      "synthetic stop")), \
                redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(RELIABILITY.main([
                "--reference", "/not/opened.bin", "--commit"]), 3)
        self.assertIn("Power-cycle", errors.getvalue())

    def test_production_plan_and_source_pins_match(self) -> None:
        self.assertEqual(
            RELIABILITY.EXPECTED_VERIFIER_SOURCE_SHA256,
            RELIABILITY._source_sha256(RELIABILITY._verify.__file__))
        self.assertEqual(
            RELIABILITY.EXPECTED_PLAN_SHA256, PRODUCTION_PLAN_SHA256)
        self.assertEqual(
            RELIABILITY.EXPECTED_TOOL_DESCRIPTOR_SHA256,
            PRODUCTION_TOOL_DESCRIPTOR_SHA256)


if __name__ == "__main__":
    unittest.main()
