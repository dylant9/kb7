"""Offline tests for the fixed KB7 scratch restart experiment."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "flash-access" / "kb7-isp-scratch-restart.py"
MODULE = "kb7_isp_scratch_restart_under_test"
PRODUCTION_LOADER_SHA256 = (
    "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56")

_spec = importlib.util.spec_from_file_location(MODULE, TOOL)
isp = importlib.util.module_from_spec(_spec)
sys.modules[MODULE] = isp
_spec.loader.exec_module(isp)


def make_v122_image():
    image = bytearray([0xFF]) * isp.FLASH_SIZE
    writer = isp._writer
    image[:len(writer.HEADER_MAGIC)] = writer.HEADER_MAGIC
    image[
        writer.BOOT_CONFIGURATION_OFFSET:
        writer.BOOT_CONFIGURATION_OFFSET + len(writer.BOOT_CONFIGURATION_MAGIC)
    ] = writer.BOOT_CONFIGURATION_MAGIC
    struct.pack_into(
        "<II", image, writer.BOOT_CONFIGURATION_OFFSET + 8,
        writer.FLASH_BASE + writer.MANIFEST_OFFSET, 0)
    manifest = writer.MANIFEST_OFFSET
    image[manifest:manifest + len(writer.MANIFEST_PREFIX)] = (
        writer.MANIFEST_PREFIX)
    first_offset = isp.EXPECTED_REGION_GEOMETRY[0][1]
    struct.pack_into(
        "<IIII", image, manifest + 0x10,
        writer.FLASH_BASE + first_offset, 0xFFFFFFFF, 1, 0xFFFFFFFF)
    for entry, (load, offset, length) in zip(
            writer.MANIFEST_ENTRIES[:3], isp.EXPECTED_REGION_GEOMETRY):
        checksum = writer.fwin(bytes(image[offset:offset + length]))
        struct.pack_into(
            "<IIII", image, manifest + entry,
            load, writer.FLASH_BASE + offset, length, checksum)
    struct.pack_into(
        "<IIII", image, manifest + writer.MANIFEST_ENTRIES[3],
        writer.EXPECTED_LOADS[3],
        writer.FLASH_BASE + isp.EXPECTED_REGION_GEOMETRY[1][1], 0, 0)
    return bytes(image)


def accepted_identity(path="7-2.3"):
    writer = isp._writer
    descriptor = bytearray(writer.LOADER_DESCRIPTOR_LENGTH)
    descriptor[:16] = writer._verify.LOADER_DESCRIPTOR_VERSION
    descriptor[16:28] = writer._verify.LOADER_DESCRIPTOR_DEVICE
    descriptor[28:32] = b"\xa1\xb2\xc3\xd4"
    descriptor[32:36] = writer._verify.LOADER_DESCRIPTOR_MAGIC
    stable = writer.stable_loader_descriptor(bytes(descriptor))
    return bytes(descriptor), {
        "device_path": path,
        "identify_hex": writer.LOADER_IDENT.hex(),
        "descriptor_sha256": writer.sha256_bytes(stable),
        "loader_fingerprint_sha256": writer.sha256_bytes(
            writer.LOADER_IDENT + stable),
    }


class FakeDevice:
    def __init__(self, path="7-2.3", fail_program=False):
        self.device_path = path
        self.descriptor, _identity = accepted_identity(path)
        self.events = []
        self.closed = False
        self.fail_program = fail_program

    def cmd(self, cdb, data_len=0):
        cdb = bytes(cdb)
        self.events.append(("cmd", cdb[1], cdb, data_len))
        if cdb[1] == isp._writer.SUB_IDENTIFY:
            return isp._writer.LOADER_IDENT, 0, 0
        if cdb[1] == isp._writer.SUB_DESC:
            return self.descriptor, 0, 0
        if cdb[1] == isp._writer.SUB_STATUS:
            return b"\x00", 0, 0
        return b"", 0, 0

    def program(self, cdb, payload):
        self.events.append(("program", bytes(cdb), bytes(payload)))
        if self.fail_program:
            raise RuntimeError("synthetic program failure")

    def close(self):
        self.closed = True


class ReadScript:
    def __init__(self, images):
        self.images = list(images)
        self.calls = 0

    def __call__(self, _device):
        self.calls += 1
        if not self.images:
            raise AssertionError("unexpected full-chip read")
        return self.images.pop(0)


class ScratchRestartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if isp.EXPECTED_LOADER_SHA256 != PRODUCTION_LOADER_SHA256:
            raise AssertionError("production loader pin changed")
        cls.production_loader_hash = isp.EXPECTED_LOADER_SHA256
        cls.production_plan_hash = isp.PLAN_SHA256
        cls.baseline = make_v122_image()
        cls.synthetic_loader_hash = isp.sha256_bytes(
            cls.baseline[
                isp.LOADER_OFFSET:isp.LOADER_OFFSET + isp.LOADER_SIZE])
        isp.EXPECTED_LOADER_SHA256 = cls.synthetic_loader_hash
        isp.PLAN_SHA256 = isp._plan_sha256()
        cls.manifest = isp.validate_baselines(cls.baseline, cls.baseline)
        cls.baseline_hash = isp.sha256_bytes(cls.baseline)
        cls.hashes = isp.checkpoint_hashes(cls.baseline)
        cls.descriptor, cls.identity = accepted_identity()
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.baseline_a = root / "baseline-a.bin"
        cls.baseline_b = root / "baseline-b.bin"
        cls.baseline_a.write_bytes(cls.baseline)
        cls.baseline_b.write_bytes(cls.baseline)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()
        isp.EXPECTED_LOADER_SHA256 = cls.production_loader_hash
        isp.PLAN_SHA256 = cls.production_plan_hash

    def state_path(self, name):
        return Path(self.temporary.name) / name

    def stable_state(self, status, image):
        return isp._state(
            self.identity, self.manifest, self.baseline_hash, self.hashes,
            status, isp.sha256_bytes(image), None)

    def test_fixed_geometry_payloads_and_command_vectors(self):
        self.assertEqual(
            (isp.LOWER_GUARD_SECTOR, isp.WORK_A_SECTOR,
             isp.WORK_B_SECTOR, isp.UPPER_GUARD_SECTOR),
            (0xC4000, 0xC5000, 0xC6000, 0xC7000))
        self.assertEqual(isp.LOWER_GUARD_OFFSET, 0xC4E00)
        self.assertEqual(isp.UPPER_GUARD_OFFSET, 0xC7000)
        self.assertEqual(len(isp.PATTERNS), 18)
        self.assertEqual(len(set(isp.PATTERNS)), 18)
        for payload in isp.PATTERNS:
            self.assertEqual(len(payload), isp.BLOCK)
            self.assertNotIn(0xFF, payload)
            self.assertTrue(all(
                ((~value) & 0xFF).bit_count() == 1 for value in payload))

        vectors = {
            0xC4E00: "f60600600c4e00000100000000000000",
            0xC5000: "f60600600c5000000100000000000000",
            0xC5E00: "f60600600c5e00000100000000000000",
            0xC6000: "f60600600c6000000100000000000000",
            0xC6E00: "f60600600c6e00000100000000000000",
            0xC7000: "f60600600c7000000100000000000000",
        }
        for offset, expected in vectors.items():
            self.assertEqual(isp.cdb_program(offset, isp.BLOCK).hex(), expected)
        erase_vectors = {
            0xC4000: "f6150006200000000000000000000000",
            0xC5000: "f6150006280000000000000000000000",
            0xC6000: "f6150006300000000000000000000000",
            0xC7000: "f6150006380000000000000000000000",
        }
        for offset, expected in erase_vectors.items():
            self.assertEqual(isp.cdb_erase(offset).hex(), expected)

    def test_plan_binds_every_command_payload_source_and_cut(self):
        descriptor = isp.plan_descriptor()
        self.assertEqual(descriptor["sub16_address_mode"], 0x18)
        self.assertEqual(descriptor["envelope"], [0xC0000, 0x100000])
        self.assertEqual(
            descriptor["controlled_unknown_checkpoints"],
            ["program-cut", "erase-cut"])
        self.assertEqual(len(descriptor["writes"]), 18)
        self.assertEqual(len(descriptor["erases"]), 4)
        expected_offsets = (
            0xC4E00,
            0xC5000, 0xC5200, 0xC5400, 0xC5600,
            0xC5800, 0xC5A00, 0xC5C00, 0xC5E00,
            0xC6000, 0xC6200, 0xC6400, 0xC6600,
            0xC6800, 0xC6A00, 0xC6C00, 0xC6E00,
            0xC7000,
        )
        expected_cdbs = tuple(
            f"f6060060{offset:06x}0001" + "00" * 7
            for offset in expected_offsets)
        self.assertEqual(
            tuple(item["offset"] for item in descriptor["writes"]),
            expected_offsets)
        self.assertEqual(
            tuple(item["cdb_hex"] for item in descriptor["writes"]),
            expected_cdbs)
        source_paths = {
            "experiment": TOOL,
            "writer": ROOT / "tools" / "flash-access" / "kb7-isp-write2.py",
            "verifier": ROOT / "tools" / "flash-access" / "kb7-isp-verify.py",
        }
        self.assertEqual(
            descriptor["source_sha256"],
            {
                name: hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in source_paths.items()
            })
        self.assertEqual(isp._plan_sha256(), isp.PLAN_SHA256)
        original = isp.cdb_erase
        with mock.patch.object(
                isp, "cdb_erase",
                side_effect=lambda offset: original(offset)[:-1] + b"\x01"):
            self.assertNotEqual(isp._plan_sha256(), isp.PLAN_SHA256)

    def test_two_exact_baselines_loader_layout_and_envelope_are_required(self):
        self.assertEqual(
            isp.validate_baselines(self.baseline, self.baseline).sha256,
            self.manifest.sha256)
        changed = bytearray(self.baseline)
        changed[isp.ENVELOPE_LO] = 0xFE
        with self.assertRaisesRegex(isp.SafetyError, "containment envelope"):
            isp.validate_baselines(bytes(changed), bytes(changed))
        changed = bytearray(self.baseline)
        changed[isp.LOADER_OFFSET + 10] = 0xFE
        with self.assertRaisesRegex(isp.SafetyError, "preserved ISP loader"):
            isp.validate_baselines(bytes(changed), bytes(changed))
        changed = bytearray(self.baseline)
        changed[-1] = 0xFE
        with self.assertRaisesRegex(isp.SafetyError, "not byte-identical"):
            isp.validate_baselines(self.baseline, bytes(changed))

    def test_expected_images_cover_two_full_work_sectors_and_guards(self):
        prepared_a = isp.image_prepare_a_count(
            self.baseline, len(isp.PREPARE_A_WRITES))
        cut = isp.image_after_program_cut(self.baseline)
        prepared = isp.image_prepared_all(self.baseline)
        erase_a = isp.image_after_erase_a(self.baseline)
        erase_b = isp.image_after_erase_b(self.baseline)
        lower = isp.image_after_cleanup_lower(self.baseline)
        self.assertEqual(
            isp._writer.difference_summary(self.baseline, prepared_a)[0],
            9 * isp.BLOCK)
        self.assertEqual(
            isp._writer.difference_summary(prepared_a, cut)[0], isp.BLOCK)
        self.assertEqual(
            prepared[isp.WORK_A_SECTOR:isp.WORK_A_SECTOR + isp.SECTOR],
            b"".join(payload for _offset, payload in isp.WORK_A_WRITES))
        self.assertEqual(
            prepared[isp.WORK_B_SECTOR:isp.WORK_B_SECTOR + isp.SECTOR],
            b"".join(payload for _offset, payload in isp.WORK_B_WRITES))
        self.assertEqual(
            erase_a[isp.WORK_A_SECTOR:isp.WORK_A_SECTOR + isp.SECTOR],
            b"\xff" * isp.SECTOR)
        self.assertEqual(
            erase_b[isp.WORK_B_SECTOR:isp.WORK_B_SECTOR + isp.SECTOR],
            b"\xff" * isp.SECTOR)
        self.assertEqual(
            lower[
                isp.UPPER_GUARD_OFFSET:isp.UPPER_GUARD_OFFSET + isp.BLOCK],
            isp.UPPER_GUARD)

    def test_state_accepts_only_canonical_stable_or_intent_transitions(self):
        prepared_a = isp.image_prepare_a_count(
            self.baseline, len(isp.PREPARE_A_WRITES))
        state = self.stable_state("prepare_a_verified", prepared_a)
        isp.validate_state_static(
            state, self.manifest, self.baseline_hash, self.hashes,
            self.baseline)
        tampered = json.loads(json.dumps(state))
        tampered["status"] = "invented_verified"
        with self.assertRaisesRegex(isp.SafetyError, "canonical stable"):
            isp.validate_state_static(
                tampered, self.manifest, self.baseline_hash, self.hashes,
                self.baseline)

        intent = isp.canonical_operations(self.baseline)[9]
        pending = isp._state(
            self.identity, self.manifest, self.baseline_hash, self.hashes,
            "intent_pending", intent["pre_image_sha256"], intent)
        isp.validate_state_static(
            pending, self.manifest, self.baseline_hash, self.hashes,
            self.baseline)
        tampered = json.loads(json.dumps(pending))
        tampered["intent"]["next_status"] = "skip_everything"
        with self.assertRaisesRegex(isp.SafetyError, "canonical fixed"):
            isp.validate_state_static(
                tampered, self.manifest, self.baseline_hash, self.hashes,
                self.baseline)

        duplicate = self.state_path("duplicate-state.json")
        duplicate.write_text('{"schema":"a","schema":"b"}\n')
        with self.assertRaisesRegex(isp.SafetyError, "duplicate JSON key"):
            isp._strict_json_load(duplicate)

    def test_program_cut_requires_a_new_read_only_reconciliation_session(self):
        prepared_a = isp.image_prepare_a_count(
            self.baseline, len(isp.PREPARE_A_WRITES))
        post = isp.image_after_program_cut(self.baseline)
        state_path = self.state_path("program-cut.json")
        isp.write_state_atomic(
            state_path, self.stable_state("prepare_a_verified", prepared_a),
            require_absent=True)
        first_device = FakeDevice()
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                isp.ReconciliationRequired, "planned no-readback"):
            isp.execute_stage(
                "program-cut", self.baseline, self.manifest, state_path,
                progress=False, device_factory=lambda: first_device,
                read_full_fn=ReadScript([prepared_a]))
        self.assertTrue(first_device.closed)
        pending = isp._strict_json_load(state_path)
        self.assertEqual(pending["status"], "intent_pending")
        self.assertEqual(pending["intent"]["offset"], isp.WORK_B_SECTOR)

        second_device = FakeDevice()
        reads = ReadScript([post, post])
        with redirect_stdout(io.StringIO()):
            result = isp.execute_stage(
                "reconcile", self.baseline, self.manifest, state_path,
                progress=False, device_factory=lambda: second_device,
                read_full_fn=reads)
        self.assertEqual(result, 0)
        self.assertTrue(second_device.closed)
        self.assertEqual(reads.calls, 2)
        self.assertEqual(
            isp._strict_json_load(state_path)["status"],
            "program_cut_verified")
        self.assertIsNone(isp._strict_json_load(state_path)["intent"])

    def test_prepare_a_programs_each_fixed_block_and_publishes_checkpoint(self):
        state_path = self.state_path("prepare-a.json")
        device = FakeDevice()
        calls = 0

        def read_full(_device):
            nonlocal calls
            calls += 1
            # First read is the stage preimage; each following read is the
            # exact image after that numbered one-block program.
            return isp.image_prepare_a_count(self.baseline, calls - 1)

        with redirect_stdout(io.StringIO()):
            result = isp.execute_stage(
                "prepare-a", self.baseline, self.manifest, state_path,
                progress=False, device_factory=lambda: device,
                read_full_fn=read_full)
        self.assertEqual(result, 0)
        self.assertEqual(calls, len(isp.PREPARE_A_WRITES) + 1)
        self.assertEqual(
            len([event for event in device.events if event[0] == "program"]),
            len(isp.PREPARE_A_WRITES))
        state = isp._strict_json_load(state_path)
        self.assertEqual(state["status"], "prepare_a_verified")
        self.assertIsNone(state["intent"])

    def test_reconcile_exact_preimage_does_not_retry_or_advance(self):
        prepared_a = isp.image_prepare_a_count(
            self.baseline, len(isp.PREPARE_A_WRITES))
        state_path = self.state_path("preimage-reconcile.json")
        intent = isp.canonical_operations(self.baseline)[9]
        isp.write_state_atomic(
            state_path,
            isp._state(
                self.identity, self.manifest, self.baseline_hash, self.hashes,
                "intent_pending", intent["pre_image_sha256"], intent),
            require_absent=True)
        device = FakeDevice()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = isp.execute_stage(
                "reconcile", self.baseline, self.manifest, state_path,
                progress=False, device_factory=lambda: device,
                read_full_fn=ReadScript([prepared_a, prepared_a]))
        self.assertEqual(result, 0)
        self.assertEqual(
            isp._strict_json_load(state_path)["status"], "prepare_a_verified")
        self.assertFalse(any(event[0] == "program" for event in device.events))
        self.assertIn('"automatic_retry": false', stdout.getvalue())

    def test_unstable_or_noncanonical_reconciliation_requires_spi(self):
        prepared_a = isp.image_prepare_a_count(
            self.baseline, len(isp.PREPARE_A_WRITES))
        post = isp.image_after_program_cut(self.baseline)
        intent = isp.canonical_operations(self.baseline)[9]
        for name, images, message in (
                ("unstable", [prepared_a, post], "captures differ"),
                ("partial", [
                    prepared_a[:isp.WORK_B_SECTOR] + b"\xfe" +
                    prepared_a[isp.WORK_B_SECTOR + 1:]
                ] * 2, "neither")):
            state_path = self.state_path(f"{name}.json")
            isp.write_state_atomic(
                state_path,
                isp._state(
                    self.identity, self.manifest, self.baseline_hash,
                    self.hashes, "intent_pending",
                    intent["pre_image_sha256"], intent),
                require_absent=True)
            device = FakeDevice()
            with self.subTest(name=name), redirect_stdout(io.StringIO()), \
                    self.assertRaisesRegex(isp.RecoveryRequired, message):
                isp.execute_stage(
                    "reconcile", self.baseline, self.manifest, state_path,
                    progress=False, device_factory=lambda: device,
                    read_full_fn=ReadScript(images))
            self.assertEqual(
                isp._strict_json_load(state_path)["status"], "intent_pending")

    def test_transport_failure_after_intent_is_reconcilable_not_replayed(self):
        prepared_a = isp.image_prepare_a_count(
            self.baseline, len(isp.PREPARE_A_WRITES))
        state_path = self.state_path("failed-command.json")
        isp.write_state_atomic(
            state_path, self.stable_state("prepare_a_verified", prepared_a),
            require_absent=True)
        failed = FakeDevice(fail_program=True)
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                isp.ReconciliationRequired, "completion is unknown"):
            isp.execute_stage(
                "program-cut", self.baseline, self.manifest, state_path,
                progress=False, device_factory=lambda: failed,
                read_full_fn=ReadScript([prepared_a]))
        self.assertEqual(
            isp._strict_json_load(state_path)["status"], "intent_pending")

    def test_normal_cleanup_uses_fixed_erase_and_restores_exact_baseline(self):
        before = isp.image_after_cleanup_lower(self.baseline)
        state_path = self.state_path("final-cleanup.json")
        isp.write_state_atomic(
            state_path, self.stable_state("lower_cleanup_verified", before),
            require_absent=True)
        device = FakeDevice()
        reads = ReadScript([before, self.baseline])
        with redirect_stdout(io.StringIO()):
            result = isp.execute_stage(
                "cleanup-upper", self.baseline, self.manifest, state_path,
                progress=False, device_factory=lambda: device,
                read_full_fn=reads)
        self.assertEqual(result, 0)
        self.assertFalse(state_path.exists())
        self.assertTrue(device.closed)
        simplified = [
            (event[0], event[1]) for event in device.events
            if event[0] == "cmd"
        ]
        self.assertIn(("cmd", isp.SUB_EX4B), simplified)
        erase = [
            event for event in device.events
            if event[0] == "cmd" and event[1] == isp._writer.SUB_ERASE
        ]
        self.assertEqual(
            erase[0][2], isp.cdb_erase(isp.UPPER_GUARD_SECTOR))

    def test_dry_run_opens_no_usb_and_cli_has_no_raw_mutation_options(self):
        state_path = self.state_path("dry-run.json")
        argv = [
            str(TOOL), "--stage", "prepare-a",
            "--baseline-a", str(self.baseline_a),
            "--baseline-b", str(self.baseline_b),
            "--state-file", str(state_path),
        ]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(isp, "execute_stage") as execute, \
                mock.patch.object(
                    isp._writer._verify, "_load_libusb") as load_libusb, \
                redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            result = isp.main()
        self.assertEqual(result, 0)
        execute.assert_not_called()
        load_libusb.assert_not_called()
        self.assertFalse(state_path.exists())
        self.assertIn("no USB device was opened", stdout.getvalue())
        help_text = subprocess_help()
        for forbidden in ("--offset", "--cdb", "--payload", "--force",
                          "--skip", "--device"):
            self.assertNotIn(forbidden, help_text)


def subprocess_help():
    parser = argparse_from_main()
    return parser


def argparse_from_main():
    # Capture the real parser output without opening USB or allocating another
    # 32-MiB fixture. argparse exits before baseline loading for --help.
    stdout = io.StringIO()
    with mock.patch.object(sys, "argv", [str(TOOL), "--help"]), \
            redirect_stdout(stdout), self_contained_system_exit():
        isp.main()
    return stdout.getvalue()


class self_contained_system_exit:
    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, _traceback):
        return exception_type is SystemExit and exception.code == 0


if __name__ == "__main__":
    unittest.main()
