from __future__ import annotations

import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "flash-access" / "kb7-updater-plan.py"
SPEC = importlib.util.spec_from_file_location("kb7_updater_plan_tested", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
UPDATER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = UPDATER
SPEC.loader.exec_module(UPDATER)


def balanced_region(spec: object) -> bytes:
    """Make synthetic stock bytes with the real manifest checksum."""
    data = bytearray(b"\xff" * spec.length)
    data[:16] = (b"synthetic-" + spec.name.encode("ascii"))[:16].ljust(16, b"!")
    chunk_start = ((spec.length - 1) // 0x10000) * 0x10000
    chunk_end = spec.length
    patch_offset = chunk_start + 0x80
    other_sum = sum(
        zlib.crc32(data[offset:min(offset + 0x10000, spec.length)]) & 0xFFFFFFFF
        for offset in range(0, spec.length, 0x10000)
        if offset != chunk_start
    ) & 0xFFFFFFFF
    wanted = (spec.manifest_checksum - other_sum) & 0xFFFFFFFF
    patch, rank = UPDATER.crc_patch(
        bytes(data[chunk_start:chunk_end]), patch_offset - chunk_start, wanted
    )
    assert rank == 32
    data[patch_offset:patch_offset + 4] = patch
    assert UPDATER.fwin_checksum(data) == spec.manifest_checksum
    return bytes(data)


def synthetic_baseline() -> tuple[bytes, dict[str, str]]:
    image = bytearray(b"\xff" * UPDATER.FLASH_BYTES)
    image[:8] = b"SNC7320A"
    image[UPDATER.LOADER_START:UPDATER.MANIFEST_START] = \
        b"L" * (UPDATER.MANIFEST_START - UPDATER.LOADER_START)

    core0 = balanced_region(UPDATER.CORE0)
    core1 = balanced_region(UPDATER.CORE1)
    image[UPDATER.CORE0_START:UPDATER.CORE0_START + len(core0)] = core0
    image[UPDATER.CORE1_START:UPDATER.CORE1_START + len(core1)] = core1

    region2 = bytes(image[
        UPDATER.REGION2_START:UPDATER.REGION2_START + UPDATER.REGION2_LENGTH
    ])
    manifest = bytearray(b"\xff" * UPDATER.SECTOR_BYTES)
    manifest[:8] = b"SN_FWIN\0"
    manifest[8:16] = b"v1.0.00\0"
    records = (
        (UPDATER.CORE0_VMA, UPDATER.FLASH_BASE + UPDATER.CORE0_START,
         UPDATER.CORE0_LENGTH, UPDATER.CORE0.manifest_checksum),
        (UPDATER.CORE1_VMA, UPDATER.FLASH_BASE + UPDATER.CORE1_START,
         UPDATER.CORE1_LENGTH, UPDATER.CORE1.manifest_checksum),
        (UPDATER.FLASH_BASE + UPDATER.REGION2_START,
         UPDATER.FLASH_BASE + UPDATER.REGION2_START,
         UPDATER.REGION2_LENGTH, UPDATER.fwin_checksum(region2)),
        (0x18000000, UPDATER.FLASH_BASE + UPDATER.CORE1_START, 0, 0),
    )
    for offset, record in zip((0x20, 0x30, 0x40, 0x50), records):
        struct.pack_into("<IIII", manifest, offset, *record)
    image[UPDATER.MANIFEST_START:UPDATER.CORE0_START] = manifest
    result = bytes(image)
    anchors = {
        "header": UPDATER.sha256(result[:UPDATER.LOADER_START]),
        "loader": UPDATER.sha256(result[
            UPDATER.LOADER_START:UPDATER.MANIFEST_START
        ]),
        "manifest": UPDATER.sha256(result[
            UPDATER.MANIFEST_START:UPDATER.CORE0_START
        ]),
        "core0": UPDATER.sha256(core0),
        "core1": UPDATER.sha256(core1),
    }
    return result, anchors


def replacement_raw(spec: object) -> bytes:
    raw = bytearray((index * 37 + spec.role * 11) & 0xFF for index in range(0x800))
    if spec is UPDATER.CORE0:
        struct.pack_into("<II", raw, 0, UPDATER.CORE0_STACK, 0x00000301)
    UPDATER.PAIR_STRUCT.pack_into(
        raw, spec.pair_offset, UPDATER.PAIR_MAGIC, UPDATER.PAIR_FORMAT,
        UPDATER.PAIR_BYTES, spec.role, UPDATER.RUNTIME_ABI_VERSION,
        b"\xff" * UPDATER.PAIR_ID_BYTES,
    )
    return bytes(raw)


class UpdaterPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="kb7-updater-tests-")
        cls.root = Path(cls._temporary.name)
        cls.baseline, cls.anchors = synthetic_baseline()
        cls.baseline_a = cls.root / "baseline-a.bin"
        cls.baseline_b = cls.root / "baseline-b.bin"
        cls.baseline_a.write_bytes(cls.baseline)
        cls.baseline_b.write_bytes(cls.baseline)
        cls.core0_elf = cls.root / "core0.elf"
        cls.core1_elf = cls.root / "core1.elf"
        cls.core0_elf.write_bytes(b"synthetic elf zero")
        cls.core1_elf.write_bytes(b"synthetic elf one")
        cls.raw = {
            "core0": replacement_raw(UPDATER.CORE0),
            "core1": replacement_raw(UPDATER.CORE1),
        }

        def fake_extract(elf: Path, spec: object, _prefix: str,
                         destination: Path) -> tuple[bytes, dict[str, object]]:
            raw = cls.raw[spec.name]
            destination.write_bytes(raw)
            entry = 0x301 if spec is UPDATER.CORE0 else UPDATER.CORE1_VMA + 1
            return raw, {
                "entry": f"0x{entry:08x}",
                "raw_length": len(raw),
                "elf_sha256": UPDATER.sha256(elf.read_bytes()),
                "raw_sha256": UPDATER.sha256(raw),
            }

        cls.bundle_dir = cls.root / "bundle"
        cls.descriptor = UPDATER.build_bundle(
            cls.baseline_a, cls.baseline_b, cls.core0_elf, cls.core1_elf,
            cls.bundle_dir, "unused-", anchors=cls.anchors,
            extractor=fake_extract,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_crc_solver_vectors_and_full_rank(self) -> None:
        chunk = bytes((index * 29 + 7) & 0xFF for index in range(4099))
        for wanted in (0, 0xFFFFFFFF, 0x12345678, zlib.crc32(chunk) & 0xFFFFFFFF):
            patch, rank = UPDATER.crc_patch(chunk, 701, wanted)
            corrected = bytearray(chunk)
            corrected[701:705] = patch
            self.assertEqual(zlib.crc32(corrected) & 0xFFFFFFFF, wanted)
            self.assertEqual(rank, 32)
        solution, rank = UPDATER.gf2_solve([1 << index for index in range(32)],
                                           0xA55A6996)
        self.assertEqual((solution, rank), (0xA55A6996, 32))

    def test_exact_two_capture_and_pinned_baseline_gates(self) -> None:
        self.assertEqual(UPDATER.load_baselines(self.baseline_a, self.baseline_b),
                         self.baseline)
        UPDATER.validate_baseline(self.baseline, self.anchors)
        with self.assertRaisesRegex(UPDATER.PlanError, "pinned V1.22"):
            UPDATER.validate_baseline(self.baseline)

        short = self.root / "short.bin"
        short.write_bytes(self.baseline[:-1])
        with self.assertRaisesRegex(UPDATER.PlanError, "exactly"):
            UPDATER.load_baselines(self.baseline_a, short)

        changed = self.root / "changed.bin"
        changed_data = bytearray(self.baseline)
        changed_data[-1] ^= 1
        changed.write_bytes(changed_data)
        with self.assertRaisesRegex(UPDATER.PlanError, "captures differ"):
            UPDATER.load_baselines(self.baseline_a, changed)

        alias = self.root / "baseline-alias.bin"
        os.link(self.baseline_a, alias)
        with self.assertRaisesRegex(UPDATER.PlanError, "aliases"):
            UPDATER.load_baselines(self.baseline_a, alias)

        tampered = bytearray(self.baseline)
        tampered[UPDATER.LOADER_START + 9] ^= 1
        with self.assertRaisesRegex(UPDATER.PlanError, "loader SHA-256"):
            UPDATER.validate_baseline(bytes(tampered), self.anchors)

        # Even mutable user/settings bytes outside the pinned boot regions are
        # part of the plan identity.  Two matching-but-new captures must not be
        # accepted against a bundle made for an older full-chip state.
        rebound_data = bytearray(self.baseline)
        rebound_data[-1] ^= 1
        rebound_a = self.root / "rebound-a.bin"
        rebound_b = self.root / "rebound-b.bin"
        rebound_a.write_bytes(rebound_data)
        rebound_b.write_bytes(rebound_data)
        with self.assertRaisesRegex(UPDATER.PlanError, "different baseline"):
            UPDATER.verify_bundle(
                self.bundle_dir, rebound_a, rebound_b, anchors=self.anchors
            )

    def test_pair_placeholder_and_deterministic_pair_patch(self) -> None:
        pair_id = UPDATER.derive_pair_id(self.raw["core0"], self.raw["core1"])
        self.assertEqual(len(pair_id), UPDATER.PAIR_ID_BYTES)
        self.assertNotIn(pair_id, (b"\0" * 16, b"\xff" * 16))
        self.assertEqual(
            pair_id, UPDATER.derive_pair_id(self.raw["core0"], self.raw["core1"])
        )
        for spec in UPDATER.REGIONS:
            raw = self.raw[spec.name]
            UPDATER.validate_pair_placeholder(raw, spec)
            target, staged, metadata = UPDATER.build_target_region(raw, spec, pair_id)
            marker = UPDATER.PAIR_STRUCT.unpack_from(target, spec.pair_offset)
            self.assertEqual(marker[:5], (
                UPDATER.PAIR_MAGIC, UPDATER.PAIR_FORMAT, UPDATER.PAIR_BYTES,
                spec.role, UPDATER.RUNTIME_ABI_VERSION,
            ))
            self.assertEqual(marker[5], pair_id)
            self.assertEqual(UPDATER.fwin_checksum(target), spec.manifest_checksum)
            self.assertNotEqual(UPDATER.fwin_checksum(staged), spec.manifest_checksum)
            self.assertEqual(metadata["fixup_rank"], 32)
            self.assertEqual(metadata["gate_rank"], 32)
            with self.assertRaisesRegex(UPDATER.PlanError, "reserved"):
                UPDATER.validate_target_region(target, spec, b"\0" * 16,
                                               {"target_sha256": UPDATER.sha256(target)})
            with self.assertRaisesRegex(UPDATER.PlanError, "placeholder"):
                UPDATER.validate_pair_placeholder(target, spec)

        bad_core0 = bytearray(self.raw["core0"])
        struct.pack_into("<I", bad_core0, 4, 0x00002001)
        with self.assertRaisesRegex(UPDATER.PlanError, "reset vector"):
            UPDATER.validate_extracted_image(bytes(bad_core0), UPDATER.CORE0,
                                             0x00002001)

    def test_manifest_and_all_immutable_bytes_are_preserved(self) -> None:
        self.assertEqual(self.descriptor["manifest_operations"], 0)
        simulation = json.loads(
            (self.bundle_dir / "simulation.json").read_text(encoding="utf-8")
        )
        self.assertEqual(simulation["preserved_boot_region_operation_count"], 0)
        self.assertEqual(
            simulation["preserved_boot_regions"],
            UPDATER.preserved_boot_regions(self.baseline),
        )
        image = bytearray(self.baseline)
        operations, _ = UPDATER.build_operations(
            self.baseline,
            {
                "core0": (self.bundle_dir / "core0-sector-image.bin").read_bytes()[
                    :UPDATER.CORE0_LENGTH
                ],
                "core1": (self.bundle_dir / "core1-sector-image.bin").read_bytes()[
                    :UPDATER.CORE1_LENGTH
                ],
            },
            {
                name: self._staged_image(name) for name in ("core0", "core1")
            },
        )
        for operation in operations:
            self.assertGreaterEqual(operation.offset, UPDATER.CORE0_START)
            self.assertLessEqual(operation.offset + operation.length,
                                 UPDATER.CORE1_ENVELOPE_END)
            UPDATER.apply_operation(image, operation)
        self.assertEqual(image[:UPDATER.CORE0_START],
                         self.baseline[:UPDATER.CORE0_START])
        self.assertEqual(image[UPDATER.CORE1_ENVELOPE_END:],
                         self.baseline[UPDATER.CORE1_ENVELOPE_END:])
        self.assertEqual(image[UPDATER.MANIFEST_START:UPDATER.CORE0_START],
                         self.baseline[UPDATER.MANIFEST_START:UPDATER.CORE0_START])

    def _staged_image(self, name: str) -> bytes:
        spec = UPDATER.CORE0 if name == "core0" else UPDATER.CORE1
        target = bytearray((self.bundle_dir / f"{name}-sector-image.bin").read_bytes()[
            :spec.length
        ])
        target[spec.gate_offset:spec.gate_offset + 4] = b"\xff" * 4
        return bytes(target)

    def test_operation_order_and_boot_invariants(self) -> None:
        traces = self.descriptor["operations"]
        phases = [item["phase"] for item in traces]
        self.assertEqual(phases[:2], ["poison_core0", "poison_core1"])
        self.assertEqual(phases[-2:], ["commit_core1", "commit_core0"])
        self.assertNotIn("erase", [item["operation"] for item in traces[:2]])
        self.assertTrue(all(
            phase.startswith(("poison_", "stage_", "commit_")) for phase in phases
        ))
        self.assertLess(max(index for index, phase in enumerate(phases)
                            if phase.startswith("poison_")),
                        min(index for index, phase in enumerate(phases)
                            if phase.startswith("stage_")))
        report = UPDATER.verify_bundle(
            self.bundle_dir, self.baseline_a, self.baseline_b, anchors=self.anchors
        )
        self.assertEqual(report["early_checksum_valid_non_target_states"], 0)
        self.assertEqual(report["command_boundary_prefixes_checked"], len(traces) + 1)
        self.assertFalse(report["hardware_execution_authorized"])
        self.assertFalse(report["flash_approved"])
        self.assertIn("SPI recovery", report["proof_boundary"])

    def test_cdb_encoding_vectors(self) -> None:
        self.assertEqual(
            UPDATER.cdb_program(0x8E000).hex(),
            "f606006008e000000100000000000000",
        )
        self.assertEqual(
            UPDATER.cdb_erase(0x8E000).hex(),
            "f6150004700000000000000000000000",
        )
        with self.assertRaises(UPDATER.PlanError):
            UPDATER.cdb_program(0x8E001)
        with self.assertRaises(UPDATER.PlanError):
            UPDATER.cdb_erase(0x8E200)

    def test_image_derived_reconciliation_ignores_journal_authority(self) -> None:
        pre = bytes(b"\xff" * 1024)
        payload = bytes(b"\x00" * 16 + b"\xff" * (UPDATER.BLOCK_BYTES - 16))
        operation = UPDATER.Operation(
            "stage_core0", "program", 0, payload, "payload.bin", 0
        )
        post = bytearray(pre)
        post[:UPDATER.BLOCK_BYTES] = bytes(
            left & right for left, right in zip(
                post[:UPDATER.BLOCK_BYTES], payload
            )
        )
        partial = bytearray(pre)
        partial[:8] = b"\0" * 8
        self.assertEqual(
            UPDATER.classify_reconciliation(pre, pre, bytes(post), operation),
            "exact_preimage",
        )
        self.assertEqual(
            UPDATER.classify_reconciliation(pre, bytes(post), bytes(post), operation),
            "exact_postimage",
        )
        self.assertEqual(
            UPDATER.classify_reconciliation(pre, bytes(partial), bytes(post), operation),
            "modeled_partial_rebuild_active_sector",
        )
        partial[-1] = 0
        self.assertEqual(
            UPDATER.classify_reconciliation(pre, bytes(partial), bytes(post), operation),
            "spi_recovery_required",
        )

    def test_cli_is_offline_only_and_has_no_commit_surface(self) -> None:
        source = TOOL_PATH.read_text(encoding="utf-8")
        lowered = source.lower()
        for forbidden in (
            "import usb", "from usb", "pyusb", "libusb", "hidraw", "/dev/",
            "--commit", "--device", "bulktransfer", "ctrl_transfer",
        ):
            self.assertNotIn(forbidden, lowered)
        result = subprocess.run(
            [sys.executable, str(TOOL_PATH), "--help"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{build,simulate}", result.stdout)
        self.assertNotIn("commit", result.stdout.lower())

    def test_descriptor_and_payload_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kb7-tamper-") as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(self.bundle_dir, copied)
            descriptor_path = copied / "bundle.json"
            descriptor = json.loads(descriptor_path.read_text())
            descriptor["flash_approved"] = True
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            with self.assertRaisesRegex(UPDATER.PlanError, "fail closed|identifier"):
                UPDATER.load_descriptor(copied)

        with tempfile.TemporaryDirectory(prefix="kb7-payload-tamper-") as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(self.bundle_dir, copied)
            payload = copied / "core0-sector-image.bin"
            data = bytearray(payload.read_bytes())
            data[0x400] ^= 1
            payload.write_bytes(data)
            with self.assertRaisesRegex(UPDATER.PlanError, "does not verify"):
                UPDATER.load_descriptor(copied)

        with tempfile.TemporaryDirectory(prefix="kb7-plan-tamper-") as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(self.bundle_dir, copied)
            descriptor_path = copied / "bundle.json"
            descriptor = json.loads(descriptor_path.read_text())
            descriptor["operations"][2]["offset"] = "0x00010000"
            descriptor["bundle_id"] = UPDATER.canonical_sha256(
                UPDATER.descriptor_without_id(descriptor)
            )
            descriptor_path.write_text(
                json.dumps(descriptor, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(UPDATER.PlanError, "not canonical"):
                UPDATER.verify_bundle(
                    copied, self.baseline_a, self.baseline_b, anchors=self.anchors
                )

        with tempfile.TemporaryDirectory(prefix="kb7-schema-tamper-") as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(self.bundle_dir, copied)
            descriptor_path = copied / "bundle.json"
            descriptor = json.loads(descriptor_path.read_text())
            descriptor["operations"] = {"not": "a list"}
            descriptor["bundle_id"] = UPDATER.canonical_sha256(
                UPDATER.descriptor_without_id(descriptor)
            )
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            with self.assertRaisesRegex(UPDATER.PlanError, "operations field"):
                UPDATER.load_descriptor(copied)

        with tempfile.TemporaryDirectory(prefix="kb7-nonfinite-json-") as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(self.bundle_dir, copied)
            descriptor_path = copied / "bundle.json"
            descriptor = json.loads(descriptor_path.read_text())
            descriptor["manifest_operations"] = float("nan")
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            with self.assertRaisesRegex(UPDATER.PlanError, "non-finite JSON"):
                UPDATER.load_descriptor(copied)

    def test_saved_simulation_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kb7-simulation-tamper-") as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(self.bundle_dir, copied)
            report_path = copied / "simulation.json"
            report = json.loads(report_path.read_text())
            report["early_checksum_valid_non_target_states"] = 999
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(UPDATER.PlanError, "simulation"):
                UPDATER.verify_bundle(
                    copied, self.baseline_a, self.baseline_b, anchors=self.anchors
                )

        # Even a self-consistently rehashed, still fail-closed-looking report
        # must equal the independently recomputed model result.
        with tempfile.TemporaryDirectory(prefix="kb7-simulation-rehash-") as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(self.bundle_dir, copied)
            report_path = copied / "simulation.json"
            report = json.loads(report_path.read_text())
            report["proof_boundary"] += " tampered"
            report_raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
            report_path.write_bytes(report_raw)
            descriptor_path = copied / "bundle.json"
            descriptor = json.loads(descriptor_path.read_text())
            descriptor["reports"]["simulation.json"] = {
                "length": len(report_raw), "sha256": UPDATER.sha256(report_raw)
            }
            descriptor["bundle_id"] = UPDATER.canonical_sha256(
                UPDATER.descriptor_without_id(descriptor)
            )
            descriptor_path.write_text(
                json.dumps(descriptor, indent=2, sort_keys=True) + "\n"
            )
            with self.assertRaisesRegex(UPDATER.PlanError, "independent recomputation"):
                UPDATER.verify_bundle(
                    copied, self.baseline_a, self.baseline_b, anchors=self.anchors
                )

    def test_build_pair_helpers_in_host_c(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-build-pair-c-") as temporary:
            executable = Path(temporary) / "build-pair-test"
            subprocess.run([
                compiler, "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-DKB7_HOST_TEST", "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/build_pair_host.c"),
                "-o", str(executable),
            ], check=True)
            subprocess.run([str(executable)], check=True)

    def test_firmware_pair_gate_precedes_usb_and_core1_initialization(self) -> None:
        core0 = (ROOT / "replacement_fw/core0/main.c").read_text()
        core1 = (ROOT / "replacement_fw/core1/startup.c").read_text()
        core0_startup = (ROOT / "replacement_fw/core0/startup.c").read_text()
        core0_linker = (ROOT / "replacement_fw/linker/core0.ld").read_text()
        core1_linker = (ROOT / "replacement_fw/linker/core1.ld").read_text()

        self.assertLess(core0.index("kb7_build_pair_marker_valid"),
                        core0.index("kb7_usb_init()"))
        self.assertLess(core0.index("api->build_pair_id"),
                        core0.index("api->magic = KB7_RUNTIME_MAGIC"))
        self.assertLess(core1.index("kb7_build_pair_marker_valid"),
                        core1.index("uint32_t *source"))
        self.assertLess(core1.index("api->build_pair_id"),
                        core1.index("kb7_application_main()"))
        self.assertIn("KB7_BUILD_PAIR_ROLE_CORE0", core0_startup)
        self.assertIn("KB7_BUILD_PAIR_ROLE_CORE1", core1)
        self.assertIn("UINT8_C(0xff)", core0_startup)
        self.assertIn("UINT8_C(0xff)", core1)
        self.assertIn("ORIGIN(IMAGE) + 0x140", core0_linker)
        self.assertIn("ORIGIN(IMAGE) + 0x100", core1_linker)
        self.assertIn("SIZEOF(.kb7_pair) == 32", core0_linker)
        self.assertIn("SIZEOF(.kb7_pair) == 32", core1_linker)


if __name__ == "__main__":
    unittest.main()
