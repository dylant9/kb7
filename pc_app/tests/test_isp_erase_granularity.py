"""Offline safety-contract tests for the KB7 erase-footprint experiment.

All flash images and loader replies in this module are synthetic.  No test
opens USB or imports proprietary firmware data.
"""

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
TOOL_PATH = (
    ROOT / "tools" / "flash-access" / "kb7-isp-erase-granularity.py")
MODULE_NAME = "kb7_isp_erase_granularity_under_test"
PRODUCTION_LOADER_SHA256 = (
    "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56")

_SPEC = importlib.util.spec_from_file_location(MODULE_NAME, TOOL_PATH)
isp = importlib.util.module_from_spec(_SPEC)
sys.modules[MODULE_NAME] = isp
_SPEC.loader.exec_module(isp)


def make_v122_image():
    """Build a synthetic image with the exact reviewed V1.22 geometry."""
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

    # The required zero-length SRAM mapping aliases region 1's store address.
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
    identity = {
        "device_path": path,
        "identify_hex": writer.LOADER_IDENT.hex(),
        "descriptor_sha256": writer.sha256_bytes(stable),
        "loader_fingerprint_sha256": writer.sha256_bytes(
            writer.LOADER_IDENT + stable),
    }
    return bytes(descriptor), identity


class FakeDevice:
    """Strict-enough BOT facade with a chronological event log."""

    def __init__(self, path="7-2.3", fail_subcode=None,
                 interrupt_program=False):
        self.device_path = path
        self.descriptor, _identity = accepted_identity(path)
        self.events = []
        self.program_calls = []
        self.fail_subcode = fail_subcode
        self.interrupt_program = interrupt_program
        self.closed = False

    def cmd(self, cdb, data_len=0):
        cdb = bytes(cdb)
        subcode = cdb[1]
        self.events.append(("cmd", subcode, cdb, data_len))
        if subcode == self.fail_subcode:
            raise RuntimeError("synthetic transport failure")
        if subcode == isp._writer.SUB_IDENTIFY:
            return isp._writer.LOADER_IDENT, 0, 0
        if subcode == isp._writer.SUB_DESC:
            return self.descriptor, 0, 0
        if subcode == isp._writer.SUB_STATUS:
            return b"\x00", 0, 0
        return b"", 0, 0

    def program(self, cdb, data):
        cdb = bytes(cdb)
        payload = bytes(data)
        self.events.append(("program", cdb[1], cdb, len(payload)))
        self.program_calls.append((cdb, payload))
        if self.interrupt_program:
            raise KeyboardInterrupt

    def close(self):
        self.closed = True


class ReadScript:
    """Return lazily-created full images while logging capture boundaries."""

    def __init__(self, device, factory):
        self.device = device
        self.factory = factory
        self.calls = 0

    def __call__(self, _device):
        self.calls += 1
        self.device.events.append(("read-full", self.calls))
        return self.factory(self.calls)


class EraseGranularityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Independently pin the production hash without embedding proprietary
        # loader bytes in this synthetic test fixture.
        if isp.EXPECTED_LOADER_SHA256 != PRODUCTION_LOADER_SHA256:
            raise AssertionError("the production V1.22 loader hash changed")
        cls.production_loader_hash = isp.EXPECTED_LOADER_SHA256
        cls.production_plan_hash = isp.PLAN_SHA256
        cls.baseline = make_v122_image()
        cls.synthetic_loader_hash = isp.sha256_bytes(
            cls.baseline[
                isp.LOADER_OFFSET:isp.LOADER_OFFSET + isp.LOADER_SIZE])
        if cls.synthetic_loader_hash == cls.production_loader_hash:
            raise AssertionError("synthetic loader unexpectedly matches production")

        # The implementation module has a test-only import name. Rebind its
        # loader pin to the synthetic bytes, and recompute the plan which
        # deliberately commits to that synthetic hash.
        isp.EXPECTED_LOADER_SHA256 = cls.synthetic_loader_hash
        isp.PLAN_SHA256 = isp._plan_sha256()
        cls.manifest = isp.parse_manifest(cls.baseline)
        cls.baseline_hash = isp.sha256_bytes(cls.baseline)
        cls.image_hashes = isp._image_hashes(cls.baseline)
        cls.temporary = tempfile.TemporaryDirectory()
        cls.baseline_path = Path(cls.temporary.name) / "synthetic-v122.bin"
        cls.baseline_path.write_bytes(cls.baseline)
        cls.descriptor, cls.identity = accepted_identity()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()
        isp.EXPECTED_LOADER_SHA256 = cls.production_loader_hash
        isp.PLAN_SHA256 = cls.production_plan_hash

    def state_path(self, name):
        return Path(self.temporary.name) / name

    def write_stage_state(self, path, status, image):
        isp.write_state_atomic(
            path,
            isp._state_fields(
                self.identity, self.manifest, self.baseline_hash,
                self.image_hashes, status, isp.sha256_bytes(image)))

    def test_fixed_program_and_erase_cdb_vectors(self):
        program_vectors = (
            (0x000C5E00,
             "f6 06 00 60 0c 5e 00 00 01 00 00 00 00 00 00 00"),
            (0x000C6000,
             "f6 06 00 60 0c 60 00 00 01 00 00 00 00 00 00 00"),
            (0x000C6200,
             "f6 06 00 60 0c 62 00 00 01 00 00 00 00 00 00 00"),
            (0x000C6400,
             "f6 06 00 60 0c 64 00 00 01 00 00 00 00 00 00 00"),
            (0x000C6600,
             "f6 06 00 60 0c 66 00 00 01 00 00 00 00 00 00 00"),
            (0x000C6800,
             "f6 06 00 60 0c 68 00 00 01 00 00 00 00 00 00 00"),
            (0x000C6A00,
             "f6 06 00 60 0c 6a 00 00 01 00 00 00 00 00 00 00"),
            (0x000C6C00,
             "f6 06 00 60 0c 6c 00 00 01 00 00 00 00 00 00 00"),
            (0x000C6E00,
             "f6 06 00 60 0c 6e 00 00 01 00 00 00 00 00 00 00"),
            (0x000C7000,
             "f6 06 00 60 0c 70 00 00 01 00 00 00 00 00 00 00"),
        )
        self.assertEqual(
            tuple(offset for offset, _payload in isp.PREPARE_WRITES),
            tuple(offset for offset, _vector in program_vectors))
        for offset, vector in program_vectors:
            with self.subTest(program=hex(offset)):
                self.assertEqual(
                    isp.cdb_program(offset, isp.BLOCK),
                    bytes.fromhex(vector))

        erase_vectors = (
            (0x000C5000,
             "f6 15 00 06 28 00 00 00 00 00 00 00 00 00 00 00"),
            (0x000C6000,
             "f6 15 00 06 30 00 00 00 00 00 00 00 00 00 00 00"),
            (0x000C7000,
             "f6 15 00 06 38 00 00 00 00 00 00 00 00 00 00 00"),
        )
        for offset, vector in erase_vectors:
            with self.subTest(erase=hex(offset)):
                self.assertEqual(isp.cdb_erase(offset), bytes.fromhex(vector))

    def test_plan_binds_literal_geometry_commands_modes_and_source_hashes(self):
        descriptor = isp.plan_descriptor()
        self.assertEqual(
            set(descriptor),
            {
                "schema", "loader_sha256", "flash_size", "block_size",
                "sector_size", "sub16_address_mode", "envelope",
                "lower_sector", "target_sector", "upper_sector", "writes",
                "erases", "source_sha256",
            })
        self.assertEqual(descriptor["schema"],
                         "kb7-isp-erase-granularity-state-v1")
        self.assertEqual(descriptor["loader_sha256"],
                         self.synthetic_loader_hash)
        self.assertEqual(descriptor["flash_size"], 0x02000000)
        self.assertEqual(descriptor["block_size"], 0x200)
        self.assertEqual(descriptor["sector_size"], 0x1000)
        self.assertEqual(descriptor["sub16_address_mode"], 0x18)
        self.assertEqual(descriptor["envelope"], [0x000C0000, 0x00100000])
        self.assertEqual(descriptor["lower_sector"], 0x000C5000)
        self.assertEqual(descriptor["target_sector"], 0x000C6000)
        self.assertEqual(descriptor["upper_sector"], 0x000C7000)

        expected_write_offsets = (
            0x000C5E00, 0x000C6000, 0x000C6200, 0x000C6400,
            0x000C6600, 0x000C6800, 0x000C6A00, 0x000C6C00,
            0x000C6E00, 0x000C7000,
        )
        expected_write_cdbs = (
            "f60600600c5e00000100000000000000",
            "f60600600c6000000100000000000000",
            "f60600600c6200000100000000000000",
            "f60600600c6400000100000000000000",
            "f60600600c6600000100000000000000",
            "f60600600c6800000100000000000000",
            "f60600600c6a00000100000000000000",
            "f60600600c6c00000100000000000000",
            "f60600600c6e00000100000000000000",
            "f60600600c7000000100000000000000",
        )
        self.assertEqual(
            tuple(item["offset"] for item in descriptor["writes"]),
            expected_write_offsets)
        self.assertEqual(
            tuple(item["cdb_hex"] for item in descriptor["writes"]),
            expected_write_cdbs)
        self.assertEqual(
            tuple(item["sha256"] for item in descriptor["writes"]),
            tuple(
                hashlib.sha256(payload).hexdigest()
                for _offset, payload in isp.PREPARE_WRITES))

        self.assertEqual(
            descriptor["erases"],
            [
                {
                    "offset": 0x000C6000,
                    "cdb_hex": "f6150006300000000000000000000000",
                },
                {
                    "offset": 0x000C5000,
                    "cdb_hex": "f6150006280000000000000000000000",
                },
                {
                    "offset": 0x000C7000,
                    "cdb_hex": "f6150006380000000000000000000000",
                },
            ])

        source_paths = {
            "experiment": TOOL_PATH,
            "writer": ROOT / "tools" / "flash-access" / "kb7-isp-write2.py",
            "verifier": ROOT / "tools" / "flash-access" / "kb7-isp-verify.py",
        }
        self.assertEqual(set(descriptor["source_sha256"]), set(source_paths))
        self.assertEqual(
            descriptor["source_sha256"],
            {
                name: hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in source_paths.items()
            })
        self.assertEqual(isp._plan_sha256(), isp.PLAN_SHA256)

        # A command-byte or source-code hash change must produce a distinct
        # plan, so stale stage state cannot authorize it.
        original_cdb_program = isp.cdb_program

        def changed_cdb_program(offset, nbytes):
            cdb = bytearray(original_cdb_program(offset, nbytes))
            cdb[-1] = 1
            return bytes(cdb)

        with mock.patch.object(isp, "cdb_program", changed_cdb_program):
            self.assertNotEqual(isp._plan_sha256(), isp.PLAN_SHA256)
        with mock.patch.object(isp, "_source_sha256", return_value="0" * 64):
            self.assertNotEqual(isp._plan_sha256(), isp.PLAN_SHA256)

    def test_patterns_are_unique_full_blocks_with_one_cleared_bit_per_byte(self):
        self.assertEqual(len(isp.PATTERNS), 10)
        self.assertEqual(len(set(isp.PATTERNS)), 10)
        for index, pattern in enumerate(isp.PATTERNS):
            with self.subTest(index=index):
                self.assertEqual(len(pattern), isp.BLOCK)
                self.assertNotIn(0xFF, pattern)
                self.assertTrue(all(
                    ((~value) & 0xFF).bit_count() == 1
                    for value in pattern))
        self.assertEqual(isp.LOWER_GUARD, isp.PATTERNS[0])
        self.assertEqual(isp.TARGET_PAYLOAD, b"".join(isp.PATTERNS[1:9]))
        self.assertEqual(isp.UPPER_GUARD, isp.PATTERNS[9])

    def test_exact_v122_geometry_and_complete_256k_erased_envelope(self):
        self.assertEqual(
            self.production_loader_hash, PRODUCTION_LOADER_SHA256)
        self.assertEqual(
            isp.validate_loader_window(self.baseline),
            self.synthetic_loader_hash)
        geometry = tuple(
            (region.load, region.offset, region.length)
            for region in sorted(
                self.manifest.regions, key=lambda region: region.index))
        self.assertEqual(geometry, isp.EXPECTED_REGION_GEOMETRY)
        self.assertEqual(
            (self.manifest.scratch_lo, self.manifest.scratch_hi),
            isp.EXPECTED_SCRATCH)
        self.assertEqual(isp.ENVELOPE_HI - isp.ENVELOPE_LO, 0x40000)
        isp.validate_baseline_window(self.baseline, self.manifest)

        # A programmed byte anywhere in the containment envelope must refuse
        # the experiment, even when it is far outside the three test sectors.
        changed = bytearray(self.baseline)
        for offset in (
                isp.ENVELOPE_LO, isp.LOWER_SECTOR - 1,
                isp.UPPER_SECTOR + isp.SECTOR, isp.ENVELOPE_HI - 1):
            changed[offset] = 0x7F
            with self.subTest(offset=hex(offset)), self.assertRaisesRegex(
                    isp.SafetyError, "256-KiB containment envelope"):
                isp.validate_baseline_window(bytes(changed), self.manifest)
            changed[offset] = 0xFF

        # Geometry is a fixed reviewed precondition, not merely any manifest
        # which happens to expose a sufficiently large gap.
        regions = list(self.manifest.regions)
        region = regions[1]
        regions[1] = isp._writer.Region(
            region.index, region.load, region.store, region.offset,
            region.length - isp.BLOCK, region.checksum)
        other_layout = isp._writer.ManifestInfo(
            self.manifest.sha256, tuple(regions),
            self.manifest.scratch_lo, self.manifest.scratch_hi)
        with self.assertRaisesRegex(isp.SafetyError, "reviewed V1.22 layout"):
            isp.validate_v122_layout(other_layout)

    def test_loader_mutation_is_rejected_before_usb_or_state_creation(self):
        changed = bytearray(self.baseline)
        changed[isp.LOADER_OFFSET + isp.LOADER_SIZE // 2] = 0x7F
        changed = bytes(changed)
        with self.assertRaisesRegex(
                isp.SafetyError, "preserved ISP loader hash"):
            isp.validate_baseline_window(changed, self.manifest)

        state_path = self.state_path("bad-loader-state.json")
        device_factory = mock.Mock()
        with self.assertRaisesRegex(
                isp.SafetyError, "preserved ISP loader hash"):
            isp.execute_stage(
                "prepare", changed, self.manifest, str(state_path),
                progress=False, device_factory=device_factory,
                read_full_fn=lambda _device: changed)
        device_factory.assert_not_called()
        self.assertFalse(state_path.exists())

    def test_expected_phase_images_have_only_the_intended_differences(self):
        prepared = isp.prepared_image(self.baseline)
        target_erased = isp.target_erased_image(self.baseline)
        lower_cleaned = isp.lower_cleaned_image(self.baseline)

        self.assertEqual(
            isp._writer.difference_summary(self.baseline, prepared),
            (10 * isp.BLOCK,
             [(isp.LOWER_GUARD_OFFSET,
               isp.UPPER_GUARD_OFFSET + isp.BLOCK - 1)]))
        self.assertEqual(
            isp._writer.difference_summary(prepared, target_erased),
            (isp.SECTOR,
             [(isp.TARGET_SECTOR,
               isp.TARGET_SECTOR + isp.SECTOR - 1)]))
        self.assertEqual(
            isp._writer.difference_summary(target_erased, lower_cleaned),
            (isp.BLOCK,
             [(isp.LOWER_GUARD_OFFSET,
               isp.LOWER_GUARD_OFFSET + isp.BLOCK - 1)]))
        self.assertEqual(
            isp._writer.difference_summary(lower_cleaned, self.baseline),
            (isp.BLOCK,
             [(isp.UPPER_GUARD_OFFSET,
               isp.UPPER_GUARD_OFFSET + isp.BLOCK - 1)]))

        self.assertEqual(
            prepared[
                isp.LOWER_GUARD_OFFSET:
                isp.LOWER_GUARD_OFFSET + isp.BLOCK],
            isp.LOWER_GUARD)
        self.assertEqual(
            prepared[isp.TARGET_SECTOR:isp.TARGET_SECTOR + isp.SECTOR],
            isp.TARGET_PAYLOAD)
        self.assertEqual(
            target_erased[
                isp.TARGET_SECTOR:isp.TARGET_SECTOR + isp.SECTOR],
            b"\xff" * isp.SECTOR)
        self.assertEqual(
            target_erased[
                isp.LOWER_GUARD_OFFSET:
                isp.LOWER_GUARD_OFFSET + isp.BLOCK],
            isp.LOWER_GUARD)
        self.assertEqual(
            target_erased[
                isp.UPPER_GUARD_OFFSET:
                isp.UPPER_GUARD_OFFSET + isp.BLOCK],
            isp.UPPER_GUARD)

    def test_dry_run_validates_but_never_opens_usb(self):
        state_path = self.state_path("dry-run-state.json")
        argv = [
            str(TOOL_PATH), "--stage", "prepare", "--baseline",
            str(self.baseline_path), "--state-file", str(state_path),
        ]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(isp, "execute_stage") as execute_stage, \
                mock.patch.object(
                    isp._writer._verify, "_load_libusb") as load_libusb, \
                redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            result = isp.main()
        self.assertEqual(result, 0)
        execute_stage.assert_not_called()
        load_libusb.assert_not_called()
        self.assertFalse(state_path.exists())
        self.assertIn("No USB device was opened", stdout.getvalue())

    def test_stage_skipping_tampering_and_started_states_are_refused(self):
        prepared = isp.prepared_image(self.baseline)
        target_erased = isp.target_erased_image(self.baseline)
        lower_cleaned = isp.lower_cleaned_image(self.baseline)
        state_path = self.state_path("gating-state.json")

        with self.assertRaises(isp.SafetyError):
            isp._load_stage_state(
                "erase-target", state_path, self.manifest,
                self.baseline_hash, self.image_hashes, prepared)

        # Each later stage refuses a valid state from the preceding-but-wrong
        # phase; callers cannot skip the target proof or either cleanup.
        cases = (
            ("cleanup-lower", "prepared_verified", prepared),
            ("cleanup-upper", "target_erased_verified", target_erased),
            ("erase-target", "target_erase_started", prepared),
            ("cleanup-lower", "lower_cleanup_started", target_erased),
            ("cleanup-upper", "upper_cleanup_started", lower_cleaned),
        )
        for stage, status, image in cases:
            self.write_stage_state(state_path, status, image)
            with self.subTest(stage=stage, status=status), self.assertRaises(
                    isp.SafetyError):
                isp._load_stage_state(
                    stage, state_path, self.manifest, self.baseline_hash,
                    self.image_hashes, isp._expected_stage_images(
                        stage, self.baseline)[0])

        # Prepare never overwrites any prior authorization, including a
        # consumed/started one.
        with self.assertRaisesRegex(isp.SafetyError, "already exists"):
            isp._load_stage_state(
                "prepare", state_path, self.manifest, self.baseline_hash,
                self.image_hashes, self.baseline)

        valid = isp._state_fields(
            self.identity, self.manifest, self.baseline_hash,
            self.image_hashes, "prepared_verified",
            isp.sha256_bytes(prepared))
        self.assertEqual(
            valid["loader_window_sha256"], self.synthetic_loader_hash)
        tampered_values = {
            "manifest_sha256": "0" * 64,
            "loader_window_sha256": self.production_loader_hash,
            "baseline_sha256": "1" * 64,
            "plan_sha256": "2" * 64,
            "target_payload_sha256": "3" * 64,
            "current_image_sha256": "4" * 64,
            "target_sector_offset": isp.TARGET_SECTOR + isp.SECTOR,
        }
        for key, value in tampered_values.items():
            tampered = dict(valid)
            tampered[key] = value
            with self.subTest(tampered=key), self.assertRaises(isp.SafetyError):
                isp.validate_static_state(
                    tampered, self.manifest, self.baseline_hash,
                    self.image_hashes, "prepared_verified",
                    isp.sha256_bytes(prepared))

        for key, value in (
                ("device_path", "8-1"),
                ("descriptor_sha256", "5" * 64),
                ("loader_fingerprint_sha256", "6" * 64)):
            tampered = dict(valid)
            tampered[key] = value
            with self.subTest(connected_binding=key), self.assertRaises(
                    isp.SafetyError):
                isp.validate_connected_state(
                    tampered, self.identity, self.manifest,
                    self.baseline_hash, self.image_hashes,
                    "prepared_verified", isp.sha256_bytes(prepared))

    def test_prepare_order_and_full_read_after_every_program(self):
        state_path = self.state_path("prepare-order-state.json")
        device = FakeDevice()

        def image_for_read(call):
            if call == 1:
                return self.baseline
            return isp.image_after_prepare_count(self.baseline, call - 1)

        reads = ReadScript(device, image_for_read)
        with redirect_stdout(io.StringIO()):
            result = isp.execute_stage(
                "prepare", self.baseline, self.manifest, str(state_path),
                progress=False, device_factory=lambda: device,
                read_full_fn=reads)

        self.assertEqual(result, 0)
        self.assertTrue(device.closed)
        self.assertEqual(reads.calls, 11)
        self.assertEqual(
            device.program_calls,
            [
                (isp.cdb_program(offset, isp.BLOCK), payload)
                for offset, payload in isp.PREPARE_WRITES
            ])

        expected_events = [
            ("cmd", isp._writer.SUB_IDENTIFY),
            ("cmd", isp._writer.SUB_DESC),
            ("cmd", isp.SUB_EN4B),
            ("read-full", 1),
        ]
        for index in range(10):
            expected_events.extend((
                ("cmd", isp.SUB_EX4B),
                ("program", isp._writer.SUB_PROGRAM),
                ("cmd", isp._writer.SUB_STATUS),
                ("cmd", isp.SUB_EN4B),
                ("read-full", index + 2),
            ))
        simplified = [
            event[:2] for event in device.events
        ]
        self.assertEqual(simplified, expected_events)

        state = isp.load_state(state_path)
        self.assertEqual(state["status"], "prepared_verified")
        self.assertEqual(
            state["current_image_sha256"],
            self.image_hashes["prepared_image_sha256"])

    def test_erase_and_cleanup_sequences_advance_and_finally_clear_state(self):
        prepared = isp.prepared_image(self.baseline)
        target_erased = isp.target_erased_image(self.baseline)
        lower_cleaned = isp.lower_cleaned_image(self.baseline)
        state_path = self.state_path("lifecycle-state.json")
        self.write_stage_state(state_path, "prepared_verified", prepared)

        stages = (
            ("erase-target", prepared, target_erased,
             isp.TARGET_SECTOR, "target_erased_verified", True),
            ("cleanup-lower", target_erased, lower_cleaned,
             isp.LOWER_SECTOR, "lower_cleaned_verified", True),
            ("cleanup-upper", lower_cleaned, self.baseline,
             isp.UPPER_SECTOR, None, False),
        )
        for stage, before, after, offset, next_status, remains in stages:
            device = FakeDevice()
            reads = ReadScript(
                device, lambda call, before=before, after=after:
                before if call == 1 else after)
            with self.subTest(stage=stage), redirect_stdout(io.StringIO()):
                result = isp.execute_stage(
                    stage, self.baseline, self.manifest, str(state_path),
                    progress=False, device_factory=lambda: device,
                    read_full_fn=reads)
            self.assertEqual(result, 0)
            self.assertTrue(device.closed)
            self.assertEqual(reads.calls, 2)
            self.assertEqual(
                [event[:2] for event in device.events],
                [
                    ("cmd", isp._writer.SUB_IDENTIFY),
                    ("cmd", isp._writer.SUB_DESC),
                    ("cmd", isp.SUB_EN4B),
                    ("read-full", 1),
                    ("cmd", isp.SUB_EX4B),
                    ("cmd", isp._writer.SUB_ERASE),
                    ("cmd", isp._writer.SUB_STATUS),
                    ("cmd", isp.SUB_EN4B),
                    ("read-full", 2),
                ])
            erase_events = [
                event for event in device.events
                if event[0] == "cmd" and event[1] == isp._writer.SUB_ERASE]
            self.assertEqual(len(erase_events), 1)
            self.assertEqual(erase_events[0][2], isp.cdb_erase(offset))
            self.assertEqual(state_path.exists(), remains)
            if remains:
                self.assertEqual(isp.load_state(state_path)["status"], next_status)

    def test_failed_mutation_is_unknown_and_consumes_stage_authorization(self):
        # An interrupt after program dispatch leaves a non-replayable started
        # state and is promoted to an explicitly unknown mutation result.
        prepare_state = self.state_path("interrupted-prepare-state.json")
        interrupted = FakeDevice(interrupt_program=True)
        reads = ReadScript(interrupted, lambda _call: self.baseline)
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                isp.MutationResultUnknown, "operator interruption"):
            isp.execute_stage(
                "prepare", self.baseline, self.manifest,
                str(prepare_state), progress=False,
                device_factory=lambda: interrupted, read_full_fn=reads)
        self.assertTrue(interrupted.closed)
        self.assertEqual(
            isp.load_state(prepare_state)["status"],
            "prepare_block_01_started")

        # The same fail-closed rule applies to an anomalous erase transfer.
        prepared = isp.prepared_image(self.baseline)
        erase_state = self.state_path("failed-erase-state.json")
        self.write_stage_state(erase_state, "prepared_verified", prepared)
        failed = FakeDevice(fail_subcode=isp._writer.SUB_ERASE)
        reads = ReadScript(failed, lambda _call: prepared)
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                isp.MutationResultUnknown, "mutation may have occurred"):
            isp.execute_stage(
                "erase-target", self.baseline, self.manifest,
                str(erase_state), progress=False,
                device_factory=lambda: failed, read_full_fn=reads)
        self.assertTrue(failed.closed)
        self.assertEqual(
            isp.load_state(erase_state)["status"],
            "target_erase_started")


if __name__ == "__main__":
    unittest.main()
