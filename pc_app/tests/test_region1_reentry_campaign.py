from __future__ import annotations

import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_PATH = (
    ROOT / "tools" / "flash-access" / "kb7-region1-reentry-campaign.py")
PLAN_TEST_PATH = ROOT / "pc_app" / "tests" / "test_updater_plan.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


CAMPAIGN = load_module("kb7_region1_reentry_campaign_tested", CAMPAIGN_PATH)
PLAN_TEST = load_module("kb7_updater_plan_fixture_for_region1_campaign", PLAN_TEST_PATH)
PLANNER = CAMPAIGN._planner
SPEC = PLANNER.CORE1


def synthetic_raw(length: int = 404) -> bytes:
    """A deterministic proof-shaped payload: CPSID first, no 0xff words."""

    data = bytearray()
    seed = 0x9E3779B1
    while len(data) < length:
        seed = (seed * 1103515245 + 12345) & 0xFFFFFFFF
        data += struct.pack("<I", seed & 0x7F7F7F7F)
    data[:2] = b"\x72\xb6"  # cpsid i
    return bytes(data[:length])


def region1_with_populated_patch_sector() -> tuple[bytes, dict[str, str]]:
    """The planner fixture, with stock-like bytes in the patch sector.

    The synthetic stock region is mostly erased; the restore direction needs a
    non-erased full-rank word in the patch sector, and the install direction
    needs the sector to require an erase.  Fill the sector deterministically,
    then re-solve the fixture's own fixup word so the region keeps the
    manifest checksum.
    """

    image, anchors = PLAN_TEST.synthetic_baseline()
    image = bytearray(image)
    region = bytearray(image[SPEC.start:SPEC.start + SPEC.length])
    filler = bytearray()
    seed = 0x12345678
    while len(filler) < 0x1000:
        seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
        filler += struct.pack("<I", seed | 0x01010101)
    region[CAMPAIGN.PATCH_SECTOR:CAMPAIGN.PATCH_SECTOR_END] = filler[:0x1000]
    chunk_start = ((SPEC.length - 1) // 0x10000) * 0x10000
    fixture_fixup = chunk_start + 0x80
    region[fixture_fixup:fixture_fixup + 4] = b"\0" * 4
    other_sum = sum(
        zlib.crc32(region[offset:min(offset + 0x10000, SPEC.length)]) & 0xFFFFFFFF
        for offset in range(0, SPEC.length, 0x10000) if offset != chunk_start
    ) & 0xFFFFFFFF
    wanted = (SPEC.manifest_checksum - other_sum) & 0xFFFFFFFF
    patch, rank = PLANNER.crc_patch(
        bytes(region[chunk_start:SPEC.length]), fixture_fixup - chunk_start, wanted)
    assert rank == 32
    region[fixture_fixup:fixture_fixup + 4] = patch
    assert PLANNER.fwin_checksum(bytes(region)) == SPEC.manifest_checksum
    image[SPEC.start:SPEC.start + SPEC.length] = region
    anchors = dict(anchors)
    anchors["core1"] = PLANNER.sha256(bytes(region))
    return bytes(image), anchors


class Region1ReentryCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(
            prefix="kb7-region1-reentry-campaign-tests-")
        cls.root = Path(cls._temporary.name)
        cls.baseline, cls.anchors = region1_with_populated_patch_sector()
        cls.baseline_a = cls.root / "baseline-a.bin"
        cls.baseline_b = cls.root / "baseline-b.bin"
        cls.baseline_a.write_bytes(cls.baseline)
        cls.baseline_b.write_bytes(cls.baseline)
        cls.proof_elf = cls.root / "proof-core1.elf"
        cls.proof_elf.write_bytes(b"synthetic fixed region-1 reentry proof ELF")
        cls.raw = synthetic_raw()
        cls.proof_identity = {
            "entry": "0x1004a525",
            "raw_length": len(cls.raw),
            "raw_sha256": PLANNER.sha256(cls.raw),
        }

        def extractor(_elf: Path, _prefix: str, destination: Path):
            destination.write_bytes(cls.raw)
            return cls.raw, {
                **cls.proof_identity,
                "elf_sha256": PLANNER.sha256(cls.proof_elf.read_bytes()),
            }

        cls.extractor = staticmethod(extractor)
        cls.campaign_dir = cls.root / "campaign"
        cls.descriptor = CAMPAIGN.build_campaign(
            cls.baseline_a, cls.baseline_b, cls.proof_elf,
            cls.campaign_dir, "unused-", anchors=cls.anchors,
            proof_identity=cls.proof_identity, extractor=cls.extractor)
        cls.campaign = CAMPAIGN.load_campaign(
            cls.campaign_dir, cls.baseline_a, cls.baseline_b,
            cls.proof_elf, "unused-", anchors=cls.anchors,
            proof_identity=cls.proof_identity, extractor=cls.extractor)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_campaign_patches_only_the_entry_sector_and_round_trips(self) -> None:
        proof = self.campaign.proof_image
        baseline = self.campaign.baseline
        start = SPEC.start + CAMPAIGN.PATCH_SECTOR
        end = SPEC.start + CAMPAIGN.PATCH_SECTOR_END
        self.assertEqual(proof[:start], baseline[:start])
        self.assertEqual(proof[end:], baseline[end:])
        self.assertNotEqual(proof[start:end], baseline[start:end])
        entry = SPEC.start + CAMPAIGN.PATCH_OFFSET
        self.assertEqual(proof[entry:entry + len(self.raw)], self.raw)
        self.assertEqual(PLANNER.core_checksums(proof),
                         (PLANNER.CORE0.manifest_checksum, SPEC.manifest_checksum))
        current = bytearray(baseline)
        for operation in self.campaign.operations[:self.campaign.install_operation_count]:
            PLANNER.apply_operation(current, operation)
        self.assertEqual(bytes(current), proof)
        for operation in self.campaign.operations[self.campaign.install_operation_count:]:
            PLANNER.apply_operation(current, operation)
        self.assertEqual(bytes(current), baseline)

    def test_every_operation_lies_in_the_two_declared_sectors(self) -> None:
        ranges = [(int(entry["start"], 0), int(entry["end_exclusive"], 0))
                  for entry in self.descriptor["mutable_ranges"]]
        self.assertEqual(len(ranges), 2)
        self.assertEqual(ranges[0], (SPEC.start + CAMPAIGN.PATCH_SECTOR,
                                     SPEC.start + CAMPAIGN.PATCH_SECTOR_END))
        for operation in self.campaign.operations:
            self.assertTrue(any(start <= operation.offset and
                                operation.offset + operation.length <= end
                                for start, end in ranges), operation)
            self.assertGreaterEqual(operation.offset, PLANNER.CORE1_START)

    def test_phase_structure_has_poison_stage_barrier_and_gate_per_direction(self) -> None:
        phases = [operation.phase for operation in self.campaign.operations]
        install = phases[:self.campaign.install_operation_count]
        restore = phases[self.campaign.install_operation_count:]
        for direction, sequence in (("install", install), ("restore", restore)):
            self.assertEqual(sequence[0], f"{direction}_poison_core1")
            self.assertEqual(sequence[-1], f"{direction}_commit")
            self.assertIn(f"{direction}_stage_core1_patch", sequence)
            self.assertIn(f"{direction}_stage_core1_barrier", sequence)
            first_stage = sequence.index(f"{direction}_stage_core1_patch")
            first_barrier = sequence.index(f"{direction}_stage_core1_barrier")
            self.assertLess(first_stage, first_barrier)
            self.assertEqual(sequence.count(f"{direction}_commit"), 1)
        self.assertEqual(self.descriptor["install_operation_count"], len(install))
        self.assertLessEqual(len(phases), 48)

    def test_no_boundary_or_prefix_state_is_loader_valid_early(self) -> None:
        simulation = json.loads(
            (self.campaign_dir / CAMPAIGN.SIMULATION_NAME).read_text())
        self.assertEqual(simulation["early_loader_valid_non_target_states"], 0)
        self.assertEqual(simulation["region0_operation_count"], 0)
        self.assertEqual(simulation["preserved_boot_region_operation_count"], 0)
        self.assertEqual(simulation["sparse_gate_subset_proofs"], 2)
        self.assertGreater(simulation["distinct_prefix_states_evaluated"],
                           simulation["operation_count"] * 2)
        current = bytearray(self.campaign.baseline)
        for index, operation in enumerate(self.campaign.operations):
            PLANNER.apply_operation(current, operation)
            valid = PLANNER.core_checksums(bytes(current))[1] == SPEC.manifest_checksum
            at_target = index + 1 in (self.campaign.install_operation_count,
                                      len(self.campaign.operations))
            self.assertEqual(valid, at_target, index)
            self.assertEqual(PLANNER.core_checksums(bytes(current))[0],
                             PLANNER.CORE0.manifest_checksum)

    def test_operation_descriptors_bind_exact_cdbs_and_payloads(self) -> None:
        for trace, operation in zip(self.descriptor["operations"],
                                    self.campaign.operations):
            self.assertEqual(int(trace["offset"], 0), operation.offset)
            if operation.action == "program":
                self.assertEqual(trace["cdb_hex"],
                                 PLANNER.cdb_program(operation.offset).hex())
                self.assertEqual(trace["payload_sha256"],
                                 PLANNER.sha256(operation.payload))
            else:
                self.assertEqual(trace["cdb_hex"],
                                 PLANNER.cdb_erase(operation.offset).hex())
                self.assertIsNone(trace["payload_sha256"])

    def test_fixup_and_gate_are_full_rank_and_inside_the_patch_sector(self) -> None:
        metadata = self.descriptor["proof_core1"]
        fixup = int(metadata["fixup_offset"], 0)
        gate = int(metadata["gate_offset"], 0)
        self.assertEqual(fixup, CAMPAIGN.PATCH_OFFSET + len(self.raw))
        self.assertEqual(gate, fixup + 4)
        self.assertLessEqual(gate + 4, CAMPAIGN.PATCH_WINDOW_END)
        self.assertEqual(metadata["fixup_rank"], 32)
        self.assertEqual(metadata["gate_rank"], 32)
        restore_gate = int(self.descriptor["restore_gate"]["offset"], 0)
        self.assertTrue(CAMPAIGN.PATCH_SECTOR <= restore_gate < CAMPAIGN.PATCH_SECTOR_END)

    def test_campaign_tampering_and_wrong_identity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            copy = Path(temporary) / "campaign"
            copy.mkdir()
            for path in self.campaign_dir.iterdir():
                copy.joinpath(path.name).write_bytes(path.read_bytes())
            sector = copy / CAMPAIGN.PATCH_SECTOR_NAME
            data = bytearray(sector.read_bytes())
            data[0x600] ^= 0x01
            sector.write_bytes(bytes(data))
            with self.assertRaises(PLANNER.PlanError):
                CAMPAIGN.load_campaign(
                    copy, self.baseline_a, self.baseline_b, self.proof_elf,
                    "unused-", anchors=self.anchors,
                    proof_identity=self.proof_identity, extractor=self.extractor)
        wrong = dict(self.proof_identity, raw_sha256="00" * 32)
        with self.assertRaises(PLANNER.PlanError):
            CAMPAIGN.load_campaign(
                self.campaign_dir, self.baseline_a, self.baseline_b,
                self.proof_elf, "unused-", anchors=self.anchors,
                proof_identity=wrong, extractor=self.extractor)

    def test_oversized_or_misaligned_proof_is_rejected(self) -> None:
        stock = self.baseline[SPEC.start:SPEC.start + SPEC.length]
        with self.assertRaises(PLANNER.PlanError):
            CAMPAIGN.build_patched_region(stock, synthetic_raw(0xADC))
        with self.assertRaises(PLANNER.PlanError):
            CAMPAIGN.build_patched_region(stock, synthetic_raw(402))
        # Fits the sector but not the stock main routine's 0x2d4-byte window.
        with self.assertRaises(PLANNER.PlanError):
            CAMPAIGN.build_patched_region(stock, synthetic_raw(0x2D0))
        target, _staged, metadata = CAMPAIGN.build_patched_region(
            stock, synthetic_raw(0x2CC))
        self.assertLessEqual(int(metadata["gate_offset"], 0) + 4,
                             CAMPAIGN.PATCH_WINDOW_END)
        self.assertEqual(target[CAMPAIGN.PATCH_WINDOW_END:],
                         stock[CAMPAIGN.PATCH_WINDOW_END:])

    def test_cli_is_offline_only_and_has_no_device_surface(self) -> None:
        source = CAMPAIGN_PATH.read_text(encoding="utf-8").lower()
        for forbidden in ("import usb", "from usb", "libusb", "--commit", "--device"):
            self.assertNotIn(forbidden, source)
        result = subprocess.run(
            [sys.executable, str(CAMPAIGN_PATH), "--help"],
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("offline", result.stdout.lower())
        self.assertFalse(self.descriptor["execution_authorized"])
        self.assertFalse(self.descriptor["flash_approved"])
        self.assertTrue(self.descriptor["requires_separate_executor_authorization"])


if __name__ == "__main__":
    unittest.main()
