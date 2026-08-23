"""Offline tests for the fixed scratch-only updater execution harness."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = (
    ROOT / "tools" / "flash-access" / "kb7-updater-scratch-executor.py")
FIXTURE_PATH = ROOT / "pc_app" / "tests" / "test_isp_scratch_restart.py"
FIRMWARE_EXECUTOR_PATH = (
    ROOT / "tools" / "flash-access" / "kb7-updater-executor.py")


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


SCRATCH = load_module("kb7_updater_scratch_executor_tested", TOOL_PATH)
FIXTURE = load_module("kb7_updater_scratch_fixture", FIXTURE_PATH)
FIRMWARE = load_module("kb7_firmware_executor_lock_fixture", FIRMWARE_EXECUTOR_PATH)


class FakeDevice:
    def __init__(self, *, fail_action: str | None = None) -> None:
        self.device_path = "7-2.3"
        self.descriptor, _identity = FIXTURE.accepted_identity(self.device_path)
        self.fail_action = fail_action
        self.events: list[tuple[object, ...]] = []
        self.closed = False

    def cmd(self, cdb, data_len=0):
        cdb = bytes(cdb)
        self.events.append(("cmd", cdb, data_len))
        if self.fail_action == "cmd":
            raise RuntimeError("synthetic command failure")
        if cdb[1] == SCRATCH._writer.SUB_IDENTIFY:
            return SCRATCH._writer.LOADER_IDENT, 0, 0
        if cdb[1] == SCRATCH._writer.SUB_DESC:
            return self.descriptor, 0, 0
        if cdb[1] == SCRATCH._writer.SUB_STATUS:
            return b"\x00", 0, 0
        return b"", 0, 0

    def program(self, cdb, payload):
        self.events.append(("program", bytes(cdb), bytes(payload)))
        if self.fail_action == "program":
            raise RuntimeError("synthetic program failure")

    def close(self):
        self.closed = True


class FakeSession:
    next_handle = 1

    def __init__(self, transaction, operation_index, image: bytearray, *,
                 capture_sequence: list[bytes] | None = None,
                 fail_execute: bool = False,
                 fail_close: bool = False) -> None:
        self.transaction = transaction
        self.operation_index = operation_index
        self.image = image
        self.capture_sequence = list(capture_sequence or [])
        self.fail_execute = fail_execute
        self.fail_close = fail_close
        self.execute_count = 0
        self.capture_count = 0
        self.closed = False
        self.handle = FakeSession.next_handle
        FakeSession.next_handle += 1

    def identity(self):
        _descriptor, identity = FIXTURE.accepted_identity()
        return identity

    def capture(self, *, progress=True):
        del progress
        self.capture_count += 1
        if self.capture_sequence:
            return self.capture_sequence.pop(0)
        return bytes(self.image)

    def execute(self):
        self.execute_count += 1
        if self.fail_execute:
            raise RuntimeError("synthetic mutation uncertainty")
        SCRATCH._apply_operation(
            self.image, self.transaction.operations[self.operation_index])

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError("synthetic close uncertainty")


class UpdaterScratchExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.production_loader = SCRATCH._restart.EXPECTED_LOADER_SHA256
        cls.production_public_loader = SCRATCH.EXPECTED_LOADER_SHA256
        cls.production_restart_plan = SCRATCH._restart.PLAN_SHA256
        cls.production_expected_restart_plan = (
            SCRATCH.EXPECTED_SOURCE_SCRATCH_PLAN_SHA256)
        cls.production_expected_plan = SCRATCH.EXPECTED_PLAN_SHA256
        cls.production_plan = SCRATCH.PLAN_SHA256
        cls.baseline = FIXTURE.make_v122_image()
        synthetic_loader = SCRATCH._writer.sha256_bytes(
            cls.baseline[
                SCRATCH._restart.LOADER_OFFSET:
                SCRATCH._restart.LOADER_OFFSET + SCRATCH._restart.LOADER_SIZE])
        SCRATCH._restart.EXPECTED_LOADER_SHA256 = synthetic_loader
        SCRATCH.EXPECTED_LOADER_SHA256 = synthetic_loader
        SCRATCH._restart.PLAN_SHA256 = SCRATCH._restart._plan_sha256()
        SCRATCH.EXPECTED_SOURCE_SCRATCH_PLAN_SHA256 = (
            SCRATCH._restart.PLAN_SHA256)
        SCRATCH.EXPECTED_PLAN_SHA256 = SCRATCH._plan_sha256()
        SCRATCH.PLAN_SHA256 = SCRATCH.EXPECTED_PLAN_SHA256
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="kb7-updater-scratch-tests-")
        cls.root = Path(cls.temporary.name)
        cls.baseline_a = cls.root / "baseline-a.bin"
        cls.baseline_b = cls.root / "baseline-b.bin"
        cls.baseline_a.write_bytes(cls.baseline)
        cls.baseline_b.write_bytes(cls.baseline)
        cls.transaction = SCRATCH.load_transaction(
            cls.baseline_a, cls.baseline_b)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()
        SCRATCH._restart.EXPECTED_LOADER_SHA256 = cls.production_loader
        SCRATCH.EXPECTED_LOADER_SHA256 = cls.production_public_loader
        SCRATCH._restart.PLAN_SHA256 = cls.production_restart_plan
        SCRATCH.EXPECTED_SOURCE_SCRATCH_PLAN_SHA256 = (
            cls.production_expected_restart_plan)
        SCRATCH.EXPECTED_PLAN_SHA256 = cls.production_expected_plan
        SCRATCH.PLAN_SHA256 = cls.production_plan

    def journal_path(self, name: str) -> Path:
        return self.root / name

    def identity(self, image: bytes) -> dict[str, str]:
        _descriptor, raw = FIXTURE.accepted_identity()
        return SCRATCH._identity_fields(raw, image)

    def other_process_nonce(self) -> str:
        candidate = "00" * 32
        return candidate if candidate != SCRATCH.PROCESS_NONCE else "11" * 32

    def write_boundary(self, path: Path, boundary: int) -> None:
        image = SCRATCH.expected_boundary_image(self.transaction, boundary)
        SCRATCH.write_journal_atomic(
            path, SCRATCH.boundary_journal(
                self.transaction, self.identity(image), boundary),
            require_absent=not path.exists())

    def test_fixed_plan_is_exact_complete_and_restores_baseline(self) -> None:
        operations = self.transaction.operations
        self.assertEqual(len(operations), 22)
        self.assertEqual(
            [operation.offset for operation in operations[:18]],
            [
                0xC4E00,
                *range(0xC5000, 0xC6000, 0x200),
                *range(0xC6000, 0xC7000, 0x200),
                0xC7000,
            ],
        )
        self.assertEqual(
            [operation.offset for operation in operations[18:]],
            [0xC5000, 0xC6000, 0xC4000, 0xC7000])
        self.assertEqual(
            SCRATCH.expected_boundary_image(self.transaction, len(operations)),
            self.baseline)
        self.assertEqual(
            self.transaction.boundary_sha256[0],
            self.transaction.boundary_sha256[-1])
        self.assertEqual(
            len(set(self.transaction.boundary_sha256[:-1])), len(operations))
        descriptor = SCRATCH.plan_descriptor()
        self.assertEqual(descriptor["address_mode_cdb_hex"], "f618" + "00" * 14)
        self.assertEqual(descriptor["envelope"], [0xC0000, 0x100000])
        self.assertEqual(
            descriptor["required_active_intent_checkpoint"],
            {
                "operation_index": 9,
                "operation_identifier": "program-09",
                "operation_offset": 0xC6000,
                "operation_cdb_hex": "f60600600c6000000100000000000000",
                "payload_sha256": (
                    "ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380"),
                "policy": "after_command_and_wip_poll_before_postread",
                "fresh_process_reconciliation_required": True,
                "automatic_retry": False,
                "single_attempt": True,
                "exact_preimage_policy": "stop_campaign_checkpoint_consumed",
            },
        )
        self.assertEqual(
            [item["cdb_hex"] for item in descriptor["operations"]],
            [operation.cdb.hex() for operation in operations])

    def test_reviewed_source_and_executor_plan_hashes_are_hard_pinned(self) -> None:
        self.assertEqual(
            self.production_restart_plan,
            "d784f036e06a972d9688d15c76a41cbd7e90ca806d5ced1aeab5aae16745085b")
        self.assertEqual(
            self.production_plan,
            "f0a8acfcdc7ab5fb7a7dc2753ed8bdca0e381a9433f64fe311348442a8bbdb32")

        drift = "00" * 32
        with mock.patch.object(SCRATCH._restart, "PLAN_SHA256", drift), \
                mock.patch.object(
                    SCRATCH._restart, "_plan_sha256", return_value=drift), \
                self.assertRaisesRegex(
                    SCRATCH.ScratchExecutorError, "scratch-plan source"):
            SCRATCH.load_transaction(self.baseline_a, self.baseline_b)

        changed = replace(
            SCRATCH.OPERATIONS[0],
            cdb=SCRATCH.OPERATIONS[0].cdb[:-1] + b"\x01")
        with mock.patch.object(
                SCRATCH, "OPERATIONS",
                (changed,) + SCRATCH.OPERATIONS[1:]), \
                self.assertRaisesRegex(
                    SCRATCH.ScratchExecutorError, "executor plan binding"):
            SCRATCH.load_transaction(self.baseline_a, self.baseline_b)

    def test_real_backend_emits_only_exact_internal_commands_for_all_ops(self) -> None:
        for index, operation in enumerate(self.transaction.operations):
            with self.subTest(operation=operation.identifier):
                device = FakeDevice()
                backend = SCRATCH.FixedScratchUsbMutationBackend(
                    self.transaction, index, device_factory=lambda: device)
                backend.execute()
                backend.close()
                if operation.action == "program":
                    self.assertEqual(
                        device.events,
                        [
                            ("cmd", SCRATCH._writer.cdb_simple(
                                SCRATCH._writer.SUB_EX4B), 0),
                            ("program", operation.cdb, operation.payload),
                            ("cmd", SCRATCH._writer.cdb_simple(
                                SCRATCH._writer.SUB_STATUS), 1),
                        ],
                    )
                else:
                    self.assertEqual(
                        device.events,
                        [
                            ("cmd", SCRATCH._writer.cdb_simple(
                                SCRATCH._writer.SUB_EX4B), 0),
                            ("cmd", operation.cdb, 0),
                            ("cmd", SCRATCH._writer.cdb_simple(
                                SCRATCH._writer.SUB_STATUS), 1),
                        ],
                    )
                self.assertTrue(device.closed)

    def test_backend_rejects_every_noncanonical_domain_before_usb(self) -> None:
        original = self.transaction.operations[0]
        for changed in (
                replace(original, offset=0xC4800,
                        cdb=SCRATCH._writer.cdb_program(0xC4800, 0x200)),
                replace(original, offset=0x11000,
                        cdb=SCRATCH._writer.cdb_program(0x11000, 0x200)),
                replace(
                    original,
                    payload=bytes([original.payload[0] ^ 1]) + original.payload[1:]),
                replace(original, cdb=original.cdb[:-1] + b"\x01")):
            opened = False

            def factory():
                nonlocal opened
                opened = True
                return FakeDevice()

            transaction = replace(
                self.transaction,
                operations=(changed,) + self.transaction.operations[1:])
            with self.subTest(offset=changed.offset), self.assertRaises(
                    SCRATCH.ScratchExecutorError):
                SCRATCH.FixedScratchUsbMutationBackend(
                    transaction, 0, device_factory=factory)
            self.assertFalse(opened)

        opened = False

        def factory():
            nonlocal opened
            opened = True
            return FakeDevice()

        generic = FIRMWARE._planner.Operation(
            "stage_core0", "erase", 0x11000, None, None, None)
        transaction = replace(
            self.transaction,
            operations=(generic,) + self.transaction.operations[1:])
        with self.assertRaisesRegex(
                SCRATCH.ScratchExecutorError, "fixed scratch domain"):
            SCRATCH.FixedScratchUsbMutationBackend(
                transaction, 0, device_factory=factory)
        self.assertFalse(opened)

    def test_backend_phase_order_failure_and_reuse_are_fail_closed(self) -> None:
        device = FakeDevice()
        backend = SCRATCH.FixedScratchUsbMutationBackend(
            self.transaction, 0, device_factory=lambda: device)
        with self.assertRaisesRegex(SCRATCH.ScratchExecutorError, "expected mode_set"):
            backend.mutate()
        backend.set_mode()
        with self.assertRaisesRegex(SCRATCH.ScratchExecutorError, "expected opened"):
            backend.set_mode()
        backend.mutate()
        with self.assertRaisesRegex(
                SCRATCH.ScratchExecutorError, "unavailable during mutation"):
            backend.capture(progress=False)
        backend.poll()
        with self.assertRaisesRegex(SCRATCH.ScratchExecutorError, "expected opened"):
            backend.execute()
        backend.close()

        failed_device = FakeDevice(fail_action="program")
        failed = SCRATCH.FixedScratchUsbMutationBackend(
            self.transaction, 0, device_factory=lambda: failed_device)
        failed.set_mode()
        with self.assertRaisesRegex(RuntimeError, "program failure"):
            failed.mutate()
        with self.assertRaisesRegex(SCRATCH.ScratchExecutorError, "failed"):
            failed.poll()
        failed.close()

    def test_preflight_requires_two_reads_and_publishes_separate_schema(self) -> None:
        journal = self.journal_path("preflight.json")
        image = bytearray(self.baseline)
        sessions: list[FakeSession] = []

        def factory(transaction, operation_index):
            session = FakeSession(transaction, operation_index, image)
            sessions.append(session)
            return session

        result = SCRATCH.live_preflight(
            self.transaction, journal, backend_factory=factory, progress=False)
        self.assertEqual(result["classification"], "exact_stock_or_complete")
        self.assertEqual(sessions[0].capture_count, 2)
        self.assertEqual(sessions[0].execute_count, 0)
        self.assertTrue(sessions[0].closed)
        saved = SCRATCH.load_journal(journal)
        SCRATCH.validate_journal(
            self.transaction, saved, self.identity(self.baseline))
        self.assertEqual(saved["schema"], SCRATCH.JOURNAL_SCHEMA)
        self.assertEqual(saved["boundary_index"], 0)

        unstable = self.journal_path("unstable-preflight.json")
        changed = bytearray(self.baseline)
        changed[-1] = 0xFE
        with self.assertRaisesRegex(SCRATCH.SafetyError, "differ"):
            SCRATCH.live_preflight(
                self.transaction, unstable,
                backend_factory=lambda transaction, index: FakeSession(
                    transaction, index, bytearray(self.baseline),
                    capture_sequence=[self.baseline, bytes(changed)]),
                progress=False)
        self.assertFalse(unstable.exists())

    def test_each_selected_step_has_two_pre_and_post_reads_and_one_mutation(self) -> None:
        for index in (0, 8, 10, 18, 21):
            with self.subTest(index=index):
                journal = self.journal_path(f"step-{index}.json")
                self.write_boundary(journal, index)
                image = bytearray(SCRATCH.expected_boundary_image(
                    self.transaction, index))
                session = FakeSession(self.transaction, index, image)
                result = SCRATCH.live_step(
                    self.transaction, journal,
                    backend_factory=lambda _transaction, _index: session,
                    progress=False)
                self.assertEqual(session.execute_count, 1)
                self.assertEqual(session.capture_count, 4)
                self.assertTrue(session.closed)
                self.assertFalse(result["automatic_retry"])
                self.assertEqual(bytes(image), SCRATCH.expected_boundary_image(
                    self.transaction, index + 1))
                if index == len(self.transaction.operations) - 1:
                    self.assertTrue(journal.exists())
                    self.assertEqual(SCRATCH.load_journal(journal)["status"], "complete")
                    self.assertEqual(result["classification"],
                                     "exact_baseline_restored_pending_finalize")
                    final_session = FakeSession(
                        self.transaction, index, bytearray(self.baseline))
                    finalized = SCRATCH.live_reconcile(
                        self.transaction, journal,
                        backend_factory=lambda _transaction, _index: final_session,
                        progress=False)
                    self.assertTrue(finalized["state_cleared"])
                    self.assertFalse(journal.exists())
                else:
                    self.assertEqual(
                        SCRATCH.load_journal(journal)["boundary_index"], index + 1)

    def test_mandatory_checkpoint_executes_once_without_postread_and_reconciles_fresh(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        self.assertEqual(index, 9)
        operation = self.transaction.operations[index]
        self.assertEqual(
            (operation.identifier, operation.action, operation.offset,
             operation.cdb.hex(), SCRATCH._writer.sha256_bytes(operation.payload)),
            (
                "program-09", "program", 0xC6000,
                "f60600600c6000000100000000000000",
                "ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380",
            ),
        )

        journal = self.journal_path("checkpoint-postimage.json")
        self.write_boundary(journal, index)
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        image = bytearray(preimage)
        mutation_session = FakeSession(self.transaction, index, image)

        result = SCRATCH.live_step(
            self.transaction, journal,
            backend_factory=lambda _transaction, _index: mutation_session,
            progress=False)

        self.assertEqual(mutation_session.capture_count, 2)
        self.assertEqual(mutation_session.execute_count, 1)
        self.assertTrue(mutation_session.closed)
        self.assertEqual(bytes(image), postimage)
        self.assertEqual(result["classification"],
                         "planned_active_intent_checkpoint")
        self.assertEqual(result["command_completed_operation"], "program-09")
        self.assertTrue(result["reconciliation_required"])
        self.assertFalse(result["postread_performed"])
        self.assertFalse(result["automatic_retry"])
        self.assertEqual(result["boundary_index"], index)
        self.assertEqual(result["expected_post_boundary_index"], index + 1)
        pending = SCRATCH.load_journal(journal)
        self.assertEqual(pending["status"], "intent")
        self.assertEqual(pending["boundary_index"], index)
        self.assertEqual(pending["active_operation_id"], "program-09")
        self.assertEqual(pending["intent_process_nonce"], SCRATCH.PROCESS_NONCE)

        opened = False

        def same_process_factory(_transaction, _index):
            nonlocal opened
            opened = True
            return FakeSession(self.transaction, index, image)

        with self.assertRaisesRegex(
                SCRATCH.ScratchExecutorError, "fresh process"):
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=same_process_factory, progress=False)
        self.assertFalse(opened)

        next_nonce = self.other_process_nonce()
        reconcile_session = FakeSession(self.transaction, index, image)
        self.assertNotEqual(mutation_session.handle, reconcile_session.handle)
        with mock.patch.object(SCRATCH, "PROCESS_NONCE", next_nonce):
            reconciled = SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: reconcile_session,
                progress=False)

        self.assertEqual(reconcile_session.capture_count, 2)
        self.assertEqual(reconcile_session.execute_count, 0)
        self.assertTrue(reconcile_session.closed)
        self.assertEqual(reconciled["classification"], "exact_postimage_completed")
        self.assertEqual(reconciled["boundary_index"], index + 1)
        self.assertEqual(reconciled["next_operation"], "program-10")
        self.assertFalse(reconciled["automatic_retry"])
        verified = SCRATCH.load_journal(journal)
        self.assertEqual(verified["status"], "boundary_verified")
        self.assertEqual(verified["boundary_index"], index + 1)
        self.assertIsNone(verified["intent_process_nonce"])

    def test_checkpoint_exact_preimage_is_terminal_and_is_never_retried(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        journal = self.journal_path("checkpoint-preimage.json")
        self.write_boundary(journal, index)
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        failed_mutation = FakeSession(
            self.transaction, index, bytearray(preimage), fail_execute=True)

        with self.assertRaises(SCRATCH.ReconciliationRequired):
            SCRATCH.live_step(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: failed_mutation,
                progress=False)
        self.assertEqual(failed_mutation.capture_count, 2)
        self.assertEqual(failed_mutation.execute_count, 1)
        self.assertEqual(SCRATCH.load_journal(journal)["status"], "intent")

        read_only = FakeSession(
            self.transaction, index, bytearray(preimage))
        with mock.patch.object(
                SCRATCH, "PROCESS_NONCE", self.other_process_nonce()):
            stopped = SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertEqual(read_only.capture_count, 2)
        self.assertEqual(read_only.execute_count, 0)
        self.assertTrue(read_only.closed)
        self.assertEqual(
            stopped["classification"],
            "exact_preimage_checkpoint_consumed_no_effect")
        self.assertEqual(stopped["boundary_index"], index)
        self.assertIsNone(stopped["next_operation"])
        self.assertFalse(stopped["automatic_retry"])
        self.assertTrue(stopped["campaign_stopped"])
        self.assertFalse(stopped["state_cleared"])
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"], "checkpoint_no_effect")

        argv = [
            str(TOOL_PATH), "reconcile",
            "--baseline-a", str(self.baseline_a),
            "--baseline-b", str(self.baseline_b),
            "--journal", str(journal),
            "--commit",
        ]
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(
                    SCRATCH, "live_reconcile", return_value=stopped) as reconcile, \
                redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            result = SCRATCH.main()
        self.assertEqual(result, 5)
        reconcile.assert_called_once()
        self.assertIn("CAMPAIGN STOPPED", stderr.getvalue())
        self.assertIn("Do not retry or run step", stderr.getvalue())

        dry_step_argv = [
            str(TOOL_PATH), "step",
            "--baseline-a", str(self.baseline_a),
            "--baseline-b", str(self.baseline_b),
            "--journal", str(journal),
        ]
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", dry_step_argv), \
                mock.patch.object(SCRATCH, "live_step") as live, \
                mock.patch.object(
                    SCRATCH._writer._verify, "_load_libusb") as load_libusb, \
                redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            result = SCRATCH.main()
        self.assertEqual(result, 2)
        live.assert_not_called()
        load_libusb.assert_not_called()
        self.assertIn("campaign is consumed", stderr.getvalue())

        opened = False

        def forbidden_retry(_transaction, _index):
            nonlocal opened
            opened = True
            return FakeSession(self.transaction, index, bytearray(preimage))

        with self.assertRaisesRegex(
                SCRATCH.ScratchExecutorError,
                "campaign is consumed; USB mutation retry is prohibited"):
            SCRATCH.live_step(
                self.transaction, journal,
                backend_factory=forbidden_retry, progress=False)
        self.assertFalse(opened)

    def test_checkpoint_binding_and_intent_publication_fail_closed(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        operation = self.transaction.operations[index]
        changed = replace(operation, identifier="program-08")
        operations = (
            self.transaction.operations[:index] + (changed,) +
            self.transaction.operations[index + 1:])
        with self.assertRaisesRegex(
                SCRATCH.ScratchExecutorError, "reviewed command"):
            SCRATCH._validate_checkpoint_operation(operations)

        journal = self.journal_path("checkpoint-publish-failure.json")
        self.write_boundary(journal, index)
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        session = FakeSession(self.transaction, index, bytearray(preimage))

        def stop_publication(_site):
            raise RuntimeError("synthetic checkpoint publication failure")

        with self.assertRaisesRegex(RuntimeError, "checkpoint publication"):
            SCRATCH.live_step(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: session,
                progress=False, journal_fault=stop_publication)
        self.assertEqual(session.capture_count, 2)
        self.assertEqual(session.execute_count, 0)
        self.assertEqual(
            SCRATCH.load_journal(journal)["boundary_index"], index)
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"], "boundary_verified")

    def test_transport_or_postread_failure_leaves_intent_and_never_retries(self) -> None:
        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        for name, session in (
                ("transport", FakeSession(
                    self.transaction, index, bytearray(preimage), fail_execute=True)),
                ("postread", FakeSession(
                    self.transaction, index, bytearray(preimage),
                    capture_sequence=[preimage, preimage, preimage, preimage])),
        ):
            with self.subTest(name=name):
                journal = self.journal_path(f"failure-{name}.json")
                self.write_boundary(journal, index)
                if name == "postread":
                    original_execute = session.execute

                    def mutate_but_report_old():
                        original_execute()
                        session.capture_sequence = [preimage, preimage]

                    session.execute = mutate_but_report_old
                with self.assertRaises(SCRATCH.ReconciliationRequired):
                    SCRATCH.live_step(
                        self.transaction, journal,
                        backend_factory=lambda _transaction, _index: session,
                        progress=False)
                self.assertEqual(session.execute_count, 1)
                self.assertEqual(SCRATCH.load_journal(journal)["status"], "intent")
                self.assertTrue(session.closed)

    def test_intent_publication_and_close_failures_never_expand_authority(self) -> None:
        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)

        before_intent = self.journal_path("before-intent-failure.json")
        self.write_boundary(before_intent, index)
        session = FakeSession(self.transaction, index, bytearray(preimage))

        def stop_publication(_site):
            raise RuntimeError("synthetic journal publication failure")

        with self.assertRaisesRegex(RuntimeError, "journal publication"):
            SCRATCH.live_step(
                self.transaction, before_intent,
                backend_factory=lambda _transaction, _index: session,
                progress=False, journal_fault=stop_publication)
        self.assertEqual(session.execute_count, 0)
        self.assertEqual(
            SCRATCH.load_journal(before_intent)["boundary_index"], index)

        after_intent = self.journal_path("close-failure.json")
        self.write_boundary(after_intent, index)
        closing = FakeSession(
            self.transaction, index, bytearray(preimage), fail_close=True)
        with self.assertRaisesRegex(
                SCRATCH.ReconciliationRequired, "uncertain USB close"):
            SCRATCH.live_step(
                self.transaction, after_intent,
                backend_factory=lambda _transaction, _index: closing,
                progress=False)
        self.assertEqual(closing.execute_count, 1)
        self.assertTrue(closing.closed)
        self.assertEqual(
            SCRATCH.load_journal(after_intent)["boundary_index"], index + 1)

    def test_reconcile_uses_new_read_only_session_for_exact_pre_or_post(self) -> None:
        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        for label, image, expected_boundary in (
                ("pre", preimage, index), ("post", postimage, index + 1)):
            with self.subTest(label=label):
                journal = self.journal_path(f"reconcile-{label}.json")
                SCRATCH.write_journal_atomic(
                    journal,
                    SCRATCH.intent_journal(
                        self.transaction, self.identity(preimage), index,
                        process_nonce=self.other_process_nonce()),
                    require_absent=True)
                session = FakeSession(
                    self.transaction, index, bytearray(image))
                result = SCRATCH.live_reconcile(
                    self.transaction, journal,
                    backend_factory=lambda _transaction, _index: session,
                    progress=False)
                self.assertEqual(session.capture_count, 2)
                self.assertEqual(session.execute_count, 0)
                self.assertTrue(session.closed)
                self.assertFalse(result["automatic_retry"])
                self.assertEqual(result["boundary_index"], expected_boundary)
                self.assertEqual(
                    SCRATCH.load_journal(journal)["boundary_index"],
                    expected_boundary)

    def test_reconcile_rejects_partial_unstable_and_outside_damage(self) -> None:
        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        cases: list[tuple[str, list[bytes]]] = []
        partial = bytearray(preimage)
        partial[self.transaction.operations[index].offset] = \
            postimage[self.transaction.operations[index].offset]
        cases.append(("partial", [bytes(partial), bytes(partial)]))
        outside = bytearray(preimage)
        outside[0x11000] ^= 1
        cases.append(("outside", [bytes(outside), bytes(outside)]))
        cases.append(("unstable", [preimage, postimage]))
        for name, images in cases:
            with self.subTest(name=name):
                journal = self.journal_path(f"bad-{name}.json")
                SCRATCH.write_journal_atomic(
                    journal,
                    SCRATCH.intent_journal(
                        self.transaction, self.identity(preimage), index,
                        process_nonce=self.other_process_nonce()),
                    require_absent=True)
                session = FakeSession(
                    self.transaction, index, bytearray(images[0]),
                    capture_sequence=images)
                expected = (SCRATCH.SafetyError if name == "unstable"
                            else SCRATCH.RecoveryRequired)
                with self.assertRaises(expected):
                    SCRATCH.live_reconcile(
                        self.transaction, journal,
                        backend_factory=lambda _transaction, _index: session,
                        progress=False)
                self.assertEqual(session.execute_count, 0)
                self.assertEqual(SCRATCH.load_journal(journal)["status"], "intent")

    def test_journal_domain_tamper_paths_and_publish_are_fail_closed(self) -> None:
        journal = self.journal_path("strict.json")
        self.write_boundary(journal, 0)
        value = SCRATCH.load_journal(journal)
        self.assertEqual(
            SCRATCH.JOURNAL_SCHEMA, "kb7-usb-updater-scratch-journal-v2")
        for key, changed in (
                ("plan_sha256", "00" * 32),
                ("boundary_index", 3),
                ("schema", "kb7-usb-updater-scratch-journal-v1"),
                ("schema", FIRMWARE.JOURNAL_SCHEMA)):
            tampered = dict(value)
            tampered[key] = changed
            with self.subTest(key=key), self.assertRaises(
                    SCRATCH.ScratchExecutorError):
                SCRATCH.validate_journal(self.transaction, tampered)

        intent = SCRATCH.intent_journal(
            self.transaction, self.identity(self.baseline), 0)
        intent["intent_process_nonce"] = "not-a-process-nonce"
        with self.assertRaisesRegex(
                SCRATCH.ScratchExecutorError, "intent_process_nonce"):
            SCRATCH.validate_journal(self.transaction, intent)

        duplicate = self.journal_path("duplicate.json")
        duplicate.write_text('{"schema":"a","schema":"b"}\n', encoding="utf-8")
        with self.assertRaisesRegex(SCRATCH.ScratchExecutorError, "duplicate"):
            SCRATCH.load_journal(duplicate)
        nonfinite = self.journal_path("nonfinite.json")
        nonfinite.write_text('{"schema":NaN}\n', encoding="utf-8")
        with self.assertRaisesRegex(SCRATCH.ScratchExecutorError, "non-finite"):
            SCRATCH.load_journal(nonfinite)
        with self.assertRaisesRegex(SCRATCH.ScratchExecutorError, "baseline"):
            SCRATCH.validate_journal_path(self.transaction, self.baseline_a)

        published = self.journal_path("published.json")
        with mock.patch.object(SCRATCH.os, "fsync", wraps=SCRATCH.os.fsync) as fsync:
            SCRATCH.write_journal_atomic(
                published,
                SCRATCH.boundary_journal(
                    self.transaction, self.identity(self.baseline), 0),
                require_absent=True)
        self.assertGreaterEqual(fsync.call_count, 2)
        self.assertEqual(published.stat().st_mode & 0o777, 0o600)

    def test_process_lock_blocks_stale_concurrent_steps_before_usb(self) -> None:
        journal = self.journal_path("locked.json")
        self.write_boundary(journal, 0)
        opened = False

        def factory(_transaction, _index):
            nonlocal opened
            opened = True
            return FakeSession(
                self.transaction, 0, bytearray(self.baseline))

        lock_path = SCRATCH.journal_lock_path(journal)
        with SCRATCH.scratch_journal_lock(self.transaction, journal):
            with self.assertRaisesRegex(
                    SCRATCH.ScratchExecutorError, "holds this journal lock"):
                SCRATCH.live_step(
                    self.transaction, journal, backend_factory=factory,
                    progress=False)
        self.assertFalse(opened)
        self.assertTrue(lock_path.exists())
        self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(lock_path.stat().st_size, 0)

    def test_step_dry_run_validates_state_and_checkpoint_cli_maps_to_exit_four(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)

        unresolved = self.journal_path("dry-run-unresolved.json")
        SCRATCH.write_journal_atomic(
            unresolved,
            SCRATCH.intent_journal(
                self.transaction, self.identity(preimage), index),
            require_absent=True)
        argv = [
            str(TOOL_PATH), "step",
            "--baseline-a", str(self.baseline_a),
            "--baseline-b", str(self.baseline_b),
            "--journal", str(unresolved),
        ]
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(SCRATCH, "live_step") as live, \
                mock.patch.object(
                    SCRATCH._writer._verify, "_load_libusb") as load_libusb, \
                redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            result = SCRATCH.main()
        self.assertEqual(result, 2)
        live.assert_not_called()
        load_libusb.assert_not_called()
        self.assertIn("unresolved intent requires reconcile", stderr.getvalue())

        checkpoint = self.journal_path("dry-run-checkpoint.json")
        self.write_boundary(checkpoint, index)
        argv[-1] = str(checkpoint)
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(SCRATCH, "live_step") as live, \
                mock.patch.object(
                    SCRATCH._writer._verify, "_load_libusb") as load_libusb, \
                redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            result = SCRATCH.main()
        self.assertEqual(result, 0)
        live.assert_not_called()
        load_libusb.assert_not_called()
        self.assertIn("checkpoint: mandatory", stdout.getvalue())
        self.assertIn("no USB device was opened", stdout.getvalue())

        argv.append("--commit")
        checkpoint_result = {
            "classification": "planned_active_intent_checkpoint",
            "command_completed_operation": "program-09",
            "boundary_index": index,
            "expected_post_boundary_index": index + 1,
            "next_operation": None,
            "observed_sha256": None,
            "automatic_retry": False,
            "postread_performed": False,
            "reconciliation_required": True,
            "state_cleared": False,
            "firmware_region_mutation_enabled": False,
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(
                    SCRATCH, "live_step", return_value=checkpoint_result) as live, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            result = SCRATCH.main()
        self.assertEqual(result, 4)
        live.assert_called_once()
        self.assertIn('"reconciliation_required": true', stdout.getvalue())
        self.assertIn("planned active-intent checkpoint", stderr.getvalue())
        self.assertIn("fresh process", stderr.getvalue())

    def test_dry_run_cli_opens_no_usb_and_exposes_no_raw_authority(self) -> None:
        journal = self.journal_path("dry-run.json")
        argv = [
            str(TOOL_PATH), "preflight",
            "--baseline-a", str(self.baseline_a),
            "--baseline-b", str(self.baseline_b),
            "--journal", str(journal),
        ]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(SCRATCH, "live_preflight") as live, \
                mock.patch.object(
                    SCRATCH._writer._verify, "_load_libusb") as load_libusb, \
                redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            result = SCRATCH.main()
        self.assertEqual(result, 0)
        live.assert_not_called()
        load_libusb.assert_not_called()
        self.assertFalse(journal.exists())
        self.assertIn("no USB device was opened", stdout.getvalue())

        help_outputs = []
        for command in (None, "preflight", "step", "reconcile"):
            arguments = [sys.executable, str(TOOL_PATH)]
            if command is not None:
                arguments.append(command)
            arguments.append("--help")
            help_result = subprocess.run(
                arguments, text=True, capture_output=True, check=False)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            help_outputs.append(help_result.stdout.lower())
        self.assertIn("{preflight,step,reconcile}", help_outputs[0])
        for output in help_outputs:
            for forbidden in (
                    "--offset", "--cdb", "--payload", "--operation",
                    "--bundle", "--force", "--retry", "--device"):
                self.assertNotIn(forbidden, output)
        self.assertFalse(FIRMWARE.LIVE_MUTATION_ENABLED)


if __name__ == "__main__":
    unittest.main()
