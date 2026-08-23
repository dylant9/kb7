from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tools" / "flash-access" / "kb7-updater-executor.py"
HELPERS_PATH = ROOT / "pc_app" / "tests" / "test_updater_plan.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


EXECUTOR = load_module("kb7_updater_executor_tested", EXECUTOR_PATH)
HELPERS = load_module("kb7_updater_executor_fixture_helpers", HELPERS_PATH)
PLANNER = EXECUTOR._planner


class InjectedFault(RuntimeError):
    pass


class FakeBackend:
    def __init__(self, image: bytes, *, device_path: str = "3-2.2",
                 capture_sequence: list[bytes] | None = None) -> None:
        self.image = bytearray(image)
        self.device_path = device_path
        self.capture_sequence = list(capture_sequence or [])
        self.capture_count = 0
        self.mode_calls: list[object] = []
        self.mutation_calls: list[object] = []
        self.poll_count = 0
        self.closed = False

    def identity(self) -> dict[str, str]:
        return {
            "device_path": self.device_path,
            "identify_hex": EXECUTOR._writer.LOADER_IDENT.hex(),
            "descriptor_sha256": "11" * 32,
            "loader_fingerprint_sha256": "22" * 32,
        }

    def capture(self, *, progress: bool = False) -> bytes:
        del progress
        self.capture_count += 1
        if self.capture_sequence:
            return self.capture_sequence.pop(0)
        return bytes(self.image)

    def set_mode(self, operation: object) -> None:
        self.mode_calls.append(operation)

    def mutate(self, operation: object) -> None:
        self.mutation_calls.append(operation)
        PLANNER.apply_operation(self.image, operation)

    def poll(self) -> None:
        self.poll_count += 1

    def close(self) -> None:
        self.closed = True


class UpdaterExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="kb7-executor-tests-")
        cls.root = Path(cls._temporary.name)
        cls.baseline, cls.anchors = HELPERS.synthetic_baseline()
        cls.baseline_a = cls.root / "baseline-a.bin"
        cls.baseline_b = cls.root / "baseline-b.bin"
        cls.baseline_a.write_bytes(cls.baseline)
        cls.baseline_b.write_bytes(cls.baseline)
        cls.core0_elf = cls.root / "core0.elf"
        cls.core1_elf = cls.root / "core1.elf"
        cls.core0_elf.write_bytes(b"synthetic executor elf zero")
        cls.core1_elf.write_bytes(b"synthetic executor elf one")
        raw = {
            "core0": HELPERS.replacement_raw(HELPERS.UPDATER.CORE0),
            "core1": HELPERS.replacement_raw(HELPERS.UPDATER.CORE1),
        }

        def fake_extract(elf: Path, spec: object, _prefix: str,
                         destination: Path) -> tuple[bytes, dict[str, object]]:
            payload = raw[spec.name]
            destination.write_bytes(payload)
            entry = 0x301 if spec.name == "core0" else HELPERS.UPDATER.CORE1_VMA + 1
            return payload, {
                "entry": f"0x{entry:08x}",
                "raw_length": len(payload),
                "elf_sha256": HELPERS.UPDATER.sha256(elf.read_bytes()),
                "raw_sha256": HELPERS.UPDATER.sha256(payload),
            }

        cls.bundle = cls.root / "bundle"
        HELPERS.UPDATER.build_bundle(
            cls.baseline_a, cls.baseline_b, cls.core0_elf, cls.core1_elf,
            cls.bundle, "unused-", anchors=cls.anchors, extractor=fake_extract,
        )
        cls.transaction = EXECUTOR.load_transaction(
            cls.bundle, cls.baseline_a, cls.baseline_b, anchors=cls.anchors)
        cls.stage_index = next(
            index for index, operation in enumerate(cls.transaction.operations)
            if operation.phase.startswith("stage_") and operation.action == "program"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    @classmethod
    def bound_identity(cls, image: bytes, *, device_path: str = "3-2.2"
                       ) -> dict[str, str]:
        backend = FakeBackend(image, device_path=device_path)
        return EXECUTOR._identity_fields(backend.identity(), image)

    def test_cli_is_read_only_and_live_mutation_is_hard_locked(self) -> None:
        result = subprocess.run(
            [sys.executable, str(EXECUTOR_PATH), "--help"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{preflight,reconcile}", result.stdout)
        for forbidden in ("--commit", "--force", "--offset", "--cdb"):
            self.assertNotIn(forbidden, result.stdout.lower())
        source = EXECUTOR_PATH.read_text(encoding="utf-8")
        for live_call in (
                "_writer.set_address_mode_for_range", "self.device.program(",
                "_planner.cdb_erase(", "_writer.poll_ready"):
            self.assertNotIn(live_call, source)
        self.assertFalse(EXECUTOR.LIVE_MUTATION_ENABLED)
        locked = object.__new__(EXECUTOR.LockedUsbMutationBackend)
        for method, argument in (
                (locked.set_mode, self.transaction.operations[0]),
                (locked.mutate, self.transaction.operations[0]),
                (locked.poll, None)):
            with self.assertRaisesRegex(EXECUTOR.ExecutionLocked, "disabled"):
                if argument is None:
                    method()
                else:
                    method(argument)
        # Even monkey-patching the informational status constant cannot expose
        # transport code; enabling execution requires an actual reviewed edit.
        with mock.patch.object(EXECUTOR, "LIVE_MUTATION_ENABLED", True):
            with self.assertRaises(EXECUTOR.ExecutionLocked):
                locked.mutate(self.transaction.operations[0])

    def test_transaction_reconstruction_and_exact_boundary_classification(self) -> None:
        transaction = self.transaction
        self.assertEqual(len(transaction.operations),
                         len(transaction.descriptor["operations"]))
        self.assertEqual(
            PLANNER.sha256(transaction.target_image), transaction.target_full_sha256)
        stock = EXECUTOR.classify_observed_image(transaction, transaction.baseline)
        target = EXECUTOR.classify_observed_image(transaction, transaction.target_image)
        self.assertEqual((stock["classification"], stock["boundary_index"]),
                         ("exact_stock", 0))
        self.assertEqual(
            (target["classification"], target["boundary_index"]),
            ("exact_target", len(transaction.operations)),
        )
        first = bytearray(transaction.baseline)
        PLANNER.apply_operation(first, transaction.operations[0])
        middle = EXECUTOR.classify_observed_image(transaction, bytes(first))
        self.assertEqual(middle["classification"], "exact_intermediate_boundary")
        self.assertEqual(middle["boundary_index"], 1)
        self.assertFalse(middle["automatic_mutation_authorized"])

        unknown = bytearray(transaction.baseline)
        unknown[PLANNER.CORE0_START + 0x300] ^= 1
        self.assertEqual(
            EXECUTOR.classify_observed_image(transaction, bytes(unknown))["classification"],
            "spi_recovery_required",
        )
        immutable = bytearray(transaction.baseline)
        immutable[PLANNER.LOADER_START] ^= 1
        with self.assertRaisesRegex(EXECUTOR.ExecutorError, "immutable"):
            EXECUTOR.classify_observed_image(transaction, bytes(immutable))

        bundle_link = self.root / "bundle-link"
        baseline_link = self.root / "baseline-link.bin"
        try:
            bundle_link.symlink_to(self.bundle, target_is_directory=True)
            baseline_link.symlink_to(self.baseline_a)
            with self.assertRaisesRegex(PLANNER.PlanError, "regular directory"):
                EXECUTOR.load_transaction(
                    bundle_link, self.baseline_a, self.baseline_b,
                    anchors=self.anchors)
            with self.assertRaisesRegex(PLANNER.PlanError, "non-symlink"):
                EXECUTOR.load_transaction(
                    self.bundle, baseline_link, self.baseline_b,
                    anchors=self.anchors)
        finally:
            bundle_link.unlink(missing_ok=True)
            baseline_link.unlink(missing_ok=True)

    def test_live_preflight_requires_two_exact_reads_and_writes_bound_journal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kb7-preflight-") as temporary:
            journal_path = Path(temporary) / "journal.json"
            backend = FakeBackend(self.baseline)
            result = EXECUTOR.live_preflight(
                self.transaction, journal_path, backend_factory=lambda: backend,
                progress=False,
            )
            self.assertEqual(result["classification"], "exact_stock")
            self.assertFalse(result["live_mutation_enabled"])
            self.assertEqual(backend.capture_count, 2)
            self.assertTrue(backend.closed)
            journal = EXECUTOR.load_journal(journal_path)
            EXECUTOR.validate_journal(
                self.transaction, journal, self.bound_identity(self.baseline))
            self.assertEqual(journal["status"], "preflight_verified")
            self.assertEqual(journal["boundary_index"], 0)
            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "replace"):
                EXECUTOR.live_preflight(
                    self.transaction, journal_path,
                    backend_factory=lambda: FakeBackend(self.baseline), progress=False)

            changed = bytearray(self.baseline)
            changed[PLANNER.CORE0_START + 0x222] ^= 1
            mismatch_path = Path(temporary) / "mismatch.json"
            mismatched = FakeBackend(
                self.baseline, capture_sequence=[self.baseline, bytes(changed)])
            with self.assertRaisesRegex(RuntimeError, "differ"):
                EXECUTOR.live_preflight(
                    self.transaction, mismatch_path,
                    backend_factory=lambda: mismatched, progress=False)
            self.assertFalse(mismatch_path.exists())
            self.assertTrue(mismatched.closed)

    def test_reconcile_repairs_only_exact_image_derived_boundaries(self) -> None:
        first = bytearray(self.baseline)
        PLANNER.apply_operation(first, self.transaction.operations[0])
        with tempfile.TemporaryDirectory(prefix="kb7-reconcile-") as temporary:
            journal_path = Path(temporary) / "journal.json"
            backend = FakeBackend(bytes(first))
            result = EXECUTOR.live_reconcile(
                self.transaction, journal_path, backend_factory=lambda: backend,
                progress=False,
            )
            self.assertEqual(result["classification"], "exact_intermediate_boundary")
            self.assertEqual(result["boundary_index"], 1)
            self.assertTrue(result["journal_rebuilt"])
            self.assertIn("does not exist", result["journal_error_before_reconciliation"])
            self.assertEqual(EXECUTOR.load_journal(journal_path)["boundary_index"], 1)

            stale = EXECUTOR.boundary_journal(
                self.transaction, self.bound_identity(self.baseline), 0)
            EXECUTOR.write_journal_atomic(journal_path, stale)
            result = EXECUTOR.live_reconcile(
                self.transaction, journal_path,
                backend_factory=lambda: FakeBackend(bytes(first)), progress=False)
            self.assertFalse(result["journal_rebuilt"])
            self.assertEqual(EXECUTOR.load_journal(journal_path)["boundary_index"], 1)

            journal_path.write_text('{"schema":NaN}', encoding="utf-8")
            result = EXECUTOR.live_reconcile(
                self.transaction, journal_path,
                backend_factory=lambda: FakeBackend(bytes(first)), progress=False)
            self.assertTrue(result["journal_rebuilt"])
            self.assertIn("non-finite", result["journal_error_before_reconciliation"])

    def test_reconcile_refuses_stale_source_and_device_bindings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kb7-binding-") as temporary:
            journal_path = Path(temporary) / "journal.json"
            journal = EXECUTOR.boundary_journal(
                self.transaction, self.bound_identity(self.baseline), 0)
            journal["executor_source_sha256"] = "00" * 32
            EXECUTOR.write_journal_atomic(journal_path, journal)
            opened = False

            def factory():
                nonlocal opened
                opened = True
                return FakeBackend(self.baseline)

            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "executor_source"):
                EXECUTOR.live_reconcile(
                    self.transaction, journal_path, backend_factory=factory,
                    progress=False)
            self.assertFalse(opened)

            good = EXECUTOR.boundary_journal(
                self.transaction, self.bound_identity(self.baseline), 0)
            EXECUTOR.write_journal_atomic(journal_path, good)
            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "device_path"):
                EXECUTOR.live_reconcile(
                    self.transaction, journal_path,
                    backend_factory=lambda: FakeBackend(
                        self.baseline, device_path="3-3.1"), progress=False)

    def test_intent_classifies_only_reachable_active_unit_partial_state(self) -> None:
        index = self.stage_index
        operation = self.transaction.operations[index]
        preimage = EXECUTOR.expected_boundary_image(self.transaction, index)
        postimage = bytearray(preimage)
        PLANNER.apply_operation(postimage, operation)
        identity = self.bound_identity(preimage)
        journal = EXECUTOR.intent_journal(self.transaction, identity, index)
        transitions = [
            operation.offset + local for local in range(operation.length)
            if preimage[operation.offset + local] != postimage[operation.offset + local]
        ]
        self.assertGreater(len(transitions), 1)
        partial = bytearray(preimage)
        for offset in transitions[:max(1, len(transitions) // 2)]:
            partial[offset] = postimage[offset]
        result = EXECUTOR.classify_observed_image(
            self.transaction, bytes(partial), journal)
        self.assertEqual(
            result["classification"], "modeled_partial_rebuild_active_sector")
        self.assertFalse(result["automatic_mutation_authorized"])

        outside = bytearray(partial)
        candidate = (PLANNER.CORE1_START if operation.offset < PLANNER.CORE1_START
                     else PLANNER.CORE0_START)
        outside[candidate + 0x280] ^= 1
        self.assertEqual(
            EXECUTOR.classify_observed_image(
                self.transaction, bytes(outside), journal)["classification"],
            "spi_recovery_required",
        )

    def test_journal_is_strict_non_aliasing_and_directory_fsynced(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kb7-journal-") as temporary:
            root = Path(temporary)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema":"a","schema":"b"}', encoding="utf-8")
            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "duplicate"):
                EXECUTOR.load_journal(duplicate)
            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"schema":Infinity}', encoding="utf-8")
            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "non-finite"):
                EXECUTOR.load_journal(nonfinite)

            journal_path = root / "journal.json"
            journal = EXECUTOR.boundary_journal(
                self.transaction, self.bound_identity(self.baseline), 0)
            with mock.patch.object(os, "fsync", wraps=os.fsync) as fsync:
                EXECUTOR.write_journal_atomic(journal_path, journal)
            self.assertGreaterEqual(fsync.call_count, 2)
            self.assertEqual(journal_path.stat().st_mode & 0o777, 0o600)
            journal_link = root / "journal-link.json"
            journal_link.symlink_to(journal_path)
            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "safely open"):
                EXECUTOR.load_journal(journal_link)

            real_parent = root / "real"
            real_parent.mkdir()
            linked_parent = root / "linked"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "regular directory"):
                EXECUTOR.write_journal_atomic(linked_parent / "state.json", journal)
            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "regular directory"):
                EXECUTOR.validate_journal_path(
                    self.transaction, linked_parent / "state.json")

            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "baseline"):
                EXECUTOR.validate_journal_path(self.transaction, self.baseline_a)
            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "bundle"):
                EXECUTOR.validate_journal_path(
                    self.transaction, self.bundle / "updater-journal.json")

    def test_modeled_operation_writes_intent_then_verified_boundary(self) -> None:
        index = self.stage_index
        preimage = EXECUTOR.expected_boundary_image(self.transaction, index)
        identity = self.bound_identity(preimage)
        backend = FakeBackend(preimage)
        with tempfile.TemporaryDirectory(prefix="kb7-modeled-success-") as temporary:
            journal_path = Path(temporary) / "journal.json"
            EXECUTOR.write_journal_atomic(
                journal_path,
                EXECUTOR.boundary_journal(self.transaction, identity, index),
            )
            postimage = EXECUTOR.run_one_modeled_operation(
                self.transaction, index, backend, journal_path)
            self.assertEqual(bytes(backend.image), postimage)
            self.assertEqual(backend.capture_count, 4)
            self.assertEqual(len(backend.mode_calls), 1)
            self.assertEqual(len(backend.mutation_calls), 1)
            self.assertEqual(backend.poll_count, 1)
            journal = EXECUTOR.load_journal(journal_path)
            EXECUTOR.validate_journal(self.transaction, journal, identity)
            self.assertEqual(journal["boundary_index"], index + 1)
            self.assertEqual(journal["status"], "boundary_verified")

    def test_every_fault_site_stops_and_requires_image_reconciliation(self) -> None:
        index = self.stage_index
        operation = self.transaction.operations[index]
        preimage = EXECUTOR.expected_boundary_image(self.transaction, index)
        postimage = bytearray(preimage)
        PLANNER.apply_operation(postimage, operation)
        identity = self.bound_identity(preimage)
        with tempfile.TemporaryDirectory(prefix="kb7-fault-sites-") as temporary:
            root = Path(temporary)
            for site in EXECUTOR.FAULT_SITES:
                with self.subTest(site=site):
                    journal_path = root / f"{site}.json"
                    EXECUTOR.write_journal_atomic(
                        journal_path,
                        EXECUTOR.boundary_journal(
                            self.transaction, identity, index),
                    )
                    backend = FakeBackend(preimage)

                    def inject(observed_site: str) -> None:
                        if observed_site != site:
                            return
                        if site == "during_data_or_erase":
                            changed = [
                                local for local in range(operation.length)
                                if preimage[operation.offset + local] !=
                                postimage[operation.offset + local]
                            ]
                            for local in changed[:max(1, len(changed) // 2)]:
                                backend.image[operation.offset + local] = \
                                    postimage[operation.offset + local]
                        if site == "after_intent":
                            raise KeyboardInterrupt("injected Ctrl-C")
                        raise InjectedFault(site)

                    expected_error = (InjectedFault if site in
                                      {"before_intent", "during_intent"}
                                      else EXECUTOR.ReconciliationRequired)
                    with self.assertRaises(expected_error):
                        EXECUTOR.run_one_modeled_operation(
                            self.transaction, index, backend, journal_path,
                            fault=inject)
                    self.assertLessEqual(len(backend.mutation_calls), 1)
                    journal = EXECUTOR.load_journal(journal_path)
                    EXECUTOR.validate_journal(self.transaction, journal, identity)
                    result = EXECUTOR.classify_observed_image(
                        self.transaction, bytes(backend.image), journal)
                    self.assertFalse(result["automatic_mutation_authorized"])
                    if site == "during_data_or_erase":
                        self.assertEqual(
                            result["classification"],
                            "modeled_partial_rebuild_active_sector",
                        )
                    if site == "after_verified_journal":
                        self.assertEqual(journal["boundary_index"], index + 1)


if __name__ == "__main__":
    unittest.main()
