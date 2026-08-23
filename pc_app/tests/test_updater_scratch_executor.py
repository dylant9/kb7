"""Offline tests for the fixed scratch-only updater execution harness."""

from __future__ import annotations

from contextlib import nullcontext, redirect_stderr, redirect_stdout
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
                 fail_wait_ready: bool = False,
                 fail_capture: bool = False,
                 fail_close: bool = False) -> None:
        self.transaction = transaction
        self.operation_index = operation_index
        self.image = image
        self.capture_sequence = list(capture_sequence or [])
        self.fail_execute = fail_execute
        self.fail_wait_ready = fail_wait_ready
        self.fail_capture = fail_capture
        self.fail_close = fail_close
        self.execute_count = 0
        self.capture_count = 0
        self.wait_ready_count = 0
        self.abandon_count = 0
        self.close_count = 0
        self.events: list[str] = []
        self.closed = False
        self.handle = FakeSession.next_handle
        FakeSession.next_handle += 1

    def identity(self):
        self.events.append("identity")
        _descriptor, identity = FIXTURE.accepted_identity()
        return identity

    def capture(self, *, progress=True):
        del progress
        self.capture_count += 1
        self.events.append("capture")
        if self.fail_capture:
            raise RuntimeError("synthetic read uncertainty")
        if self.capture_sequence:
            return self.capture_sequence.pop(0)
        return bytes(self.image)

    def _mutate(self):
        self.execute_count += 1
        if self.fail_execute:
            raise RuntimeError("synthetic mutation uncertainty")
        SCRATCH._apply_operation(
            self.image, self.transaction.operations[self.operation_index])

    def execute(self):
        self.events.append("execute")
        self._mutate()

    def execute_checkpoint_before_poll(self):
        self.events.append("checkpoint_command_complete")
        self._mutate()

    def abandon_without_close(self):
        self.abandon_count += 1
        self.events.append("abandon_without_close")

    def wait_ready(self):
        self.wait_ready_count += 1
        self.events.append("wait_ready")
        if self.fail_wait_ready:
            raise RuntimeError("synthetic ready-poll uncertainty")

    def close(self):
        self.close_count += 1
        self.events.append("close")
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
        cls.production_computed_plan = SCRATCH._plan_sha256()
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

    def write_checkpoint_ready(
            self, path: Path, *, process_nonce: str | None = None) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        ready = SCRATCH.intent_journal(
            self.transaction, self.identity(preimage), index,
            process_nonce=(
                self.other_process_nonce() if process_nonce is None
                else process_nonce))
        ready["status"] = SCRATCH.CHECKPOINT_READY_STATUS
        SCRATCH.write_journal_atomic(
            path, ready, require_absent=not path.exists())

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
        self.assertEqual(
            descriptor["schema"], "kb7-usb-updater-fixed-scratch-plan-v3")
        self.assertEqual(descriptor["address_mode_cdb_hex"], "f618" + "00" * 14)
        self.assertEqual(descriptor["envelope"], [0xC0000, 0x100000])
        self.assertEqual(
            descriptor["failure_policy"],
            {
                "preflight_started_durable_before_backend_construction_or_usb": True,
                "preflight_started_failure": "external_spi_no_retry",
                "raw_intent_durable_before_backend_construction_or_usb": True,
                "intent_publication_ambiguity": (
                    "no_usb_fresh_process_dry_run_state_inspection"),
                "post_intent_transport_verification_or_checkpoint_ready_source_retained": (
                    "abandon_without_explicit_close_external_spi"),
                "ordinary_operation_intent_reconciliation": (
                    "prohibited_external_spi"),
                "checkpoint_intent_before_command_complete_reconciliation": (
                    "prohibited_external_spi"),
                "checkpoint_command_complete_reconciliation": (
                    "one_fresh_process_read_only_attempt"),
                "reconciliation_started_failure": (
                    "external_spi_no_retry"),
                "mutation_or_reconciliation_close_failure": (
                    "external_spi_no_retry"),
                "reconciliation_start_publication_failure_with_source_retained": (
                    "fresh_process_retry_permitted"),
                "final_state_publication_source_retained_after_clean_close": (
                    "external_spi_no_retry"),
                "checkpoint_ready_publication_error_with_exact_target_visible": (
                    "read_only_cleanup_only_experiment_invalid"),
                "verified_boundary_publication_error_with_exact_target_visible": (
                    "accept_exact_visible_target"),
                "final_clear_error_with_journal_absent": (
                    "accept_exact_cleared_state"),
                "unclassifiable_atomic_transition_outcome": (
                    "fresh_process_dry_run_state_inspection"),
            },
        )
        self.assertEqual(
            descriptor["required_active_intent_checkpoint"],
            {
                "operation_index": 9,
                "operation_identifier": "program-09",
                "operation_offset": 0xC6000,
                "operation_cdb_hex": "f60600600c6000000100000000000000",
                "payload_sha256": (
                    "ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380"),
                "policy": (
                    "after_validated_program_csw_before_wip_poll_or_postread"),
                "termination": "self_sigkill",
                "signal": 9,
                "expected_shell_status": 137,
                "termination_failure_shell_status": 126,
                "durable_command_complete_status_before_termination": (
                    "checkpoint_command_complete"),
                "durable_reconciliation_started_status_before_usb": (
                    "checkpoint_reconcile_started"),
                "shell_status_137_required_for_validation_evidence": True,
                "shell_status_evidence_not_machine_bound": True,
                "invalid_termination_cleanup_must_not_count_as_validation": True,
                "command_complete_state_allows_cleanup_after_invalid_termination": True,
                "validated_program_csw_required": True,
                "wip_poll_before_termination": False,
                "postread_before_termination": False,
                "explicit_usb_close_before_termination": False,
                "fresh_process_reconciliation_required": True,
                "fresh_process_wip_poll_required": True,
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
            self.production_expected_plan,
            "c1aa9348e74d6d4590b0e9666a9daf83e5544c3b23292b3df217c34038d5b653")
        self.assertEqual(self.production_plan, self.production_expected_plan)
        self.assertEqual(
            self.production_computed_plan, self.production_expected_plan,
            "production plan descriptor drifted from its reviewed hard pin")

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

        checkpoint = self.transaction.operations[SCRATCH.CHECKPOINT_OPERATION_INDEX]
        device = FakeDevice()
        backend = SCRATCH.FixedScratchUsbMutationBackend(
            self.transaction, SCRATCH.CHECKPOINT_OPERATION_INDEX,
            device_factory=lambda: device)
        backend.execute_checkpoint_before_poll()
        backend.abandon_without_close()
        self.assertEqual(
            device.events,
            [
                ("cmd", SCRATCH._writer.cdb_simple(
                    SCRATCH._writer.SUB_EX4B), 0),
                ("program", checkpoint.cdb, checkpoint.payload),
            ],
        )
        self.assertFalse(device.closed)

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

    def test_scratch_transports_never_clear_halt_after_failed_xfer(self) -> None:
        self.assertFalse(SCRATCH._writer.WriteDevice.clear_halt_on_error)
        self.assertFalse(
            SCRATCH.FixedScratchStrictWriteDevice.clear_halt_on_error)
        self.assertFalse(
            SCRATCH.FixedScratchNoRecoveryReadOnlyDevice.clear_halt_on_error)

        class FailingLibusb:
            def __init__(self) -> None:
                self.clear_halt_calls = 0

            @staticmethod
            def libusb_bulk_transfer(*_arguments):
                return -1

            def libusb_clear_halt(self, *_arguments):
                self.clear_halt_calls += 1
                return 0

        for device_class in (
                SCRATCH._writer.WriteDevice,
                SCRATCH.FixedScratchNoRecoveryReadOnlyDevice):
            with self.subTest(device_class=device_class.__name__):
                fake_libusb = FailingLibusb()
                device = object.__new__(device_class)
                device.h = None
                buffer = SCRATCH._writer._verify.ct.create_string_buffer(1)
                with mock.patch.object(
                        SCRATCH._writer._verify, "lib", fake_libusb), \
                        self.assertRaisesRegex(RuntimeError, "bulk transfer failed"):
                    device._xfer(0x81, buffer, 1)
                self.assertEqual(fake_libusb.clear_halt_calls, 0)

    def test_strict_real_libusb_close_checks_release_attach_and_always_tears_down(
            self) -> None:
        class FakeLibusb:
            def __init__(self, *, release_rc=0, attach_rc=0) -> None:
                self.release_rc = release_rc
                self.attach_rc = attach_rc
                self.events: list[tuple[object, ...]] = []

            def libusb_release_interface(self, handle, interface):
                self.events.append(("release", handle, interface))
                return self.release_rc

            def libusb_attach_kernel_driver(self, handle, interface):
                self.events.append(("attach", handle, interface))
                return self.attach_rc

            def libusb_close(self, handle):
                self.events.append(("close", handle))

            def libusb_exit(self, context):
                self.events.append(("exit", context))

        def make_device(device_class):
            device = object.__new__(device_class)
            device.h = "handle"
            device.iface = 4
            device.reattach = True
            device.ctx = "context"
            return device

        release_failure = FakeLibusb(release_rc=-7)
        device = make_device(SCRATCH.FixedScratchStrictWriteDevice)
        with mock.patch.object(
                SCRATCH._writer._verify, "lib", release_failure), \
                self.assertRaisesRegex(
                    RuntimeError, r"libusb_release_interface failed \(-7\)"):
            device.close()
        self.assertEqual(
            release_failure.events,
            [
                ("release", "handle", 4),
                ("close", "handle"),
                ("exit", "context"),
            ],
        )

        attach_failure = FakeLibusb(attach_rc=-8)
        device = make_device(SCRATCH.FixedScratchStrictWriteDevice)
        with mock.patch.object(
                SCRATCH._writer._verify, "lib", attach_failure), \
                self.assertRaisesRegex(
                    RuntimeError, r"libusb_attach_kernel_driver failed \(-8\)"):
            device.close()
        self.assertEqual(
            attach_failure.events,
            [
                ("release", "handle", 4),
                ("attach", "handle", 4),
                ("close", "handle"),
                ("exit", "context"),
            ],
        )

        for device_class in (
                SCRATCH.FixedScratchStrictWriteDevice,
                SCRATCH.FixedScratchNoRecoveryReadOnlyDevice):
            with self.subTest(device_class=device_class.__name__):
                success = FakeLibusb()
                device = make_device(device_class)
                with mock.patch.object(
                        SCRATCH._writer._verify, "lib", success):
                    device.close()
                self.assertEqual(
                    success.events,
                    [
                        ("release", "handle", 4),
                        ("attach", "handle", 4),
                        ("close", "handle"),
                        ("exit", "context"),
                    ],
                )

    def test_production_backends_bind_strict_devices_and_close_once_on_failure(
            self) -> None:
        self.assertIs(
            SCRATCH.FixedScratchUsbMutationBackend.__init__.__kwdefaults__[
                "device_factory"],
            SCRATCH.FixedScratchStrictWriteDevice,
        )
        self.assertIs(
            SCRATCH.FixedScratchReadOnlyBackend.__init__.__kwdefaults__[
                "device_factory"],
            SCRATCH.FixedScratchNoRecoveryReadOnlyDevice,
        )

        class FailingCloseDevice:
            def __init__(self) -> None:
                self.close_count = 0

            def close(self):
                self.close_count += 1
                raise RuntimeError("synthetic strict close failure")

        mutation_device = FailingCloseDevice()
        mutation = SCRATCH.FixedScratchUsbMutationBackend(
            self.transaction, 0, device_factory=lambda: mutation_device)
        with self.assertRaisesRegex(RuntimeError, "strict close failure"):
            mutation.close()
        mutation.close()
        self.assertEqual(mutation_device.close_count, 1)
        self.assertEqual(mutation._phase, "closed")

        read_only_device = FailingCloseDevice()
        read_only = SCRATCH.FixedScratchReadOnlyBackend(
            self.transaction, 0, device_factory=lambda: read_only_device)
        with self.assertRaisesRegex(RuntimeError, "strict close failure"):
            read_only.close()
        read_only.close()
        self.assertEqual(read_only_device.close_count, 1)
        self.assertTrue(read_only._closed)

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
        unstable_session = FakeSession(
            self.transaction, 0, bytearray(self.baseline),
            capture_sequence=[self.baseline, bytes(changed)])
        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "preflight transport or exact verification failed") as caught:
            SCRATCH.live_preflight(
                self.transaction, unstable,
                backend_factory=lambda _transaction, _index: unstable_session,
                progress=False)
        self.assertIsInstance(caught.exception.__cause__, SCRATCH.SafetyError)
        self.assertEqual(unstable_session.close_count, 0)
        unstable_state = SCRATCH.load_journal(unstable)
        self.assertEqual(
            unstable_state["status"], SCRATCH.PREFLIGHT_STARTED_STATUS)
        self.assertEqual(unstable_state["boundary_index"], 0)

        close_failure = self.journal_path("preflight-close-failure.json")
        closing_session = FakeSession(
            self.transaction, 0, bytearray(self.baseline), fail_close=True)
        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "preflight ended with an uncertain USB close"):
            SCRATCH.live_preflight(
                self.transaction, close_failure,
                backend_factory=lambda _transaction, _index: closing_session,
                progress=False)
        self.assertEqual(closing_session.capture_count, 2)
        self.assertEqual(closing_session.close_count, 1)
        closing_state = SCRATCH.load_journal(close_failure)
        self.assertEqual(
            closing_state["status"], SCRATCH.PREFLIGHT_STARTED_STATUS)
        self.assertEqual(closing_state["boundary_index"], 0)

    def test_preflight_start_precedes_backend_and_failures_are_terminal(
            self) -> None:
        for name in ("constructor", "identity", "read"):
            with self.subTest(name=name):
                journal = self.journal_path(f"preflight-start-{name}.json")
                opened = False
                session = FakeSession(
                    self.transaction, 0, bytearray(self.baseline),
                    fail_capture=name == "read")
                if name == "identity":
                    session.identity = mock.Mock(
                        side_effect=RuntimeError("synthetic identity failure"))

                def factory(_transaction, _index):
                    nonlocal opened
                    opened = True
                    armed = SCRATCH.load_journal(journal)
                    self.assertEqual(
                        armed["status"], SCRATCH.PREFLIGHT_STARTED_STATUS)
                    if name == "constructor":
                        raise RuntimeError("synthetic constructor failure")
                    return session

                with self.assertRaisesRegex(
                        SCRATCH.RecoveryRequired,
                        "preflight transport or exact verification failed"):
                    SCRATCH.live_preflight(
                        self.transaction, journal,
                        backend_factory=factory, progress=False)

                self.assertTrue(opened)
                terminal = SCRATCH.load_journal(journal)
                self.assertEqual(
                    terminal["status"], SCRATCH.PREFLIGHT_STARTED_STATUS)
                self.assertEqual(terminal["boundary_index"], 0)
                self.assertEqual(session.close_count, 0)
                for gate in (
                        SCRATCH._require_step_state,
                        SCRATCH._require_reconcile_state):
                    with self.assertRaisesRegex(
                            SCRATCH.RecoveryRequired, "preflight USB attempt"):
                        gate(self.transaction, terminal)

    def test_preflight_atomic_outcomes_never_open_usb_ambiguously(self) -> None:
        opened = False

        def forbidden_factory(_transaction, _index):
            nonlocal opened
            opened = True
            raise AssertionError("ambiguous preflight must not open USB")

        absent = self.journal_path("preflight-source-retained.json")
        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=RuntimeError("synthetic pre-replace failure")), \
                self.assertRaisesRegex(
                    SCRATCH.StateInspectionRequired,
                    "preflight-started was not published"):
            SCRATCH.live_preflight(
                self.transaction, absent,
                backend_factory=forbidden_factory, progress=False)
        self.assertFalse(opened)
        self.assertFalse(absent.exists())

        visible = self.journal_path("preflight-target-visible.json")
        real_write = SCRATCH.write_journal_atomic

        def publish_then_error(*args, **kwargs):
            real_write(*args, **kwargs)
            raise RuntimeError("synthetic post-replace failure")

        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=publish_then_error), \
                self.assertRaisesRegex(
                    SCRATCH.RecoveryRequired,
                    "preflight-started became visible"):
            SCRATCH.live_preflight(
                self.transaction, visible,
                backend_factory=forbidden_factory, progress=False)
        self.assertFalse(opened)
        self.assertEqual(
            SCRATCH.load_journal(visible)["status"],
            SCRATCH.PREFLIGHT_STARTED_STATUS)

        unreadable = self.journal_path("preflight-readback-ambiguous.json")
        real_load = SCRATCH.load_journal
        with mock.patch.object(
                SCRATCH, "load_journal",
                side_effect=RuntimeError("synthetic readback failure")), \
                self.assertRaisesRegex(
                    SCRATCH.StateInspectionRequired, "read back exactly"):
            SCRATCH.live_preflight(
                self.transaction, unreadable,
                backend_factory=forbidden_factory, progress=False)
        self.assertFalse(opened)
        self.assertEqual(
            real_load(unreadable)["status"], SCRATCH.PREFLIGHT_STARTED_STATUS)

    def test_preflight_visible_verified_boundary_is_authoritative(self) -> None:
        journal = self.journal_path("preflight-visible-boundary.json")
        session = FakeSession(
            self.transaction, 0, bytearray(self.baseline))
        real_write = SCRATCH.write_journal_atomic
        publication_count = 0

        def publish_final_then_error(*args, **kwargs):
            nonlocal publication_count
            publication_count += 1
            real_write(*args, **kwargs)
            if publication_count == 2:
                raise RuntimeError("synthetic visible preflight boundary")

        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=publish_final_then_error):
            result = SCRATCH.live_preflight(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: session,
                progress=False)

        self.assertEqual(result["boundary_index"], 0)
        self.assertTrue(session.closed)
        visible = SCRATCH.load_journal(journal)
        self.assertEqual(visible["status"], "boundary_verified")
        self.assertEqual(visible["boundary_index"], 0)

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

                    def final_factory(_transaction, _index):
                        started = SCRATCH.load_journal(journal)
                        self.assertEqual(
                            started["status"],
                            SCRATCH.FINAL_RECONCILE_STARTED_STATUS)
                        return final_session

                    finalized = SCRATCH.live_reconcile(
                        self.transaction, journal,
                        backend_factory=final_factory,
                        progress=False)
                    self.assertTrue(finalized["state_cleared"])
                    self.assertFalse(journal.exists())
                else:
                    self.assertEqual(
                        SCRATCH.load_journal(journal)["boundary_index"], index + 1)

    def test_mandatory_checkpoint_stops_after_csw_then_reconciles_fresh(self) -> None:
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
        ordering = mutation_session.events
        real_write_journal = SCRATCH.write_journal_atomic

        def observed_write_journal(*args, **kwargs):
            real_write_journal(*args, **kwargs)
            written = args[1]
            if written["status"] == "intent":
                ordering.append("intent_durable")
            elif written["status"] == SCRATCH.CHECKPOINT_READY_STATUS:
                ordering.append("checkpoint_ready_durable")

        def returned_terminator():
            ordering.append("sigkill")
            pending = SCRATCH.load_journal(journal)
            self.assertEqual(
                pending["status"], SCRATCH.CHECKPOINT_READY_STATUS)
            self.assertEqual(pending["boundary_index"], index)

        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=observed_write_journal), \
                self.assertRaisesRegex(
                    SCRATCH.ReconciliationRequired,
                    "only fresh-process read-only cleanup is authorized"):
            SCRATCH.live_step(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: mutation_session,
                progress=False, checkpoint_terminator=returned_terminator)

        self.assertEqual(mutation_session.capture_count, 2)
        self.assertEqual(mutation_session.execute_count, 1)
        self.assertEqual(mutation_session.wait_ready_count, 0)
        self.assertEqual(mutation_session.abandon_count, 1)
        self.assertEqual(mutation_session.close_count, 0)
        self.assertFalse(mutation_session.closed)
        self.assertEqual(
            ordering,
            [
                "intent_durable",
                "identity",
                "capture",
                "capture",
                "checkpoint_command_complete",
                "abandon_without_close",
                "checkpoint_ready_durable",
                "sigkill",
            ],
        )
        self.assertEqual(bytes(image), postimage)
        pending = SCRATCH.load_journal(journal)
        self.assertEqual(pending["status"], SCRATCH.CHECKPOINT_READY_STATUS)
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

        def reconcile_factory(_transaction, _index):
            started = SCRATCH.load_journal(journal)
            self.assertEqual(
                started["status"], SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)
            self.assertEqual(started["intent_process_nonce"], next_nonce)
            return reconcile_session

        with mock.patch.object(SCRATCH, "PROCESS_NONCE", next_nonce):
            reconciled = SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=reconcile_factory,
                progress=False)

        self.assertEqual(reconcile_session.capture_count, 2)
        self.assertEqual(reconcile_session.execute_count, 0)
        self.assertEqual(reconcile_session.wait_ready_count, 1)
        self.assertTrue(reconcile_session.closed)
        self.assertEqual(
            reconcile_session.events,
            ["identity", "wait_ready", "capture", "capture", "close"],
        )
        self.assertEqual(reconciled["classification"], "exact_postimage_completed")
        self.assertEqual(reconciled["boundary_index"], index + 1)
        self.assertEqual(reconciled["next_operation"], "program-10")
        self.assertFalse(reconciled["automatic_retry"])
        self.assertTrue(reconciled["fresh_process_wip_poll_completed"])
        verified = SCRATCH.load_journal(journal)
        self.assertEqual(verified["status"], "boundary_verified")
        self.assertEqual(verified["boundary_index"], index + 1)
        self.assertIsNone(verified["intent_process_nonce"])

    def test_planned_terminator_really_sigkills_its_process(self) -> None:
        script = (
            "import runpy\n"
            f"module = runpy.run_path({str(TOOL_PATH)!r})\n"
            "module['_planned_sigkill']()\n"
            "print('survived planned SIGKILL')\n"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            text=True, capture_output=True, check=False)

        self.assertEqual(
            completed.returncode, -int(SCRATCH.CHECKPOINT_SIGNAL))
        self.assertEqual(SCRATCH.CHECKPOINT_EXPECTED_SHELL_STATUS, 137)
        self.assertNotIn("survived", completed.stdout)
        self.assertEqual(completed.stderr, "")

        closed_stderr_script = (
            "import os, runpy\n"
            f"module = runpy.run_path({str(TOOL_PATH)!r})\n"
            "os.close(2)\n"
            "module['_planned_sigkill']()\n"
            "print('survived planned SIGKILL with closed stderr')\n"
        )
        closed_stderr = subprocess.run(
            [sys.executable, "-B", "-c", closed_stderr_script],
            text=True, capture_output=True, check=False)
        self.assertEqual(
            closed_stderr.returncode, -int(SCRATCH.CHECKPOINT_SIGNAL))
        self.assertNotIn("survived", closed_stderr.stdout)
        self.assertEqual(closed_stderr.stderr, "")

    def test_planned_terminator_failure_uses_126_never_137(self) -> None:
        class SyntheticExit(BaseException):
            def __init__(self, status: int) -> None:
                super().__init__(status)
                self.status = status

        def stop_process(status: int) -> None:
            raise SyntheticExit(status)

        for label, kill_error in (
                ("kill-returned", None),
                ("kill-raised", OSError("synthetic signal failure"))):
            with self.subTest(label=label):
                kill = mock.Mock(side_effect=kill_error)
                exit_process = mock.Mock(side_effect=stop_process)
                with mock.patch.object(SCRATCH.os, "kill", kill), \
                        mock.patch.object(SCRATCH.os, "_exit", exit_process), \
                        mock.patch.object(SCRATCH.os, "write") as write, \
                        self.assertRaises(SyntheticExit) as caught:
                    SCRATCH._planned_sigkill()

                self.assertEqual(
                    caught.exception.status,
                    SCRATCH.CHECKPOINT_TERMINATION_FAILURE_STATUS)
                self.assertEqual(caught.exception.status, 126)
                self.assertNotEqual(
                    caught.exception.status,
                    SCRATCH.CHECKPOINT_EXPECTED_SHELL_STATUS)
                kill.assert_called_once_with(
                    SCRATCH.os.getpid(), SCRATCH.CHECKPOINT_SIGNAL)
                exit_process.assert_called_once_with(126)
                write.assert_not_called()

    def test_checkpoint_fresh_process_poll_failure_keeps_intent(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        journal = self.journal_path("checkpoint-poll-failure.json")
        self.write_checkpoint_ready(journal)
        read_only = FakeSession(
            self.transaction, index, bytearray(postimage),
            fail_wait_ready=True, fail_close=True)

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "one-shot read-only reconciliation failed") as caught:
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertIn("ready-poll uncertainty", str(caught.exception.__cause__))
        self.assertEqual(read_only.wait_ready_count, 1)
        self.assertEqual(read_only.capture_count, 0)
        self.assertEqual(read_only.execute_count, 0)
        self.assertEqual(read_only.close_count, 0)
        self.assertEqual(read_only.events, ["identity", "wait_ready"])
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"],
            SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)

    def test_checkpoint_reconcile_constructor_failure_consumes_attempt(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        journal = self.journal_path("checkpoint-constructor-failure.json")
        self.write_checkpoint_ready(journal)

        def fail_constructor(_transaction, _index):
            raise RuntimeError("synthetic backend constructor failure")

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "one-shot read-only reconciliation failed") as caught:
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=fail_constructor, progress=False)

        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertIn("constructor failure", str(caught.exception.__cause__))
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"],
            SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)

    def test_reconcile_start_replace_then_error_is_terminal_before_usb(self) -> None:
        journal = self.journal_path("checkpoint-start-visible-error.json")
        self.write_checkpoint_ready(journal)
        real_write_journal = SCRATCH.write_journal_atomic
        opened = False

        def replace_then_error(*args, **kwargs):
            real_write_journal(*args, **kwargs)
            raise RuntimeError("synthetic post-replace start failure")

        def forbidden_factory(_transaction, _index):
            nonlocal opened
            opened = True
            raise AssertionError("backend must not open")

        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=replace_then_error), \
                self.assertRaisesRegex(
                    SCRATCH.RecoveryRequired,
                    "one-shot attempt is consumed"):
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=forbidden_factory, progress=False)

        self.assertFalse(opened)
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"],
            SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)

    def test_reconcile_start_publication_failure_with_source_retained_is_retryable(
            self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        journal = self.journal_path("checkpoint-reconcile-start-failure.json")
        self.write_checkpoint_ready(journal)
        opened = False

        def forbidden_factory(_transaction, _index):
            nonlocal opened
            opened = True
            raise AssertionError("backend must not open")

        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=RuntimeError(
                    "synthetic reconciliation-start publication failure")), \
                self.assertRaisesRegex(
                    SCRATCH.ReconciliationRequired,
                    "authorization was not consumed") as caught:
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=forbidden_factory, progress=False)

        self.assertFalse(opened)
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"],
            SCRATCH.CHECKPOINT_READY_STATUS)

    def test_checkpoint_final_publication_failure_is_terminal_after_clean_close(
            self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        journal = self.journal_path("checkpoint-final-publish-failure.json")
        self.write_checkpoint_ready(journal)
        read_only = FakeSession(
            self.transaction, index, bytearray(postimage))
        real_write_journal = SCRATCH.write_journal_atomic
        publication_count = 0

        def fail_final_publication(*args, **kwargs):
            nonlocal publication_count
            publication_count += 1
            if publication_count == 2:
                raise RuntimeError("synthetic final publication failure")
            return real_write_journal(*args, **kwargs)

        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=fail_final_publication), \
                self.assertRaisesRegex(
                    SCRATCH.RecoveryRequired,
                    "reconciled boundary was not published"):
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertEqual(read_only.wait_ready_count, 1)
        self.assertEqual(read_only.capture_count, 2)
        self.assertEqual(read_only.execute_count, 0)
        self.assertTrue(read_only.closed)
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"],
            SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)

    def test_checkpoint_final_publication_visible_target_is_authoritative(
            self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        journal = self.journal_path("checkpoint-final-visible-target.json")
        self.write_checkpoint_ready(journal)
        read_only = FakeSession(
            self.transaction, index, bytearray(postimage))
        real_write_journal = SCRATCH.write_journal_atomic
        publication_count = 0

        def publish_then_error(*args, **kwargs):
            nonlocal publication_count
            publication_count += 1
            real_write_journal(*args, **kwargs)
            if publication_count == 2:
                raise RuntimeError("synthetic visible final publication error")

        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=publish_then_error):
            result = SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertEqual(result["classification"], "exact_postimage_completed")
        self.assertEqual(result["boundary_index"], index + 1)
        self.assertTrue(read_only.closed)
        visible = SCRATCH.load_journal(journal)
        self.assertEqual(visible["status"], "boundary_verified")
        self.assertEqual(visible["boundary_index"], index + 1)

    def test_checkpoint_read_error_skips_close_and_preserves_cause(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        journal = self.journal_path("checkpoint-read-and-close-failure.json")
        self.write_checkpoint_ready(journal)
        read_only = FakeSession(
            self.transaction, index, bytearray(postimage),
            fail_capture=True, fail_close=True)

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "one-shot read-only reconciliation failed") as caught:
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertIn("read uncertainty", str(caught.exception.__cause__))
        self.assertEqual(read_only.wait_ready_count, 1)
        self.assertEqual(read_only.capture_count, 1)
        self.assertEqual(read_only.close_count, 0)
        self.assertNotIn("close", read_only.events)
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"],
            SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)

    def test_checkpoint_identity_error_maps_to_terminal_recovery(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        journal = self.journal_path("checkpoint-identity-failure.json")
        self.write_checkpoint_ready(journal)
        read_only = FakeSession(
            self.transaction, index, bytearray(postimage), fail_close=True)

        def fail_identity():
            raise SCRATCH.ReconciliationRequired(
                "synthetic injected reconciliation exception")

        read_only.identity = fail_identity
        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "one-shot read-only reconciliation failed") as caught:
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertIsInstance(
            caught.exception.__cause__, SCRATCH.ReconciliationRequired)
        self.assertEqual(read_only.close_count, 0)
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"],
            SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)

    def test_checkpoint_success_with_close_error_is_conservative(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        journal = self.journal_path("checkpoint-success-close-failure.json")
        self.write_checkpoint_ready(journal)
        read_only = FakeSession(
            self.transaction, index, bytearray(postimage), fail_close=True)

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "did not close cleanly") as caught:
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertIn("close uncertainty", str(caught.exception.__cause__))
        self.assertEqual(read_only.wait_ready_count, 1)
        self.assertEqual(read_only.capture_count, 2)
        self.assertEqual(read_only.execute_count, 0)
        terminal = SCRATCH.load_journal(journal)
        self.assertEqual(
            terminal["status"], SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)
        self.assertEqual(terminal["boundary_index"], index)

    def test_final_reconcile_close_failure_leaves_terminal_started_state(self) -> None:
        boundary = len(self.transaction.operations)
        journal = self.journal_path("final-reconcile-close-failure.json")
        self.write_boundary(journal, boundary)
        read_only = FakeSession(
            self.transaction, boundary - 1, bytearray(self.baseline),
            fail_close=True)

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired, "did not close cleanly"):
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertEqual(read_only.capture_count, 2)
        self.assertEqual(read_only.close_count, 1)
        terminal = SCRATCH.load_journal(journal)
        self.assertEqual(
            terminal["status"], SCRATCH.FINAL_RECONCILE_STARTED_STATUS)
        opened = False

        def forbidden_factory(_transaction, _index):
            nonlocal opened
            opened = True
            return read_only

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "one-shot reconciliation was already started"):
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=forbidden_factory, progress=False)
        self.assertFalse(opened)

    def test_final_clear_failure_leaves_started_state_after_clean_close(self) -> None:
        boundary = len(self.transaction.operations)
        journal = self.journal_path("final-reconcile-clear-failure.json")
        self.write_boundary(journal, boundary)
        read_only = FakeSession(
            self.transaction, boundary - 1, bytearray(self.baseline))

        with mock.patch.object(
                SCRATCH, "clear_journal",
                side_effect=RuntimeError("synthetic clear failure")), \
                self.assertRaisesRegex(
                    SCRATCH.RecoveryRequired,
                    "state clear did not clear") as caught:
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertTrue(read_only.closed)
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"],
            SCRATCH.FINAL_RECONCILE_STARTED_STATUS)

    def test_final_clear_visible_absence_is_authoritative(self) -> None:
        boundary = len(self.transaction.operations)
        journal = self.journal_path("final-reconcile-visible-clear.json")
        self.write_boundary(journal, boundary)
        read_only = FakeSession(
            self.transaction, boundary - 1, bytearray(self.baseline))
        real_clear_journal = SCRATCH.clear_journal

        def clear_then_error(path):
            real_clear_journal(path)
            raise RuntimeError("synthetic post-unlink clear error")

        with mock.patch.object(
                SCRATCH, "clear_journal", side_effect=clear_then_error):
            result = SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertTrue(read_only.closed)
        self.assertTrue(result["state_cleared"])
        self.assertEqual(result["classification"], "exact_stock_or_complete")
        self.assertFalse(journal.exists())

    def test_interrupt_after_final_clear_requires_local_inspection(self) -> None:
        boundary = len(self.transaction.operations)
        journal = self.journal_path("final-clear-then-interrupted.json")
        self.write_boundary(journal, boundary)
        read_only = FakeSession(
            self.transaction, boundary - 1, bytearray(self.baseline))
        real_clear = SCRATCH._clear_exact_transition

        def clear_then_interrupt(*args, **kwargs):
            real_clear(*args, **kwargs)
            raise KeyboardInterrupt()

        with mock.patch.object(
                SCRATCH, "_clear_exact_transition",
                side_effect=clear_then_interrupt), \
                self.assertRaisesRegex(
                    SCRATCH.StateInspectionRequired,
                    "interrupted after an atomic state transition"):
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: read_only,
                progress=False)

        self.assertTrue(read_only.closed)
        self.assertFalse(journal.exists())
        inspected = SCRATCH._inspection_result(self.transaction, None)
        self.assertEqual(
            inspected["permitted_next"], "preflight_dry_run_only")

    def test_checkpoint_execute_failure_skips_close_and_preserves_cause(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        journal = self.journal_path("checkpoint-execute-failure.json")
        self.write_boundary(journal, index)
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        failed_mutation = FakeSession(
            self.transaction, index, bytearray(preimage),
            fail_execute=True, fail_close=True)

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "checkpoint transport failed before a validated program CSW"
                ) as caught:
            SCRATCH.live_step(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: failed_mutation,
                progress=False)
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertIn(
            "synthetic mutation uncertainty", str(caught.exception.__cause__))
        self.assertEqual(failed_mutation.capture_count, 2)
        self.assertEqual(failed_mutation.execute_count, 1)
        self.assertEqual(failed_mutation.wait_ready_count, 0)
        self.assertEqual(failed_mutation.abandon_count, 0)
        self.assertEqual(failed_mutation.close_count, 0)
        self.assertFalse(failed_mutation.closed)
        self.assertEqual(
            failed_mutation.events,
            ["identity", "capture", "capture", "checkpoint_command_complete"],
        )
        self.assertEqual(SCRATCH.load_journal(journal)["status"], "intent")

    def test_checkpoint_exact_preimage_is_terminal_and_is_never_retried(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        journal = self.journal_path("checkpoint-preimage.json")
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        self.write_checkpoint_ready(journal)

        read_only = FakeSession(
            self.transaction, index, bytearray(preimage))
        stopped = SCRATCH.live_reconcile(
            self.transaction, journal,
            backend_factory=lambda _transaction, _index: read_only,
            progress=False)

        self.assertEqual(read_only.capture_count, 2)
        self.assertEqual(read_only.execute_count, 0)
        self.assertEqual(read_only.wait_ready_count, 1)
        self.assertTrue(read_only.closed)
        self.assertTrue(stopped["fresh_process_wip_poll_completed"])
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

        cli_journal = self.journal_path("checkpoint-preimage-cli.json")
        self.write_checkpoint_ready(cli_journal)
        argv = [
            str(TOOL_PATH), "reconcile",
            "--baseline-a", str(self.baseline_a),
            "--baseline-b", str(self.baseline_b),
            "--journal", str(cli_journal),
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

        opened = False

        def forbidden_reconcile(_transaction, _index):
            nonlocal opened
            opened = True
            return FakeSession(self.transaction, index, bytearray(preimage))

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired, "campaign is consumed"):
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=forbidden_reconcile, progress=False)
        self.assertFalse(opened)

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
        self.assertEqual(result, 3)
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
                "campaign is consumed; no further USB command"):
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

        with self.assertRaisesRegex(
                SCRATCH.StateInspectionRequired,
                "raw intent was not published"):
            SCRATCH.live_step(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: session,
                progress=False, journal_fault=stop_publication)
        self.assertEqual(session.capture_count, 0)
        self.assertEqual(session.execute_count, 0)
        self.assertEqual(
            SCRATCH.load_journal(journal)["boundary_index"], index)
        self.assertEqual(
            SCRATCH.load_journal(journal)["status"], "boundary_verified")

        ready_failure = self.journal_path("checkpoint-ready-failure.json")
        self.write_boundary(ready_failure, index)
        ready_session = FakeSession(
            self.transaction, index, bytearray(preimage))
        publication_count = 0

        def stop_ready_publication(_site):
            nonlocal publication_count
            publication_count += 1
            if publication_count == 2:
                raise RuntimeError("synthetic checkpoint-ready publication failure")

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "command-complete state was not published"):
            SCRATCH.live_step(
                self.transaction, ready_failure,
                backend_factory=lambda _transaction, _index: ready_session,
                progress=False, journal_fault=stop_ready_publication,
                checkpoint_terminator=mock.Mock())
        self.assertEqual(ready_session.execute_count, 1)
        self.assertEqual(ready_session.abandon_count, 1)
        self.assertEqual(ready_session.close_count, 0)
        self.assertEqual(
            SCRATCH.load_journal(ready_failure)["status"], "intent")

        visible_ready = self.journal_path("checkpoint-ready-visible-error.json")
        self.write_boundary(visible_ready, index)
        visible_session = FakeSession(
            self.transaction, index, bytearray(preimage))
        real_write_journal = SCRATCH.write_journal_atomic
        write_count = 0

        def publish_then_error(*args, **kwargs):
            nonlocal write_count
            write_count += 1
            real_write_journal(*args, **kwargs)
            if write_count == 2:
                raise RuntimeError("synthetic visible ready publication failure")

        terminator = mock.Mock()
        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=publish_then_error), \
                self.assertRaisesRegex(
                    SCRATCH.ReconciliationRequired,
                    "exact checkpoint command-complete state became visible"):
            SCRATCH.live_step(
                self.transaction, visible_ready,
                backend_factory=lambda _transaction, _index: visible_session,
                progress=False, checkpoint_terminator=terminator)
        visible = SCRATCH.load_journal(visible_ready)
        self.assertEqual(visible["status"], SCRATCH.CHECKPOINT_READY_STATUS)
        SCRATCH._require_reconcile_state(self.transaction, visible)
        self.assertEqual(visible_session.execute_count, 1)
        self.assertEqual(visible_session.close_count, 0)
        terminator.assert_not_called()

    def test_raw_intent_precedes_backend_and_preflight_failures_are_terminal(
            self) -> None:
        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)

        for name, factory_builder in (
                ("constructor", None),
                ("read", lambda: FakeSession(
                    self.transaction, index, bytearray(preimage),
                    fail_capture=True)),
                ("unstable", lambda: FakeSession(
                    self.transaction, index, bytearray(preimage),
                    capture_sequence=[preimage, bytes(
                        bytearray(preimage[:-1]) +
                        bytes([preimage[-1] ^ 0x01]))])),
        ):
            with self.subTest(name=name):
                journal = self.journal_path(f"armed-before-{name}.json")
                self.write_boundary(journal, index)
                opened = False
                session = None if factory_builder is None else factory_builder()

                def factory(_transaction, _index):
                    nonlocal opened
                    opened = True
                    armed = SCRATCH.load_journal(journal)
                    self.assertEqual(armed["status"], "intent")
                    self.assertEqual(armed["boundary_index"], index)
                    if session is None:
                        raise RuntimeError("synthetic constructor failure")
                    return session

                with self.assertRaisesRegex(
                        SCRATCH.RecoveryRequired,
                        "stopped after durable intent"):
                    SCRATCH.live_step(
                        self.transaction, journal,
                        backend_factory=factory, progress=False)

                self.assertTrue(opened)
                terminal = SCRATCH.load_journal(journal)
                self.assertEqual(terminal["status"], "intent")
                self.assertEqual(terminal["boundary_index"], index)
                if session is not None:
                    self.assertEqual(session.close_count, 0)

    def test_atomic_publication_readback_ambiguity_is_inspection_only(
            self) -> None:
        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)

        for name, writer_side_effect in (
                ("source", RuntimeError("synthetic pre-replace failure")),
                ("target", None),
        ):
            with self.subTest(name=name):
                journal = self.journal_path(f"ambiguous-intent-{name}.json")
                self.write_boundary(journal, index)
                opened = False
                real_load = SCRATCH.load_journal
                load_count = 0

                def fail_publication_readback(path):
                    nonlocal load_count
                    load_count += 1
                    if load_count == 2:
                        raise RuntimeError("synthetic journal readback failure")
                    return real_load(path)

                def forbidden_factory(_transaction, _index):
                    nonlocal opened
                    opened = True
                    raise AssertionError("ambiguous state must not open USB")

                writer_patch = (
                    mock.patch.object(
                        SCRATCH, "write_journal_atomic",
                        side_effect=writer_side_effect)
                    if writer_side_effect is not None else nullcontext())
                with writer_patch, mock.patch.object(
                        SCRATCH, "load_journal",
                        side_effect=fail_publication_readback), \
                        self.assertRaisesRegex(
                            SCRATCH.StateInspectionRequired,
                            "read back exactly|fresh process"):
                    SCRATCH.live_step(
                        self.transaction, journal,
                        backend_factory=forbidden_factory, progress=False)

                self.assertFalse(opened)
                visible = real_load(journal)
                self.assertEqual(
                    visible["status"],
                    "boundary_verified" if name == "source" else "intent")

    def test_interrupt_after_authorizing_publication_requires_inspection(
            self) -> None:
        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        journal = self.journal_path("boundary-published-then-interrupted.json")
        self.write_boundary(journal, index)
        session = FakeSession(self.transaction, index, bytearray(preimage))
        real_publish = SCRATCH._publish_exact_transition

        def publish_then_interrupt(*args, **kwargs):
            outcome = real_publish(*args, **kwargs)
            target = args[3]
            if target["status"] == "boundary_verified":
                raise KeyboardInterrupt()
            return outcome

        with mock.patch.object(
                SCRATCH, "_publish_exact_transition",
                side_effect=publish_then_interrupt), \
                self.assertRaisesRegex(
                    SCRATCH.StateInspectionRequired,
                    "interrupted after an atomic state transition"):
            SCRATCH.live_step(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: session,
                progress=False)

        self.assertTrue(session.closed)
        visible = SCRATCH.load_journal(journal)
        self.assertEqual(visible["status"], "boundary_verified")
        self.assertEqual(visible["boundary_index"], index + 1)

    def test_interrupt_after_checkpoint_ready_publication_requires_inspection(
            self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        journal = self.journal_path("ready-published-then-interrupted.json")
        self.write_boundary(journal, index)
        session = FakeSession(self.transaction, index, bytearray(preimage))
        terminator = mock.Mock()
        real_publish = SCRATCH._publish_exact_transition

        def publish_then_interrupt(*args, **kwargs):
            outcome = real_publish(*args, **kwargs)
            target = args[3]
            if target["status"] == SCRATCH.CHECKPOINT_READY_STATUS:
                raise KeyboardInterrupt()
            return outcome

        with mock.patch.object(
                SCRATCH, "_publish_exact_transition",
                side_effect=publish_then_interrupt), \
                self.assertRaisesRegex(
                    SCRATCH.StateInspectionRequired,
                    "interrupted after an atomic state transition"):
            SCRATCH.live_step(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: session,
                progress=False, checkpoint_terminator=terminator)

        self.assertEqual(session.execute_count, 1)
        self.assertEqual(session.abandon_count, 1)
        self.assertEqual(session.close_count, 0)
        terminator.assert_not_called()
        visible = SCRATCH.load_journal(journal)
        self.assertEqual(visible["status"], SCRATCH.CHECKPOINT_READY_STATUS)
        self.assertEqual(visible["boundary_index"], index)

    def test_interrupt_after_reconciled_boundary_publication_requires_inspection(
            self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        postimage = SCRATCH.expected_boundary_image(self.transaction, index + 1)
        journal = self.journal_path(
            "reconciled-boundary-published-then-interrupted.json")
        self.write_checkpoint_ready(journal)
        session = FakeSession(
            self.transaction, index, bytearray(postimage))
        real_publish = SCRATCH._publish_exact_transition

        def publish_then_interrupt(*args, **kwargs):
            outcome = real_publish(*args, **kwargs)
            target = args[3]
            if (target["status"] == "boundary_verified" and
                    target["boundary_index"] == index + 1):
                raise KeyboardInterrupt()
            return outcome

        with mock.patch.object(
                SCRATCH, "_publish_exact_transition",
                side_effect=publish_then_interrupt), \
                self.assertRaisesRegex(
                    SCRATCH.StateInspectionRequired,
                    "interrupted after an atomic state transition"):
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=lambda _transaction, _index: session,
                progress=False)

        self.assertTrue(session.closed)
        visible = SCRATCH.load_journal(journal)
        self.assertEqual(visible["status"], "boundary_verified")
        self.assertEqual(visible["boundary_index"], index + 1)

    def test_reconcile_start_readback_ambiguity_never_opens_usb(self) -> None:
        journal = self.journal_path("reconcile-start-readback-ambiguity.json")
        self.write_checkpoint_ready(journal)
        real_load = SCRATCH.load_journal
        load_count = 0
        opened = False

        def fail_started_readback(path):
            nonlocal load_count
            load_count += 1
            if load_count == 2:
                raise RuntimeError("synthetic started-state readback failure")
            return real_load(path)

        def forbidden_factory(_transaction, _index):
            nonlocal opened
            opened = True
            raise AssertionError("ambiguous reconciliation must not open USB")

        with mock.patch.object(
                SCRATCH, "load_journal", side_effect=fail_started_readback), \
                self.assertRaisesRegex(
                    SCRATCH.StateInspectionRequired, "read back exactly"):
            SCRATCH.live_reconcile(
                self.transaction, journal,
                backend_factory=forbidden_factory, progress=False)

        self.assertFalse(opened)
        visible = real_load(journal)
        self.assertEqual(
            visible["status"], SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)

    def test_exact_absence_never_conflates_filesystem_errors(self) -> None:
        path = self.journal_path("absence-inspection.json")
        with mock.patch.object(
                Path, "lstat", side_effect=PermissionError("synthetic lstat")), \
                self.assertRaisesRegex(
                    SCRATCH.StateInspectionRequired,
                    "could not distinguish absence"):
            SCRATCH._path_is_exactly_absent(path, label="test absence")

    def test_ordinary_transport_or_verification_failure_requires_spi(self) -> None:
        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        for name, session in (
                ("transport", FakeSession(
                    self.transaction, index, bytearray(preimage),
                    fail_execute=True, fail_close=True)),
                ("postread", FakeSession(
                    self.transaction, index, bytearray(preimage),
                    capture_sequence=[preimage, preimage, preimage, preimage],
                    fail_close=True)),
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
                with self.assertRaisesRegex(
                        SCRATCH.RecoveryRequired,
                        "transport or exact verification failed") as caught:
                    SCRATCH.live_step(
                        self.transaction, journal,
                        backend_factory=lambda _transaction, _index: session,
                        progress=False)
                self.assertIsNotNone(caught.exception.__cause__)
                if name == "transport":
                    self.assertIn(
                        "synthetic mutation uncertainty",
                        str(caught.exception.__cause__))
                else:
                    self.assertIn(
                        "scratch step postimage", str(caught.exception.__cause__))
                self.assertEqual(session.execute_count, 1)
                self.assertEqual(session.close_count, 0)
                self.assertFalse(session.closed)
                self.assertEqual(SCRATCH.load_journal(journal)["status"], "intent")

    def test_intent_publication_and_close_failures_never_expand_authority(self) -> None:
        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)

        before_intent = self.journal_path("before-intent-failure.json")
        self.write_boundary(before_intent, index)
        session = FakeSession(self.transaction, index, bytearray(preimage))

        def stop_publication(_site):
            raise RuntimeError("synthetic journal publication failure")

        with self.assertRaisesRegex(
                SCRATCH.StateInspectionRequired,
                "raw intent was not published"):
            SCRATCH.live_step(
                self.transaction, before_intent,
                backend_factory=lambda _transaction, _index: session,
                progress=False, journal_fault=stop_publication)
        self.assertEqual(session.execute_count, 0)
        self.assertEqual(
            SCRATCH.load_journal(before_intent)["boundary_index"], index)

        after_verification = self.journal_path(
            "verified-image-journal-failure.json")
        self.write_boundary(after_verification, index)
        verified_session = FakeSession(
            self.transaction, index, bytearray(preimage))
        publication_count = 0

        def stop_verified_publication(_site):
            nonlocal publication_count
            publication_count += 1
            if publication_count == 2:
                raise RuntimeError("synthetic verified journal publication failure")

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "verified boundary was not published"):
            SCRATCH.live_step(
                self.transaction, after_verification,
                backend_factory=lambda _transaction, _index: verified_session,
                progress=False, journal_fault=stop_verified_publication)
        self.assertEqual(verified_session.capture_count, 4)
        self.assertEqual(verified_session.execute_count, 1)
        self.assertEqual(verified_session.close_count, 1)
        self.assertTrue(verified_session.closed)
        self.assertEqual(
            SCRATCH.load_journal(after_verification)["status"], "intent")

        opened = False

        def forbidden_reconcile(_transaction, _index):
            nonlocal opened
            opened = True
            return FakeSession(
                self.transaction, index, bytearray(preimage))

        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired,
                "raw operation intent"):
            SCRATCH.live_reconcile(
                self.transaction, after_verification,
                backend_factory=forbidden_reconcile, progress=False)
        self.assertFalse(opened)

        visible_boundary = self.journal_path(
            "verified-image-visible-boundary.json")
        self.write_boundary(visible_boundary, index)
        visible_session = FakeSession(
            self.transaction, index, bytearray(preimage))
        real_write_journal = SCRATCH.write_journal_atomic
        visible_publication_count = 0

        def publish_boundary_then_error(*args, **kwargs):
            nonlocal visible_publication_count
            visible_publication_count += 1
            real_write_journal(*args, **kwargs)
            if visible_publication_count == 2:
                raise RuntimeError("synthetic visible boundary publication error")

        with mock.patch.object(
                SCRATCH, "write_journal_atomic",
                side_effect=publish_boundary_then_error):
            result = SCRATCH.live_step(
                self.transaction, visible_boundary,
                backend_factory=lambda _transaction, _index: visible_session,
                progress=False)

        self.assertEqual(result["boundary_index"], index + 1)
        self.assertTrue(visible_session.closed)
        visible = SCRATCH.load_journal(visible_boundary)
        self.assertEqual(visible["status"], "boundary_verified")
        self.assertEqual(visible["boundary_index"], index + 1)

        after_intent = self.journal_path("close-failure.json")
        self.write_boundary(after_intent, index)
        closing = FakeSession(
            self.transaction, index, bytearray(preimage), fail_close=True)
        with self.assertRaisesRegex(
                SCRATCH.RecoveryRequired, "did not close cleanly") as caught:
            SCRATCH.live_step(
                self.transaction, after_intent,
                backend_factory=lambda _transaction, _index: closing,
                progress=False)
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertIn("close uncertainty", str(caught.exception.__cause__))
        self.assertEqual(closing.execute_count, 1)
        self.assertTrue(closing.closed)
        closing_journal = SCRATCH.load_journal(after_intent)
        self.assertEqual(closing_journal["status"], "intent")
        self.assertEqual(closing_journal["boundary_index"], index)

    def test_ordinary_intent_reconciliation_is_prohibited_before_usb(self) -> None:
        for index in range(len(self.transaction.operations)):
            with self.subTest(index=index):
                preimage = SCRATCH.expected_boundary_image(
                    self.transaction, index)
                journal = self.journal_path(f"raw-intent-{index}.json")
                SCRATCH.write_journal_atomic(
                    journal,
                    SCRATCH.intent_journal(
                        self.transaction, self.identity(preimage), index,
                        process_nonce=self.other_process_nonce()),
                    require_absent=True)
                opened = False

                def forbidden_factory(_transaction, _index):
                    nonlocal opened
                    opened = True
                    return FakeSession(
                        self.transaction, index, bytearray(preimage))

                with self.assertRaisesRegex(
                        SCRATCH.RecoveryRequired,
                        "raw operation intent"):
                    SCRATCH.live_reconcile(
                        self.transaction, journal,
                        backend_factory=forbidden_factory, progress=False)
                self.assertFalse(opened)
                self.assertEqual(
                    SCRATCH.load_journal(journal)["status"], "intent")

        index = 10
        preimage = SCRATCH.expected_boundary_image(self.transaction, index)
        cli_journal = self.journal_path("ordinary-intent-cli.json")
        SCRATCH.write_journal_atomic(
            cli_journal,
            SCRATCH.intent_journal(
                self.transaction, self.identity(preimage), index,
                process_nonce=self.other_process_nonce()),
            require_absent=True)
        for command in ("step", "reconcile"):
            with self.subTest(command=command):
                argv = [
                    str(TOOL_PATH), command,
                    "--baseline-a", str(self.baseline_a),
                    "--baseline-b", str(self.baseline_b),
                    "--journal", str(cli_journal),
                ]
                stderr = io.StringIO()
                with mock.patch.object(sys, "argv", argv), \
                        mock.patch.object(SCRATCH, "live_step") as live_step, \
                        mock.patch.object(
                            SCRATCH, "live_reconcile") as live_reconcile, \
                        mock.patch.object(
                            SCRATCH._writer._verify,
                            "_load_libusb") as load_libusb, \
                        redirect_stdout(io.StringIO()), \
                        redirect_stderr(stderr):
                    result = SCRATCH.main()
                self.assertEqual(result, 3)
                live_step.assert_not_called()
                live_reconcile.assert_not_called()
                load_libusb.assert_not_called()
                self.assertIn("raw operation intent", stderr.getvalue())

        boundary_journal = self.journal_path("intermediate-boundary.json")
        self.write_boundary(boundary_journal, index)
        opened = False

        def forbidden_boundary_factory(_transaction, _index):
            nonlocal opened
            opened = True
            raise AssertionError("intermediate reconcile must not open USB")

        with self.assertRaisesRegex(
                SCRATCH.ScratchExecutorError,
                "intermediate verified boundaries are not reconcilable"):
            SCRATCH.live_reconcile(
                self.transaction, boundary_journal,
                backend_factory=forbidden_boundary_factory, progress=False)
        self.assertFalse(opened)

    def test_reconcile_rejects_partial_unstable_and_outside_damage(self) -> None:
        index = SCRATCH.CHECKPOINT_OPERATION_INDEX
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
                self.write_checkpoint_ready(journal)
                session = FakeSession(
                    self.transaction, index, bytearray(images[0]),
                    capture_sequence=images)
                with self.assertRaises(SCRATCH.RecoveryRequired):
                    SCRATCH.live_reconcile(
                        self.transaction, journal,
                        backend_factory=lambda _transaction, _index: session,
                        progress=False)
                self.assertEqual(session.execute_count, 0)
                self.assertEqual(
                    SCRATCH.load_journal(journal)["status"],
                    SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS)

    def test_journal_domain_tamper_paths_and_publish_are_fail_closed(self) -> None:
        journal = self.journal_path("strict.json")
        self.write_boundary(journal, 0)
        value = SCRATCH.load_journal(journal)
        self.assertEqual(
            SCRATCH.JOURNAL_SCHEMA, "kb7-usb-updater-scratch-journal-v3")
        for key, changed in (
                ("plan_sha256", "00" * 32),
                ("boundary_index", 3),
                ("schema", "kb7-usb-updater-scratch-journal-v1"),
                ("schema", "kb7-usb-updater-scratch-journal-v2"),
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

    def test_step_dry_run_validates_state_and_declares_fixed_sigkill(self) -> None:
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
        self.assertEqual(result, 3)
        live.assert_not_called()
        load_libusb.assert_not_called()
        self.assertIn("raw operation intent", stderr.getvalue())

        ready = self.journal_path("dry-run-command-complete.json")
        self.write_checkpoint_ready(ready)
        argv[-1] = str(ready)
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(SCRATCH, "live_step") as live, \
                mock.patch.object(
                    SCRATCH._writer._verify, "_load_libusb") as load_libusb, \
                redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            result = SCRATCH.main()
        self.assertEqual(result, 4)
        live.assert_not_called()
        load_libusb.assert_not_called()
        self.assertIn("requires fresh-process", stderr.getvalue())
        self.assertIn("reconcile --commit", stderr.getvalue())

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
        self.assertIn(SCRATCH.CHECKPOINT_POLICY, stdout.getvalue())
        self.assertIn("no USB device was opened", stdout.getvalue())
        self.assertEqual(SCRATCH.CHECKPOINT_TERMINATION, "self_sigkill")
        self.assertEqual(int(SCRATCH.CHECKPOINT_SIGNAL), 9)
        self.assertEqual(SCRATCH.CHECKPOINT_EXPECTED_SHELL_STATUS, 137)
        self.assertEqual(SCRATCH.CHECKPOINT_TERMINATION_FAILURE_STATUS, 126)

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
        for command in (None, "preflight", "step", "reconcile", "inspect"):
            arguments = [sys.executable, str(TOOL_PATH)]
            if command is not None:
                arguments.append(command)
            arguments.append("--help")
            help_result = subprocess.run(
                arguments, text=True, capture_output=True, check=False)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            help_outputs.append(help_result.stdout.lower())
        self.assertIn("{preflight,step,reconcile,inspect}", help_outputs[0])
        for output in help_outputs:
            for forbidden in (
                    "--offset", "--cdb", "--payload", "--operation",
                    "--bundle", "--force", "--retry", "--device"):
                self.assertNotIn(forbidden, output)
        self.assertNotIn("--commit", help_outputs[-1])
        self.assertFalse(FIRMWARE.LIVE_MUTATION_ENABLED)

    def test_inspect_is_local_only_and_reports_exact_state_authority(self) -> None:
        checkpoint_index = SCRATCH.CHECKPOINT_OPERATION_INDEX
        checkpoint_image = SCRATCH.expected_boundary_image(
            self.transaction, checkpoint_index)
        ready = SCRATCH.intent_journal(
            self.transaction, self.identity(checkpoint_image), checkpoint_index,
            process_nonce=self.other_process_nonce())
        ready["status"] = SCRATCH.CHECKPOINT_READY_STATUS
        checkpoint_started = dict(ready)
        checkpoint_started["status"] = SCRATCH.CHECKPOINT_RECONCILE_STARTED_STATUS
        no_effect = dict(ready)
        no_effect["status"] = "checkpoint_no_effect"
        complete = SCRATCH.boundary_journal(
            self.transaction, self.identity(self.baseline),
            len(self.transaction.operations))
        final_started = dict(complete)
        final_started["status"] = SCRATCH.FINAL_RECONCILE_STARTED_STATUS
        cases: list[tuple[str, dict[str, object] | None, str]] = [
            ("absent", None, "preflight_dry_run_only"),
            (
                "boundary",
                SCRATCH.boundary_journal(
                    self.transaction, self.identity(self.baseline), 0),
                "step_dry_run",
            ),
            (
                "preflight-started",
                SCRATCH.preflight_started_journal(self.transaction),
                "external_spi_no_usb",
            ),
            (
                "raw-intent",
                SCRATCH.intent_journal(
                    self.transaction, self.identity(self.baseline), 0),
                "external_spi_no_usb",
            ),
            ("checkpoint-ready", ready, "reconcile_dry_run"),
            (
                "checkpoint-reconcile-started", checkpoint_started,
                "external_spi_no_usb",
            ),
            ("checkpoint-no-effect", no_effect, "external_spi_no_usb"),
            ("complete", complete, "reconcile_dry_run"),
            (
                "final-reconcile-started", final_started,
                "external_spi_no_usb",
            ),
        ]
        for name, value, expected_next in cases:
            with self.subTest(name=name):
                journal = self.journal_path(f"inspect-{name}.json")
                if value is not None:
                    SCRATCH.write_journal_atomic(
                        journal, value, require_absent=True)
                argv = [
                    str(TOOL_PATH), "inspect",
                    "--baseline-a", str(self.baseline_a),
                    "--baseline-b", str(self.baseline_b),
                    "--journal", str(journal),
                ]
                stdout = io.StringIO()
                with mock.patch.object(sys, "argv", argv), \
                        mock.patch.object(
                            SCRATCH._writer._verify,
                            "_load_libusb") as load_libusb, \
                        redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    result = SCRATCH.main()
                self.assertEqual(result, 0)
                load_libusb.assert_not_called()
                self.assertIn('"usb_opened": false', stdout.getvalue())
                self.assertIn(
                    f'"permitted_next": "{expected_next}"',
                    stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
