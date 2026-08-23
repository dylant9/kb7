"""Offline safety-contract tests for the experimental KB7 ISP writer.

The fixtures in this module are synthetic.  USB and libusb are never opened.
"""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
WRITER_PATH = ROOT / "tools" / "flash-access" / "kb7-isp-write2.py"
WRITER_MODULE_NAME = "kb7_isp_write2_under_test"

_SPEC = importlib.util.spec_from_file_location(WRITER_MODULE_NAME, WRITER_PATH)
isp = importlib.util.module_from_spec(_SPEC)
sys.modules[WRITER_MODULE_NAME] = isp
_SPEC.loader.exec_module(isp)


TARGET = 0x8E000


def make_valid_image():
    """Build a minimal, internally consistent 32-MiB KB7-like image."""
    image = bytearray([0xFF]) * isp.FLASH_SIZE
    image[:len(isp.HEADER_MAGIC)] = isp.HEADER_MAGIC
    image[
        isp.BOOT_CONFIGURATION_OFFSET:
        isp.BOOT_CONFIGURATION_OFFSET + len(isp.BOOT_CONFIGURATION_MAGIC)
    ] = isp.BOOT_CONFIGURATION_MAGIC
    struct.pack_into(
        "<II", image, isp.BOOT_CONFIGURATION_OFFSET + 8,
        isp.FLASH_BASE + isp.MANIFEST_OFFSET, 0)

    manifest = isp.MANIFEST_OFFSET
    image[manifest:manifest + len(isp.MANIFEST_PREFIX)] = isp.MANIFEST_PREFIX

    # The application-to-assets gap contains TARGET and is wholly erased.
    declarations = (
        (0x00000000, 0x11000, 0x2000),
        (0x10000000, 0x20000, 0x2000),
        (0x60100000, 0xA0000, 0x2000),
    )
    first_store = isp.FLASH_BASE + declarations[0][1]
    struct.pack_into(
        "<IIII", image, manifest + 0x10,
        first_store, 0xFFFFFFFF, 1, 0xFFFFFFFF)
    for entry, (load, offset, length) in zip(
            isp.MANIFEST_ENTRIES[:3], declarations):
        checksum = isp.fwin(bytes(image[offset:offset + length]))
        struct.pack_into(
            "<IIII", image, manifest + entry,
            load, isp.FLASH_BASE + offset, length, checksum)

    # The fourth mapping is the required zero-length SRAM mapping and aliases
    # the application store address.
    struct.pack_into(
        "<IIII", image, manifest + isp.MANIFEST_ENTRIES[3],
        isp.EXPECTED_LOADS[3], isp.FLASH_BASE + declarations[1][1], 0, 0)
    return bytes(image)


def accepted_identity(path="7-2.3"):
    identify = isp.LOADER_IDENT
    descriptor = bytearray(isp.LOADER_DESCRIPTOR_LENGTH)
    descriptor[:16] = isp._verify.LOADER_DESCRIPTOR_VERSION
    descriptor[16:28] = isp._verify.LOADER_DESCRIPTOR_DEVICE
    descriptor[28:32] = b"\xa1\xb2\xc3\xd4"
    descriptor[32:36] = isp._verify.LOADER_DESCRIPTOR_MAGIC
    stable_descriptor = isp.stable_loader_descriptor(bytes(descriptor))
    return identify, bytes(descriptor), {
        "device_path": path,
        "identify_hex": identify.hex(),
        "descriptor_sha256": isp.sha256_bytes(stable_descriptor),
        "loader_fingerprint_sha256": isp.sha256_bytes(
            identify + stable_descriptor),
    }


class FakeDevice:
    """Small BOT façade used by execute_stage tests."""

    def __init__(self, path="7-2.3", fail_erase=False):
        self.device_path = path
        self.fail_erase = fail_erase
        self.commands = []
        self.command_lengths = []
        self.program_calls = []
        self.closed = False
        self.identify, self.descriptor, _identity = accepted_identity(path)

    def cmd(self, cdb, data_len=0):
        subcode = cdb[1]
        self.commands.append(subcode)
        self.command_lengths.append((subcode, data_len))
        if subcode == isp.SUB_IDENTIFY:
            return self.identify, 0, 0
        if subcode == isp.SUB_DESC:
            return self.descriptor, 0, 0
        if subcode == isp.SUB_STATUS:
            return b"\x00", 0, 0
        if subcode == isp.SUB_ERASE and self.fail_erase:
            raise RuntimeError("simulated uncertain erase transfer")
        return b"", 0, 0

    def program(self, cdb, data):
        self.commands.append(cdb[1])
        self.program_calls.append((cdb, bytes(data)))

    def close(self):
        self.closed = True


class IspWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = make_valid_image()
        cls.manifest = isp.parse_manifest(cls.baseline)
        cls.programmed = isp.image_with_marker(cls.baseline, TARGET)
        cls.temporary = tempfile.TemporaryDirectory()
        cls.baseline_path = Path(cls.temporary.name) / "synthetic-baseline.bin"
        cls.baseline_path.write_bytes(cls.baseline)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_exact_program_and_erase_cdb_vectors(self):
        self.assertEqual(
            isp.cdb_program(TARGET, isp.BLOCK),
            bytes.fromhex(
                "f6 06 00 60 08 e0 00 00 01 00 00 00 00 00 00 00"))
        self.assertEqual(
            isp.cdb_erase(TARGET),
            bytes.fromhex(
                "f6 15 00 04 70 00 00 00 00 00 00 00 00 00 00 00"))

    def test_vendor_address_mode_boundary_decision(self):
        # Program and erase below 16 MiB both take the vendor's F6 18 path.
        self.assertEqual(
            isp.address_mode_subcode(TARGET, isp.BLOCK), isp.SUB_EX4B)
        self.assertEqual(
            isp.address_mode_subcode(TARGET, isp.SECTOR), isp.SUB_EX4B)
        # An end exactly on the boundary remains F6 18; crossing it selects 17.
        self.assertEqual(
            isp.address_mode_subcode(0xFFF000, 0x1000), isp.SUB_EX4B)
        self.assertEqual(
            isp.address_mode_subcode(0xFFF000, 0x1001), isp.SUB_EN4B)
        self.assertEqual(
            isp.address_mode_subcode(0, isp.FLASH_SIZE), isp.SUB_EN4B)

    def test_program_stage_orders_full_reads_around_sub16_mode(self):
        device = FakeDevice()
        state_path = Path(self.temporary.name) / "program-order-state.json"
        images = iter((self.baseline, self.programmed))

        with redirect_stdout(io.StringIO()):
            result = isp.execute_stage(
                "program", TARGET, self.baseline, self.manifest,
                str(state_path), progress=False,
                device_factory=lambda: device,
                read_full_fn=lambda _device: next(images))

        self.assertEqual(result, 0)
        self.assertEqual(
            device.commands,
            [isp.SUB_IDENTIFY, isp.SUB_DESC, isp.SUB_EN4B, isp.SUB_EX4B,
             isp.SUB_PROGRAM, isp.SUB_STATUS, isp.SUB_EN4B])
        self.assertEqual(device.program_calls[0][1], isp.MARKER)
        self.assertTrue(device.closed)

    def test_baseline_loader_refuses_every_nonexact_size(self):
        for size in (0, isp.FLASH_SIZE - 1, isp.FLASH_SIZE + 1):
            path = Path(self.temporary.name) / f"baseline-{size}.bin"
            with path.open("wb") as stream:
                stream.truncate(size)
            with self.subTest(size=size), self.assertRaises(isp.SafetyError):
                isp.load_baseline(path)

        self.assertEqual(isp.load_baseline(self.baseline_path), self.baseline)

    def test_preflight_final_byte_mismatch_blocks_mutation(self):
        changed = bytearray(self.baseline)
        changed[-1] ^= 0x01
        device = FakeDevice()
        state_path = Path(self.temporary.name) / "mismatch-state.json"

        with redirect_stdout(io.StringIO()), self.assertRaises(isp.SafetyError) as caught:
            isp.execute_stage(
                "program", TARGET, self.baseline, self.manifest,
                str(state_path), progress=False,
                device_factory=lambda: device,
                read_full_fn=lambda _device: bytes(changed))

        self.assertIn("fresh pre-mutation device image mismatch", str(caught.exception))
        self.assertIn("0x1ffffff", str(caught.exception))
        self.assertNotIn(isp.SUB_PROGRAM, device.commands)
        self.assertTrue(device.closed)

    def test_exact_image_comparison_covers_final_byte(self):
        changed = bytearray(self.baseline)
        changed[-1] = 0
        with self.assertRaises(isp.SafetyError) as caught:
            isp.require_exact_image("full chip", self.baseline, bytes(changed))
        self.assertIn("0x1ffffff-0x1ffffff", str(caught.exception))

    def test_manifest_identity_and_region_preconditions_fail_closed(self):
        bad_header = bytearray(self.baseline)
        bad_header[0] ^= 0x01
        with self.assertRaisesRegex(isp.SafetyError, "flash header"):
            isp.parse_manifest(bytes(bad_header))

        bad_manifest = bytearray(self.baseline)
        bad_manifest[isp.MANIFEST_OFFSET] ^= 0x01
        with self.assertRaisesRegex(isp.SafetyError, "manifest magic"):
            isp.parse_manifest(bytes(bad_manifest))

        # A declared application sector cannot be selected as scratch.
        with self.assertRaises(isp.SafetyError):
            isp.validate_target(self.manifest, self.baseline, 0x20000)

        device = FakeDevice()
        device.identify = b"wrong-id"
        with self.assertRaisesRegex(isp.SafetyError, "loader identity"):
            isp.query_loader_identity(device)

        padded = FakeDevice()
        padded.identify = isp.LOADER_IDENT + bytes(6)
        with self.assertRaisesRegex(isp.SafetyError, "loader identity"):
            isp.query_loader_identity(padded)

        accepted = FakeDevice()
        accepted_result = isp.query_loader_identity(accepted)
        self.assertEqual(
            accepted.command_lengths,
            [(isp.SUB_IDENTIFY, 2),
             (isp.SUB_DESC, isp.LOADER_DESCRIPTOR_LENGTH)])

        # Bytes 28..31 come from an uninitialized loader stack tail. They must
        # not break state binding across reconnects, while every stable field
        # remains exact.
        changed_tail = FakeDevice()
        changed = bytearray(changed_tail.descriptor)
        changed[28:32] = b"\x10\x20\x30\x40"
        changed_tail.descriptor = bytes(changed)
        changed_result = isp.query_loader_identity(changed_tail)
        self.assertEqual(
            changed_result["descriptor_sha256"],
            accepted_result["descriptor_sha256"])
        self.assertEqual(
            changed_result["loader_fingerprint_sha256"],
            accepted_result["loader_fingerprint_sha256"])

        bad_stable_field = FakeDevice()
        changed = bytearray(bad_stable_field.descriptor)
        changed[16] ^= 1
        bad_stable_field.descriptor = bytes(changed)
        with self.assertRaisesRegex(isp.SafetyError, "loader descriptor"):
            isp.query_loader_identity(bad_stable_field)

        # Hard-coded loader vector: do not construct this from production
        # constants, so a typo in those constants cannot make the fixture and
        # implementation agree accidentally.
        canonical = bytes.fromhex(
            "76 30 2e 30 30 31 20 74 65 73 74 21 00 00 00 00 "
            "53 4e 43 37 33 32 30 42 00 00 00 00 de ad be ef "
            "fc cf ab ba")
        stable = bytes.fromhex(
            "76 30 2e 30 30 31 20 74 65 73 74 21 00 00 00 00 "
            "53 4e 43 37 33 32 30 42 00 00 00 00 fc cf ab ba")
        self.assertEqual(isp.stable_loader_descriptor(canonical), stable)
        for index in (0, 16, 32):
            corrupted = bytearray(canonical)
            corrupted[index] ^= 1
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                isp.stable_loader_descriptor(bytes(corrupted))
        for length in (35, 37):
            malformed = canonical[:length] if length < 36 else canonical + b"\x00"
            with self.subTest(length=length), self.assertRaises(RuntimeError):
                isp.stable_loader_descriptor(malformed)

    def test_target_requires_the_entire_sector_to_be_erased(self):
        programmed_tail = bytearray(self.baseline)
        # Outside the 512-byte marker window, but inside its 4-KiB sector.
        programmed_tail[TARGET + isp.SECTOR - 1] = 0x7F
        with self.assertRaisesRegex(
                isp.SafetyError, "entire target sector must be erased"):
            isp.validate_target(self.manifest, bytes(programmed_tail), TARGET)

    def test_state_is_bound_to_device_manifest_baseline_and_marker(self):
        _identify, _descriptor, identity = accepted_identity()
        baseline_hash = isp.sha256_bytes(self.baseline)
        programmed_hash = isp.sha256_bytes(self.programmed)
        expected = isp._state_fields(
            identity, self.manifest, baseline_hash, TARGET,
            programmed_hash, isp.STATE_READY)
        isp.validate_state(dict(expected), expected)

        replacements = {
            "device_path": "9-9",
            "identify_hex": "0000",
            "descriptor_sha256": "0" * 64,
            "loader_fingerprint_sha256": "1" * 64,
            "manifest_sha256": "2" * 64,
            "baseline_sha256": "3" * 64,
            "marker_sha256": "4" * 64,
            "programmed_image_sha256": "5" * 64,
        }
        for key, replacement in replacements.items():
            tampered = dict(expected)
            tampered[key] = replacement
            with self.subTest(key=key), self.assertRaises(isp.SafetyError):
                isp.validate_state(tampered, expected)

        # Even the offline erase dry run requires a complete, canonical state;
        # identity values are checked exactly once the connected device opens.
        isp.validate_static_state(
            expected, self.manifest, baseline_hash, TARGET, programmed_hash)
        malformed_states = []
        missing = dict(expected)
        missing.pop("device_path")
        malformed_states.append(missing)
        extra = dict(expected)
        extra["unknown"] = True
        malformed_states.append(extra)
        bad_hash = dict(expected)
        bad_hash["descriptor_sha256"] = "not-a-hash"
        malformed_states.append(bad_hash)
        for state in malformed_states:
            with self.subTest(state=state), self.assertRaises(isp.SafetyError):
                isp.validate_static_state(
                    state, self.manifest, baseline_hash, TARGET,
                    programmed_hash)

    def test_erase_attempt_consumes_ready_state_before_transport(self):
        _identify, _descriptor, identity = accepted_identity()
        baseline_hash = isp.sha256_bytes(self.baseline)
        programmed_hash = isp.sha256_bytes(self.programmed)
        state_path = Path(self.temporary.name) / "erase-consumed-state.json"
        isp.write_state_atomic(
            state_path,
            isp._state_fields(
                identity, self.manifest, baseline_hash, TARGET,
                programmed_hash, isp.STATE_READY))
        device = FakeDevice(fail_erase=True)

        with redirect_stdout(io.StringIO()), self.assertRaises(
                isp.MutationResultUnknown):
            isp.execute_stage(
                "erase", TARGET, self.baseline, self.manifest,
                str(state_path), progress=False,
                device_factory=lambda: device,
                read_full_fn=lambda _device: self.programmed)

        consumed = isp.load_state(state_path)
        self.assertEqual(consumed["status"], isp.STATE_ERASE_STARTED)
        with self.assertRaisesRegex(isp.SafetyError, "status"):
            isp.validate_static_state(
                consumed, self.manifest, baseline_hash, TARGET,
                programmed_hash)

    def test_erase_stage_orders_full_reads_and_consumes_state_on_success(self):
        _identify, _descriptor, identity = accepted_identity()
        baseline_hash = isp.sha256_bytes(self.baseline)
        programmed_hash = isp.sha256_bytes(self.programmed)
        state_path = Path(self.temporary.name) / "erase-order-state.json"
        isp.write_state_atomic(
            state_path,
            isp._state_fields(
                identity, self.manifest, baseline_hash, TARGET,
                programmed_hash, isp.STATE_READY))
        device = FakeDevice()
        images = iter((self.programmed, self.baseline))

        with redirect_stdout(io.StringIO()):
            result = isp.execute_stage(
                "erase", TARGET, self.baseline, self.manifest,
                str(state_path), progress=False,
                device_factory=lambda: device,
                read_full_fn=lambda _device: next(images))

        self.assertEqual(result, 0)
        self.assertEqual(
            device.commands,
            [isp.SUB_IDENTIFY, isp.SUB_DESC, isp.SUB_EN4B, isp.SUB_EX4B,
             isp.SUB_ERASE, isp.SUB_STATUS, isp.SUB_EN4B])
        self.assertFalse(state_path.exists())
        self.assertTrue(device.closed)

    def test_operator_interrupt_after_mutation_is_an_unknown_result(self):
        class InterruptedDevice(FakeDevice):
            def program(self, cdb, data):
                super().program(cdb, data)
                raise KeyboardInterrupt

        device = InterruptedDevice()
        state_path = Path(self.temporary.name) / "interrupt-state.json"

        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                isp.MutationResultUnknown, "operator interruption"):
            isp.execute_stage(
                "program", TARGET, self.baseline, self.manifest,
                str(state_path), progress=False,
                device_factory=lambda: device,
                read_full_fn=lambda _device: self.baseline)

        self.assertFalse(state_path.exists())
        self.assertTrue(device.closed)

    def test_csw_validation_rejects_every_transport_anomaly(self):
        tag = 0x12345678
        valid = struct.pack("<IIIB", 0x53425355, tag, 0, 0)
        self.assertEqual(isp.parse_csw(valid, tag), (0, 0))
        invalid = (
            valid[:-1],
            struct.pack("<IIIB", 0xDEADBEEF, tag, 0, 0),
            struct.pack("<IIIB", 0x53425355, tag + 1, 0, 0),
            struct.pack("<IIIB", 0x53425355, tag, 1, 0),
            struct.pack("<IIIB", 0x53425355, tag, 0, 1),
        )
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                isp.parse_csw(raw, tag)

        # The loader's F6 path reports the original CBW data length as residue
        # even after an exact data phase. Accept only the precisely expected
        # value, never an arbitrary nonzero residue.
        quirky = struct.pack("<IIIB", 0x53425355, tag, 8, 0)
        self.assertEqual(isp.parse_csw(quirky, tag, 8), (0, 8))
        for expected in (7, 9):
            with self.subTest(expected=expected), self.assertRaises(RuntimeError):
                isp.parse_csw(quirky, tag, expected)

    def test_f6_transports_require_exact_loader_residue(self):
        read_device = object.__new__(isp.Device)
        read_device.tag = 0
        read_device.ep_in = 0x81
        read_device.ep_out = 0x02
        read_device._xfer_exact = mock.Mock()
        with mock.patch.object(
                isp._verify, "parse_csw", return_value=(0, 2)) as parser:
            payload, status, residue = read_device._command(
                isp.cdb_simple(isp.SUB_IDENTIFY), 2, isp._verify._ALLOWED)
        self.assertEqual((len(payload), status, residue), (2, 0, 2))
        self.assertEqual(parser.call_args.kwargs["expected_residue"], 2)

        write_device = object.__new__(isp.WriteDevice)
        write_device.tag = 0
        write_device.ep_in = 0x81
        write_device.ep_out = 0x02
        write_device._xfer_exact = mock.Mock()
        with mock.patch.object(
                isp, "parse_csw", return_value=(0, isp.BLOCK)) as parser:
            self.assertEqual(
                write_device.program(
                    isp.cdb_program(TARGET, isp.BLOCK), isp.MARKER),
                (0, isp.BLOCK))
        self.assertEqual(
            parser.call_args.kwargs["expected_residue"], isp.BLOCK)

    def test_short_bulk_and_short_read_are_fatal(self):
        class ShortTransfer:
            @staticmethod
            def _xfer(_ep, _buf, length, _timeout):
                return length - 1

        with self.assertRaisesRegex(RuntimeError, "short CBW transfer"):
            isp.Device._xfer_exact(
                ShortTransfer(), 0x02, object(), 31, "CBW")

        class ShortRead:
            @staticmethod
            def cmd(_cdb, data_len=0):
                return bytes(data_len - 1), 0, 0

        with self.assertRaisesRegex(RuntimeError, "short verification read"):
            isp.read_range(ShortRead(), 0, isp.BLOCK, progress=False)

    def test_poll_ready_timeout_is_fatal(self):
        class BusyDevice:
            calls = 0

            def cmd(self, cdb, data_len=0):
                self.calls += 1
                self.asserted = (cdb[1], data_len)
                return b"\x01", 0, 0

        ticks = iter((0.0, 0.5, 1.1))
        device = BusyDevice()
        with self.assertRaisesRegex(RuntimeError, "remained busy"):
            isp.poll_ready(
                device, timeout=1.0, interval=0,
                clock=lambda: next(ticks), sleeper=lambda _seconds: None)
        self.assertEqual(device.asserted, (isp.SUB_STATUS, 1))
        self.assertEqual(device.calls, 2)

    def test_dry_run_never_opens_a_usb_device(self):
        state_path = Path(self.temporary.name) / "dry-run-state.json"
        argv = [
            str(WRITER_PATH), "--stage", "program", "--baseline",
            str(self.baseline_path), "--state-file", str(state_path),
        ]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(isp, "execute_stage") as execute_stage, \
                mock.patch.object(isp._verify, "_load_libusb") as load_libusb, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = isp.main()
        self.assertEqual(result, 0)
        execute_stage.assert_not_called()
        load_libusb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
