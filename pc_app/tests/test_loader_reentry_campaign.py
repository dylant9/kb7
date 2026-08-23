from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_PATH = (
    ROOT / "tools" / "flash-access" / "kb7-loader-reentry-campaign.py")
PLAN_TEST_PATH = ROOT / "pc_app" / "tests" / "test_updater_plan.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


CAMPAIGN = load_module("kb7_loader_reentry_campaign_tested", CAMPAIGN_PATH)
PLAN_TEST = load_module("kb7_updater_plan_fixture_for_campaign", PLAN_TEST_PATH)
PLANNER = CAMPAIGN._planner


class LoaderReentryCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(
            prefix="kb7-loader-reentry-campaign-tests-")
        cls.root = Path(cls._temporary.name)
        cls.baseline, cls.anchors = PLAN_TEST.synthetic_baseline()
        cls.baseline_a = cls.root / "baseline-a.bin"
        cls.baseline_b = cls.root / "baseline-b.bin"
        cls.baseline_a.write_bytes(cls.baseline)
        cls.baseline_b.write_bytes(cls.baseline)
        cls.proof_elf = cls.root / "proof-core0.elf"
        cls.proof_elf.write_bytes(b"synthetic fixed loader reentry proof ELF")
        cls.raw = PLAN_TEST.replacement_raw(PLANNER.CORE0)
        cls.proof_identity = {
            "entry": "0x00000301",
            "raw_length": len(cls.raw),
            "raw_sha256": PLANNER.sha256(cls.raw),
        }

        def extractor(_elf: Path, _spec: object, _prefix: str,
                      destination: Path):
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

    def test_proof_symbol_gate_tracks_the_current_stackless_entry_name(self) -> None:
        symbols = "\n".join((
            "0000030c T kb7_loader_trampoline_relocate_and_enter",
            "00000360 T kb7_loader_trampoline_blob_start",
            "00000360 T kb7_loader_trampoline_start",
        ))
        with mock.patch.object(CAMPAIGN.shutil, "which",
                               return_value="arm-none-eabi-nm"), \
                mock.patch.object(CAMPAIGN._planner, "run",
                                  return_value=symbols):
            CAMPAIGN._verify_proof_symbols(self.proof_elf, "arm-none-eabi-")

        with mock.patch.object(CAMPAIGN.shutil, "which",
                               return_value="arm-none-eabi-nm"), \
                mock.patch.object(CAMPAIGN._planner, "run",
                                  return_value=symbols.replace(
                                      "kb7_loader_trampoline_start", "missing")):
            with self.assertRaisesRegex(
                    CAMPAIGN.PlanError, "kb7_loader_trampoline_start"):
                CAMPAIGN._verify_proof_symbols(
                    self.proof_elf, "arm-none-eabi-")

    def test_campaign_targets_proof_core0_and_round_trips_exact_baseline(self) -> None:
        self.assertEqual(self.campaign.baseline, self.baseline)
        self.assertEqual(
            self.campaign.proof_image[PLANNER.CORE1_START:],
            self.baseline[PLANNER.CORE1_START:])
        self.assertNotEqual(
            self.campaign.proof_image[
                PLANNER.CORE0_START:PLANNER.CORE0_ENVELOPE_END],
            self.baseline[PLANNER.CORE0_START:PLANNER.CORE0_ENVELOPE_END])

        image = bytearray(self.baseline)
        barrier = int(
            self.descriptor["install_core1_barrier"]["absolute_sector_offset"], 0)
        for operation in self.campaign.operations:
            in_core0 = (PLANNER.CORE0_START <= operation.offset and
                        operation.offset + operation.length <=
                        PLANNER.CORE0_ENVELOPE_END)
            in_barrier = (barrier <= operation.offset and
                          operation.offset + operation.length <=
                          barrier + PLANNER.SECTOR_BYTES)
            self.assertTrue(in_core0 or in_barrier)
            PLANNER.apply_operation(image, operation)
        self.assertEqual(bytes(image), self.baseline)
        self.assertEqual(self.descriptor["proof_full_sha256"],
                         PLANNER.sha256(self.campaign.proof_image))

    def test_install_and_restore_have_poison_gate_and_no_early_valid_image(self) -> None:
        install_count = self.campaign.install_operation_count
        phases = [operation.phase for operation in self.campaign.operations]
        self.assertEqual(phases[0], "install_poison_core0")
        self.assertEqual(phases[install_count - 1], "install_commit_core0")
        self.assertEqual(phases[install_count], "restore_poison_core0")
        self.assertEqual(phases[-1], "restore_commit_core0")

        image = bytearray(self.baseline)
        for index, operation in enumerate(self.campaign.operations):
            PLANNER.apply_operation(image, operation)
            valid = (PLANNER.core_checksums(image)[0] ==
                     PLANNER.CORE0.manifest_checksum)
            self.assertEqual(
                valid, index in (install_count - 1,
                                 len(self.campaign.operations) - 1))
        simulation = json.loads(
            (self.campaign_dir / CAMPAIGN.SIMULATION_NAME).read_text())
        self.assertEqual(simulation["early_loader_valid_non_target_states"], 0)
        self.assertGreater(simulation["core1_operation_count"], 0)
        self.assertEqual(simulation["preserved_boot_region_operation_count"], 0)

    def test_operation_descriptors_bind_exact_internal_cdbs_and_payloads(self) -> None:
        traces = self.descriptor["operations"]
        self.assertEqual(len(traces), len(self.campaign.operations))
        for index, (trace, operation) in enumerate(
                zip(traces, self.campaign.operations)):
            self.assertEqual(trace["index"], index)
            self.assertEqual(trace["offset"], f"0x{operation.offset:08x}")
            if operation.action == "program":
                self.assertEqual(trace["cdb_hex"],
                                 PLANNER.cdb_program(operation.offset).hex())
                self.assertEqual(trace["payload_sha256"],
                                 PLANNER.sha256(operation.payload))
            else:
                self.assertEqual(trace["cdb_hex"],
                                 PLANNER.cdb_erase(operation.offset).hex())
                self.assertIsNone(trace["payload_sha256"])
        self.assertTrue(
            self.descriptor["policy"]["one_operation_per_cli_invocation"])
        self.assertTrue(
            self.descriptor["policy"]["durable_intent_before_usb_open"])
        self.assertFalse(self.descriptor["execution_authorized"])
        self.assertFalse(self.descriptor["flash_approved"])
        self.assertFalse(self.descriptor["campaign_self_authorizes_execution"])
        self.assertTrue(self.descriptor["requires_separate_executor_authorization"])

    def test_symbolic_prefix_proofs_cover_poison_barriers_and_bijective_commits(self) -> None:
        simulation = json.loads(
            (self.campaign_dir / CAMPAIGN.SIMULATION_NAME).read_text())
        poisons = [operation for operation in self.campaign.operations
                   if "poison_" in operation.phase]
        commits = [operation for operation in self.campaign.operations
                   if operation.phase.endswith("commit_core0")]
        self.assertEqual(len(poisons), 4)
        self.assertEqual(len(commits), 2)
        self.assertEqual(
            simulation["single_bit_poison_prefix_states_checked"],
            len(poisons) * (PLANNER.BLOCK_BYTES - 1))
        self.assertEqual(simulation["sparse_gate_subset_proofs"], 2)
        self.assertGreater(
            simulation["opposite_barrier_prefix_states_checked"], 0)

        image = bytearray(self.baseline)
        restore_gate = int(self.descriptor["restore_gate"]["offset"], 0)
        for operation in self.campaign.operations:
            pre = bytes(image)
            start = operation.offset
            end = start + operation.length
            PLANNER.apply_operation(image, operation)
            post = bytes(image)
            if "poison_" in operation.phase:
                before = pre[start:end]
                after = post[start:end]
                changed = [index for index, pair in enumerate(zip(before, after))
                           if pair[0] != pair[1]]
                self.assertEqual(len(changed), 1)
                for cut in range(operation.length + 1):
                    partial = PLANNER.prefix_outcome(
                        before, after, operation.action, cut)
                    self.assertIn(partial, (before, after))
            if operation.phase.endswith("commit_core0"):
                gate = (PLANNER.CORE0.gate_offset if
                        operation.phase.startswith("install_") else restore_gate)
                core0 = post[
                    PLANNER.CORE0_START:
                    PLANNER.CORE0_START + PLANNER.CORE0_LENGTH]
                chunk_start = (gate // 0x10000) * 0x10000
                chunk_end = min(chunk_start + 0x10000, len(core0))
                self.assertEqual(PLANNER.crc_word_rank(
                    core0[chunk_start:chunk_end], gate - chunk_start), 32)

    def test_restore_gate_is_full_rank_and_first_sector_is_staged_first(self) -> None:
        gate = int(self.descriptor["restore_gate"]["offset"], 0)
        self.assertLess(gate, PLANNER.SECTOR_BYTES)
        self.assertEqual(self.descriptor["restore_gate"]["rank"], 32)
        restore = self.campaign.operations[self.campaign.install_operation_count:]
        stage = [operation for operation in restore
                 if operation.phase == "restore_stage_core0"]
        self.assertTrue(stage)
        self.assertEqual(
            stage[0].offset & ~(PLANNER.SECTOR_BYTES - 1),
            PLANNER.CORE0_START)

    def test_campaign_tampering_and_wrong_proof_identity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kb7-campaign-tamper-") as temporary:
            copied = Path(temporary) / "campaign"
            shutil.copytree(self.campaign_dir, copied)
            payload = copied / CAMPAIGN.PROOF_IMAGE_NAME
            data = bytearray(payload.read_bytes())
            data[17] ^= 1
            payload.write_bytes(data)
            with self.assertRaisesRegex(PLANNER.PlanError, "payload"):
                CAMPAIGN.load_campaign(
                    copied, self.baseline_a, self.baseline_b, self.proof_elf,
                    "unused-", anchors=self.anchors,
                    proof_identity=self.proof_identity,
                    extractor=self.extractor)

        wrong = dict(self.proof_identity)
        wrong["raw_sha256"] = "0" * 64
        with self.assertRaisesRegex(PLANNER.PlanError, "raw identity"):
            CAMPAIGN.load_campaign(
                self.campaign_dir, self.baseline_a, self.baseline_b,
                self.proof_elf, "unused-", anchors=self.anchors,
                proof_identity=wrong, extractor=self.extractor)

    def test_cli_is_offline_only_and_has_no_commit_or_device_surface(self) -> None:
        source = CAMPAIGN_PATH.read_text(encoding="utf-8").lower()
        for forbidden in (
                "import usb", "from usb", "pyusb", "libusb", "hidraw",
                "--commit", "--device", "bulk_transfer", "ctrl_transfer"):
            self.assertNotIn(forbidden, source)
        result = subprocess.run(
            [sys.executable, str(CAMPAIGN_PATH), "--help"],
            text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{build,verify}", result.stdout)
        self.assertNotIn("--commit", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
