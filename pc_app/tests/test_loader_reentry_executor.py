from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = (
    ROOT / "tools" / "flash-access" / "kb7-loader-reentry-executor.py")
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


EXECUTOR = load_module("kb7_loader_reentry_executor_tested", EXECUTOR_PATH)
PLAN_TEST = load_module("kb7_updater_plan_fixture_for_executor", PLAN_TEST_PATH)
PLANNER = EXECUTOR._planner


class FakeState:
    def __init__(self, image: bytes, *, address: int = 10) -> None:
        self.image = bytearray(image)
        self.address = address
        self.events: list[str] = []
        self.execute_count = 0
        self.close_count = 0
        self.fail_at: str | None = None

    def identity(self) -> dict[str, object]:
        return {
            "device_path": "3-2.2",
            "identify_hex": EXECUTOR._writer.LOADER_IDENT.hex(),
            "descriptor_sha256": "1" * 64,
            "loader_fingerprint_sha256": "2" * 64,
            "usb_bus_number": 3,
            "usb_device_address": self.address,
        }


class FakeReadBackend:
    def __init__(self, _transaction: object, state: FakeState) -> None:
        self.state = state
        self.capture_count = 0
        state.events.append("open_read")
        if state.fail_at == "constructor":
            raise RuntimeError("constructor fault")

    def identity(self) -> dict[str, object]:
        self.state.events.append("identity")
        if self.state.fail_at == "identity":
            raise RuntimeError("identity fault")
        return self.state.identity()

    def capture(self, *, progress: bool = True) -> bytes:
        del progress
        self.capture_count += 1
        self.state.events.append(f"capture_{self.capture_count}")
        if self.state.fail_at == f"capture_{self.capture_count}":
            raise RuntimeError("capture fault")
        return bytes(self.state.image)

    def close(self) -> None:
        self.state.events.append("close")
        self.state.close_count += 1
        if self.state.fail_at == "close":
            raise RuntimeError("close fault")


class FakeMutationBackend(FakeReadBackend):
    def __init__(self, transaction: object, index: int, state: FakeState) -> None:
        self.transaction = transaction
        self.index = index
        super().__init__(transaction, state)
        state.events[-1] = "open_mutation"

    def execute(self) -> None:
        self.state.events.append("execute")
        self.state.execute_count += 1
        if self.state.fail_at == "execute":
            raise RuntimeError("execute fault")
        PLANNER.apply_operation(
            self.state.image, self.transaction.operations[self.index])


class LoaderReentryExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(
            prefix="kb7-loader-reentry-executor-tests-")
        cls.root = Path(cls._temporary.name)
        cls.baseline, cls.anchors = PLAN_TEST.synthetic_baseline()
        cls.baseline_a = cls.root / "baseline-a.bin"
        cls.baseline_b = cls.root / "baseline-b.bin"
        cls.baseline_a.write_bytes(cls.baseline)
        cls.baseline_b.write_bytes(cls.baseline)
        cls.proof_elf = cls.root / "proof-core0.elf"
        cls.proof_elf.write_bytes(b"synthetic proof ELF")
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
        EXECUTOR._campaign.build_campaign(
            cls.baseline_a, cls.baseline_b, cls.proof_elf,
            cls.campaign_dir, "unused-", anchors=cls.anchors,
            proof_identity=cls.proof_identity, extractor=cls.extractor)
        cls.transaction = EXECUTOR.load_transaction(
            cls.campaign_dir, cls.baseline_a, cls.baseline_b,
            cls.proof_elf, "unused-", anchors=cls.anchors,
            proof_identity=cls.proof_identity, extractor=cls.extractor)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def setUp(self) -> None:
        self.case = Path(tempfile.mkdtemp(
            prefix="case-", dir=self.root))
        self.journal = self.case / "kb7-loader-reentry-proof-journal.json"

    def identity(self, *, address: int = 10,
                 initial_address: int | None = None) -> dict[str, object]:
        state = FakeState(self.baseline, address=address)
        return EXECUTOR._bound_identity(
            state.identity(), self.baseline, initial_address=initial_address)

    def write_boundary(self, index: int, *, status: str | None = None,
                       address: int | None = None) -> dict[str, object]:
        if address is None:
            address = (11 if status == EXECUTOR.RESTORE_READY or
                       index > self.transaction.install_count else 10)
        identity = self.identity(address=address, initial_address=10)
        journal = EXECUTOR.boundary_journal(
            self.transaction, identity, index, status=status)
        EXECUTOR.write_journal_atomic(self.journal, journal, require_absent=True)
        return journal

    @staticmethod
    def fault_on_occurrence(site: str, wanted: int):
        seen = 0

        def fault(actual: str) -> None:
            nonlocal seen
            if actual == site:
                seen += 1
                if seen == wanted:
                    raise RuntimeError(f"{site} publication fault {wanted}")

        return fault

    def test_exact_proof_campaign_is_live_enabled_and_general_executor_stays_locked(self) -> None:
        self.assertTrue(EXECUTOR.LIVE_PROOF_CAMPAIGN_ENABLED)
        self.assertEqual(
            EXECUTOR.EXPECTED_CAMPAIGN_ID,
            "3fa076a69bb04ab2ef11c9369d80976e293d1d57a52ddeb63f9d8d71b004d82f")
        self.assertEqual(EXECUTOR.EXPECTED_IMPLEMENTATION_HASHES,
                         dict(EXECUTOR.IMPLEMENTATION_HASHES))
        self.assertEqual(EXECUTOR.EXPECTED_POLICY_SHA256,
                         EXECUTOR._policy_sha256())
        self.assertEqual(EXECUTOR.EXPECTED_EXECUTOR_DESCRIPTOR_SHA256,
                         EXECUTOR._executor_descriptor_sha256())
        reviewed = mock.Mock(campaign_id=EXECUTOR.EXPECTED_CAMPAIGN_ID)
        EXECUTOR.require_live_authorization(reviewed)
        with self.assertRaises(EXECUTOR.ExecutionLocked):
            EXECUTOR.require_live_authorization(self.transaction)
        general = (ROOT / "tools/flash-access/kb7-updater-executor.py").read_text()
        self.assertIn("LIVE_MUTATION_ENABLED = False", general)
        self.assertNotIn("--commit", general)
        self.assertFalse(
            EXECUTOR.FixedProofNoRecoveryReadOnlyDevice.clear_halt_on_error)
        self.assertTrue(issubclass(
            EXECUTOR.FixedProofStrictWriteDevice,
            EXECUTOR._writer.WriteDevice))
        self.assertTrue(issubclass(
            EXECUTOR.FixedProofNoRecoveryReadOnlyDevice,
            EXECUTOR._writer._verify.Device))

    def test_usb_enumeration_address_is_added_only_by_the_fixed_proof_device(self) -> None:
        class ParentDevice:
            def __init__(self) -> None:
                self.device_path = "3-2.2"
                self.h = object()

        class ProofDevice(EXECUTOR._ProofUsbEnumerationMixin, ParentDevice):
            pass

        api = mock.Mock()
        api.libusb_get_device.return_value = object()
        api.libusb_get_device_address.return_value = 17
        with mock.patch.object(EXECUTOR._writer._verify, "lib", api):
            device = ProofDevice()
        self.assertEqual(device.bus_number, 3)
        self.assertEqual(device.device_address, 17)
        api.libusb_get_device.assert_called_once_with(device.h)
        api.libusb_get_device_address.assert_called_once_with(
            api.libusb_get_device.return_value)
        shared_verifier = (
            ROOT / "tools/flash-access/kb7-isp-verify.py").read_text(
                encoding="utf-8")
        self.assertNotIn("libusb_get_device_address", shared_verifier)

    def test_preflight_publishes_terminal_start_before_usb_then_exact_boundary(self) -> None:
        state = FakeState(self.baseline)

        def factory(transaction: object):
            visible = EXECUTOR.load_journal(self.journal)
            self.assertEqual(visible["status"], EXECUTOR.PREFLIGHT_STARTED)
            return FakeReadBackend(transaction, state)

        result = EXECUTOR.live_preflight(
            self.transaction, self.journal, backend_factory=factory,
            progress=False)
        self.assertEqual(result["status"], EXECUTOR.BOUNDARY_VERIFIED)
        self.assertEqual(result["boundary_index"], 0)
        self.assertEqual(
            state.events,
            ["open_read", "identity", "capture_1", "capture_2", "close"])

    def test_preflight_faults_retain_terminal_marker_and_never_retry_usb(self) -> None:
        for fault in ("constructor", "identity", "capture_1", "capture_2",
                      "close"):
            with self.subTest(fault=fault):
                path = self.case / f"preflight-{fault}.json"
                state = FakeState(self.baseline)
                state.fail_at = fault
                with self.assertRaises(EXECUTOR.RecoveryRequired):
                    EXECUTOR.live_preflight(
                        self.transaction, path,
                        backend_factory=lambda transaction: FakeReadBackend(
                            transaction, state), progress=False)
                visible = EXECUTOR.load_journal(path)
                self.assertEqual(visible["status"], EXECUTOR.PREFLIGHT_STARTED)
                self.assertEqual(state.close_count, 1 if fault == "close" else 0)
                self.assertEqual(
                    EXECUTOR.inspect_state(self.transaction, path)["permitted_next"],
                    "external_spi_only")
                opened = 0

                def must_not_open(_transaction: object):
                    nonlocal opened
                    opened += 1
                    raise AssertionError("terminal preflight must not reopen USB")

                with self.assertRaises(EXECUTOR.ExecutorError):
                    EXECUTOR.live_preflight(
                        self.transaction, path, backend_factory=must_not_open,
                        progress=False)
                self.assertEqual(opened, 0)

    def test_preflight_atomic_publication_outcomes_never_open_usb_early(self) -> None:
        for site, expected in (("before_replace", "absent"),
                               ("after_replace", EXECUTOR.PREFLIGHT_STARTED)):
            with self.subTest(site=site):
                path = self.case / f"preflight-initial-{site}.json"
                opened = 0

                def factory(_transaction: object):
                    nonlocal opened
                    opened += 1
                    raise AssertionError("USB must not open")

                with self.assertRaises(EXECUTOR.StateInspectionRequired):
                    EXECUTOR.live_preflight(
                        self.transaction, path, backend_factory=factory,
                        progress=False,
                        journal_fault=self.fault_on_occurrence(site, 1))
                self.assertEqual(opened, 0)
                if expected == "absent":
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(
                        EXECUTOR.load_journal(path)["status"], expected)

        for site, exception, status in (
                ("before_replace", EXECUTOR.RecoveryRequired,
                 EXECUTOR.PREFLIGHT_STARTED),
                ("after_replace", EXECUTOR.StateInspectionRequired,
                 EXECUTOR.BOUNDARY_VERIFIED)):
            with self.subTest(final_site=site):
                path = self.case / f"preflight-final-{site}.json"
                state = FakeState(self.baseline)
                with self.assertRaises(exception):
                    EXECUTOR.live_preflight(
                        self.transaction, path,
                        backend_factory=lambda transaction: FakeReadBackend(
                            transaction, state), progress=False,
                        journal_fault=self.fault_on_occurrence(site, 2))
                self.assertEqual(state.close_count, 1)
                self.assertEqual(EXECUTOR.load_journal(path)["status"], status)

    def test_one_step_publishes_intent_before_usb_and_executes_one_operation(self) -> None:
        self.write_boundary(0)
        state = FakeState(self.baseline)

        def factory(transaction: object, index: int):
            visible = EXECUTOR.load_journal(self.journal)
            self.assertEqual(visible["status"], EXECUTOR.INTENT)
            self.assertEqual(visible["active_operation_index"], index)
            return FakeMutationBackend(transaction, index, state)

        result = EXECUTOR.live_step(
            self.transaction, self.journal, backend_factory=factory,
            progress=False)
        self.assertEqual(result["boundary_index"], 1)
        self.assertEqual(state.execute_count, 1)
        self.assertEqual(
            state.events,
            ["open_mutation", "identity", "capture_1", "capture_2",
             "execute", "capture_3", "capture_4", "close"])
        self.assertEqual(
            bytes(state.image), EXECUTOR.expected_boundary_image(
                self.transaction, 1))

    def test_every_operation_stays_in_fixed_ranges_and_builds_exact_commands(self) -> None:
        class Device:
            def __init__(self) -> None:
                self.events: list[tuple[str, object]] = []
                self.bus_number = 3
                self.device_address = 10
                self.device_path = "3-2.2"

            def cmd(self, cdb: bytes, data_len: int = 0):
                self.events.append(("cmd", cdb.hex(), data_len))
                if cdb[1] == EXECUTOR._writer.SUB_STATUS:
                    return b"\0", 0, 1
                return b"", 0, 0

            def program(self, cdb: bytes, payload: bytes):
                self.events.append(("program", cdb.hex(), PLANNER.sha256(payload)))

            def close(self) -> None:
                self.events.append(("close",))

        barrier = int(self.transaction.descriptor[
            "install_core1_barrier"]["absolute_sector_offset"], 0)
        for index, operation in enumerate(self.transaction.operations):
            device = Device()
            backend = EXECUTOR.FixedProofMutationBackend(
                self.transaction, index, device_factory=lambda: device)
            backend.execute()
            in_core0 = (PLANNER.CORE0_START <= operation.offset and
                        operation.offset + operation.length <=
                        PLANNER.CORE0_ENVELOPE_END)
            in_barrier = (barrier <= operation.offset and
                          operation.offset + operation.length <=
                          barrier + PLANNER.SECTOR_BYTES)
            self.assertTrue(in_core0 or in_barrier)
            self.assertEqual(device.events[0], (
                "cmd", (bytes([0xF6, EXECUTOR._writer.SUB_EX4B]) +
                        bytes(14)).hex(), 0))
            trace = self.transaction.descriptor["operations"][index]
            if operation.action == "program":
                self.assertIn(
                    ("program", trace["cdb_hex"], trace["payload_sha256"]),
                    device.events)
            else:
                self.assertIn(("cmd", trace["cdb_hex"], 0), device.events)
            self.assertEqual(device.events[-1][0], "cmd")  # ready poll

    def test_all_post_intent_fault_classes_leave_terminal_intent_and_skip_close(self) -> None:
        for fault in ("constructor", "identity", "capture_1", "capture_2",
                      "execute", "capture_3", "capture_4", "close"):
            with self.subTest(fault=fault):
                path = self.case / f"{fault}.json"
                identity = self.identity()
                source = EXECUTOR.boundary_journal(
                    self.transaction, identity, 0)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                state = FakeState(self.baseline)
                state.fail_at = fault
                with self.assertRaises(EXECUTOR.RecoveryRequired):
                    EXECUTOR.live_step(
                        self.transaction, path,
                        backend_factory=lambda transaction, index: FakeMutationBackend(
                            transaction, index, state), progress=False)
                visible = EXECUTOR.load_journal(path)
                self.assertEqual(visible["status"], EXECUTOR.INTENT)
                self.assertEqual(state.execute_count, 1 if fault in (
                    "execute", "capture_3", "capture_4", "close") else 0)
                if fault != "close":
                    self.assertEqual(state.close_count, 0)
                with self.assertRaises(EXECUTOR.RecoveryRequired):
                    EXECUTOR._require_step_state(self.transaction, visible)

    def test_atomic_intent_publication_errors_open_no_usb(self) -> None:
        for site, expected_status in (
                ("before_replace", EXECUTOR.BOUNDARY_VERIFIED),
                ("after_replace", EXECUTOR.INTENT)):
            with self.subTest(site=site):
                path = self.case / f"atomic-{site}.json"
                identity = self.identity()
                source = EXECUTOR.boundary_journal(
                    self.transaction, identity, 0)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                opened = 0

                def factory(_transaction: object, _index: int):
                    nonlocal opened
                    opened += 1
                    raise AssertionError("USB must not open")

                def fault(actual: str):
                    if actual == site:
                        raise RuntimeError("publication fault")

                with self.assertRaises(EXECUTOR.StateInspectionRequired):
                    EXECUTOR.live_step(
                        self.transaction, path, backend_factory=factory,
                        progress=False, journal_fault=fault)
                self.assertEqual(opened, 0)
                self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                 expected_status)

    def test_step_verified_publication_faults_are_exactly_classified(self) -> None:
        for site, exception, status in (
                ("before_replace", EXECUTOR.RecoveryRequired, EXECUTOR.INTENT),
                ("after_replace", EXECUTOR.StateInspectionRequired,
                 EXECUTOR.BOUNDARY_VERIFIED)):
            with self.subTest(site=site):
                path = self.case / f"step-final-{site}.json"
                source = EXECUTOR.boundary_journal(
                    self.transaction, self.identity(initial_address=10), 0)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                state = FakeState(self.baseline)
                with self.assertRaises(exception):
                    EXECUTOR.live_step(
                        self.transaction, path,
                        backend_factory=lambda transaction, index:
                        FakeMutationBackend(transaction, index, state),
                        progress=False,
                        journal_fault=self.fault_on_occurrence(site, 2))
                self.assertEqual(state.execute_count, 1)
                self.assertEqual(state.close_count, 1)
                visible = EXECUTOR.load_journal(path)
                self.assertEqual(visible["status"], status)
                if status == EXECUTOR.BOUNDARY_VERIFIED:
                    self.assertEqual(visible["boundary_index"], 1)
                    self.assertEqual(
                        EXECUTOR.inspect_state(
                            self.transaction, path)["permitted_next"],
                        "step_dry_run")
                else:
                    with self.assertRaises(EXECUTOR.RecoveryRequired):
                        EXECUTOR._require_step_state(self.transaction, visible)

    def test_loader_identity_mismatch_consumes_step_before_mutation(self) -> None:
        for field, replacement in (
                ("device_path", "3-9.9"),
                ("usb_bus_number", 4),
                ("identify_hex", "ffff"),
                ("descriptor_sha256", "3" * 64),
                ("loader_fingerprint_sha256", "4" * 64)):
            with self.subTest(field=field):
                path = self.case / f"identity-{field}.json"
                source = EXECUTOR.boundary_journal(
                    self.transaction, self.identity(initial_address=10), 0)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                state = FakeState(self.baseline)
                original = state.identity

                def changed_identity():
                    result = original()
                    result[field] = replacement
                    return result

                state.identity = changed_identity  # type: ignore[method-assign]
                with self.assertRaises(EXECUTOR.RecoveryRequired):
                    EXECUTOR.live_step(
                        self.transaction, path,
                        backend_factory=lambda transaction, index:
                        FakeMutationBackend(transaction, index, state),
                        progress=False)
                self.assertEqual(state.execute_count, 0)
                self.assertEqual(state.close_count, 0)
                self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                 EXECUTOR.INTENT)

    def test_install_barrier_reentry_and_restore_barrier_are_machine_gated(self) -> None:
        install = self.transaction.install_count
        before_install_commit = EXECUTOR.expected_boundary_image(
            self.transaction, install - 1)
        self.write_boundary(install - 1)
        state = FakeState(before_install_commit)
        installed = EXECUTOR.live_step(
            self.transaction, self.journal,
            backend_factory=lambda transaction, index: FakeMutationBackend(
                transaction, index, state), progress=False)
        self.assertEqual(installed["status"], EXECUTOR.PROOF_INSTALLED)
        with self.assertRaisesRegex(EXECUTOR.ExecutorError, "cold boot"):
            EXECUTOR._require_step_state(self.transaction, installed)

        state.address = 11
        validated = EXECUTOR.live_validate_reentry(
            self.transaction, self.journal,
            backend_factory=lambda transaction: FakeReadBackend(transaction, state),
            progress=False)
        self.assertEqual(validated["status"], EXECUTOR.RESTORE_READY)
        self.assertEqual(validated["initial_usb_address"], 10)
        self.assertEqual(validated["current_usb_address"], 11)
        self.assertEqual(EXECUTOR._require_step_state(
            self.transaction, validated), install)

    def test_reentry_requires_new_address_and_exact_proof_image(self) -> None:
        install = self.transaction.install_count
        for scenario in ("same_address", "wrong_image"):
            with self.subTest(scenario=scenario):
                path = self.case / f"reentry-{scenario}.json"
                identity = self.identity()
                source = EXECUTOR.boundary_journal(
                    self.transaction, identity, install,
                    status=EXECUTOR.PROOF_INSTALLED)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                image = self.transaction.campaign.proof_image
                if scenario == "wrong_image":
                    changed = bytearray(image)
                    changed[PLANNER.CORE0_START + 7] ^= 1
                    image = bytes(changed)
                state = FakeState(image, address=10 if scenario ==
                                  "same_address" else 11)
                with self.assertRaises(EXECUTOR.RecoveryRequired):
                    EXECUTOR.live_validate_reentry(
                        self.transaction, path,
                        backend_factory=lambda transaction: FakeReadBackend(
                            transaction, state), progress=False)
                self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                 EXECUTOR.REENTRY_STARTED)

    def test_reentry_fault_matrix_retains_terminal_started_state(self) -> None:
        install = self.transaction.install_count
        for fault in ("constructor", "identity", "capture_1", "capture_2",
                      "close"):
            with self.subTest(fault=fault):
                path = self.case / f"reentry-fault-{fault}.json"
                source = EXECUTOR.boundary_journal(
                    self.transaction, self.identity(initial_address=10), install,
                    status=EXECUTOR.PROOF_INSTALLED)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                state = FakeState(self.transaction.campaign.proof_image, address=11)
                state.fail_at = fault
                with self.assertRaises(EXECUTOR.RecoveryRequired):
                    EXECUTOR.live_validate_reentry(
                        self.transaction, path,
                        backend_factory=lambda transaction: FakeReadBackend(
                            transaction, state), progress=False)
                self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                 EXECUTOR.REENTRY_STARTED)
                self.assertEqual(state.close_count, 1 if fault == "close" else 0)
                self.assertEqual(
                    EXECUTOR.inspect_state(
                        self.transaction, path)["permitted_next"],
                    "external_spi_only")

    def test_reentry_start_and_restore_ready_publication_faults_open_safely(self) -> None:
        install = self.transaction.install_count
        for site, visible_status in (
                ("before_replace", EXECUTOR.PROOF_INSTALLED),
                ("after_replace", EXECUTOR.REENTRY_STARTED)):
            with self.subTest(start_site=site):
                path = self.case / f"reentry-start-{site}.json"
                source = EXECUTOR.boundary_journal(
                    self.transaction, self.identity(initial_address=10), install,
                    status=EXECUTOR.PROOF_INSTALLED)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                opened = 0

                def factory(_transaction: object):
                    nonlocal opened
                    opened += 1
                    raise AssertionError("USB must not open")

                with self.assertRaises(EXECUTOR.StateInspectionRequired):
                    EXECUTOR.live_validate_reentry(
                        self.transaction, path, backend_factory=factory,
                        progress=False,
                        journal_fault=self.fault_on_occurrence(site, 1))
                self.assertEqual(opened, 0)
                self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                 visible_status)

        for site, exception, visible_status in (
                ("before_replace", EXECUTOR.RecoveryRequired,
                 EXECUTOR.REENTRY_STARTED),
                ("after_replace", EXECUTOR.StateInspectionRequired,
                 EXECUTOR.RESTORE_READY)):
            with self.subTest(target_site=site):
                path = self.case / f"reentry-target-{site}.json"
                source = EXECUTOR.boundary_journal(
                    self.transaction, self.identity(initial_address=10), install,
                    status=EXECUTOR.PROOF_INSTALLED)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                state = FakeState(self.transaction.campaign.proof_image, address=11)
                with self.assertRaises(exception):
                    EXECUTOR.live_validate_reentry(
                        self.transaction, path,
                        backend_factory=lambda transaction: FakeReadBackend(
                            transaction, state), progress=False,
                        journal_fault=self.fault_on_occurrence(site, 2))
                self.assertEqual(state.close_count, 1)
                self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                 visible_status)

    def test_reentry_requires_same_topology_bus_and_canonical_identity(self) -> None:
        install = self.transaction.install_count
        scenarios = (
            {"device_path": "3-2.3"},
            {"usb_bus_number": 4},
            {"descriptor_sha256": "f" * 64},
            {"extra": "not allowed"},
        )
        for number, changes in enumerate(scenarios):
            with self.subTest(changes=changes):
                path = self.case / f"reentry-identity-{number}.json"
                source = EXECUTOR.boundary_journal(
                    self.transaction, self.identity(initial_address=10), install,
                    status=EXECUTOR.PROOF_INSTALLED)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                state = FakeState(self.transaction.campaign.proof_image, address=11)
                original = state.identity

                def changed_identity():
                    result = original()
                    result.update(changes)
                    return result

                state.identity = changed_identity  # type: ignore[method-assign]
                with self.assertRaises(EXECUTOR.RecoveryRequired):
                    EXECUTOR.live_validate_reentry(
                        self.transaction, path,
                        backend_factory=lambda transaction: FakeReadBackend(
                            transaction, state), progress=False)
                self.assertEqual(state.close_count, 0)
                self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                 EXECUTOR.REENTRY_STARTED)

    def test_last_restore_operation_and_finalization_restore_and_clear_stock(self) -> None:
        final_index = len(self.transaction.operations) - 1
        image = EXECUTOR.expected_boundary_image(self.transaction, final_index)
        self.write_boundary(final_index, address=11)
        state = FakeState(image, address=11)
        complete = EXECUTOR.live_step(
            self.transaction, self.journal,
            backend_factory=lambda transaction, index: FakeMutationBackend(
                transaction, index, state), progress=False)
        self.assertEqual(complete["status"], EXECUTOR.COMPLETE)
        self.assertEqual(bytes(state.image), self.baseline)
        result = EXECUTOR.live_finalize(
            self.transaction, self.journal,
            backend_factory=lambda transaction: FakeReadBackend(transaction, state),
            progress=False)
        self.assertTrue(result["state_cleared"])
        self.assertFalse(self.journal.exists())

    def test_finalize_fault_matrix_retains_terminal_started_state(self) -> None:
        boundary = len(self.transaction.operations)
        for fault in ("constructor", "identity", "capture_1", "capture_2",
                      "close"):
            with self.subTest(fault=fault):
                path = self.case / f"finalize-{fault}.json"
                identity = self.identity(address=11, initial_address=10)
                source = EXECUTOR.boundary_journal(
                    self.transaction, identity, boundary,
                    status=EXECUTOR.COMPLETE)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                state = FakeState(self.baseline, address=11)
                state.fail_at = fault
                with self.assertRaises(EXECUTOR.RecoveryRequired):
                    EXECUTOR.live_finalize(
                        self.transaction, path,
                        backend_factory=lambda transaction: FakeReadBackend(
                            transaction, state), progress=False)
                self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                 EXECUTOR.FINALIZE_STARTED)
                self.assertEqual(state.close_count, 1 if fault == "close" else 0)

    def test_finalize_start_publication_faults_open_no_usb(self) -> None:
        boundary = len(self.transaction.operations)
        for site, visible_status in (
                ("before_replace", EXECUTOR.COMPLETE),
                ("after_replace", EXECUTOR.FINALIZE_STARTED)):
            with self.subTest(site=site):
                path = self.case / f"finalize-start-{site}.json"
                source = EXECUTOR.boundary_journal(
                    self.transaction,
                    self.identity(address=11, initial_address=10), boundary,
                    status=EXECUTOR.COMPLETE)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                opened = 0

                def factory(_transaction: object):
                    nonlocal opened
                    opened += 1
                    raise AssertionError("USB must not open")

                with self.assertRaises(EXECUTOR.StateInspectionRequired):
                    EXECUTOR.live_finalize(
                        self.transaction, path, backend_factory=factory,
                        progress=False,
                        journal_fault=self.fault_on_occurrence(site, 1))
                self.assertEqual(opened, 0)
                self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                 visible_status)

    def test_finalize_clear_faults_distinguish_terminal_and_exact_absence(self) -> None:
        boundary = len(self.transaction.operations)
        for outcome, exception, exists in (
                ("before_unlink", EXECUTOR.RecoveryRequired, True),
                ("after_unlink", EXECUTOR.StateInspectionRequired, False),
                ("returned_without_clear", EXECUTOR.StateInspectionRequired, True)):
            with self.subTest(outcome=outcome):
                path = self.case / f"finalize-clear-{outcome}.json"
                source = EXECUTOR.boundary_journal(
                    self.transaction,
                    self.identity(address=11, initial_address=10), boundary,
                    status=EXECUTOR.COMPLETE)
                EXECUTOR.write_journal_atomic(path, source, require_absent=True)
                state = FakeState(self.baseline, address=11)

                def clear(target: Path) -> None:
                    if outcome == "before_unlink":
                        raise RuntimeError("clear before unlink")
                    if outcome == "after_unlink":
                        EXECUTOR.clear_journal(target)
                        raise RuntimeError("clear after unlink")

                with self.assertRaises(exception):
                    EXECUTOR.live_finalize(
                        self.transaction, path,
                        backend_factory=lambda transaction: FakeReadBackend(
                            transaction, state), progress=False, clear_fn=clear)
                self.assertEqual(path.exists(), exists)
                self.assertEqual(state.close_count, 1)
                if exists:
                    self.assertEqual(EXECUTOR.load_journal(path)["status"],
                                     EXECUTOR.FINALIZE_STARTED)

    def test_inspect_is_local_only_and_reports_all_authority_classes(self) -> None:
        self.assertEqual(
            EXECUTOR.inspect_state(self.transaction, self.journal)["permitted_next"],
            "preflight_dry_run")
        cases = (
            (0, EXECUTOR.BOUNDARY_VERIFIED, "step_dry_run"),
            (0, EXECUTOR.PREFLIGHT_STARTED, "external_spi_only"),
            (0, EXECUTOR.INTENT, "external_spi_only"),
            (self.transaction.install_count, EXECUTOR.PROOF_INSTALLED,
             "cold_boot_then_validate_reentry_dry_run"),
            (self.transaction.install_count, EXECUTOR.REENTRY_STARTED,
             "external_spi_only"),
            (self.transaction.install_count, EXECUTOR.RESTORE_READY,
             "step_dry_run"),
            (len(self.transaction.operations), EXECUTOR.COMPLETE,
             "finalize_dry_run"),
            (len(self.transaction.operations), EXECUTOR.FINALIZE_STARTED,
             "external_spi_only"),
        )
        for index, status, action in cases:
            path = self.case / f"inspect-{status}.json"
            if status == EXECUTOR.PREFLIGHT_STARTED:
                journal = EXECUTOR.preflight_started_journal(self.transaction)
            elif status == EXECUTOR.INTENT:
                source = EXECUTOR.boundary_journal(
                    self.transaction, self.identity(initial_address=10), 0)
                journal = EXECUTOR.intent_journal(self.transaction, source, 0)
            else:
                current = 11 if status in (
                    EXECUTOR.RESTORE_READY, EXECUTOR.COMPLETE,
                    EXECUTOR.FINALIZE_STARTED) else 10
                journal = EXECUTOR.boundary_journal(
                    self.transaction,
                    self.identity(address=current, initial_address=10),
                    index, status=status)
            EXECUTOR.write_journal_atomic(path, journal, require_absent=True)
            self.assertEqual(
                EXECUTOR.inspect_state(self.transaction, path)["permitted_next"],
                action)

    def test_process_lock_prevents_stale_parallel_step(self) -> None:
        self.write_boundary(0)
        lock_path = EXECUTOR.journal_lock_path(self.journal)
        lock_path.touch(mode=0o600)
        fd = os.open(lock_path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(EXECUTOR.ExecutorError, "another"):
                with EXECUTOR.journal_lock(self.transaction, self.journal):
                    pass
        finally:
            os.close(fd)

    def test_journal_schema_permissions_symlinks_and_phase_tamper_fail_closed(self) -> None:
        source = EXECUTOR.boundary_journal(
            self.transaction, self.identity(initial_address=10), 0)
        mutations = (
            ("schema", lambda value: value.update(schema="foreign-schema")),
            ("unknown", lambda value: value.update(unexpected=True)),
            ("source", lambda value: value.update(
                executor_source_sha256="f" * 64)),
            ("nonhex", lambda value: value.update(
                descriptor_sha256="z" * 64)),
            ("address", lambda value: value.update(current_usb_address=11)),
            ("topology", lambda value: value.update(device_path="4-2.2")),
            ("window", lambda value: value.update(loader_window_sha256="a" * 64)),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                path = self.case / f"tampered-{name}.json"
                value = dict(source)
                mutate(value)
                EXECUTOR.write_journal_atomic(path, value, require_absent=True)
                with self.assertRaises(EXECUTOR.ExecutorError):
                    EXECUTOR.validate_journal(
                        self.transaction, EXECUTOR.load_journal(path))

        mode_path = self.case / "wrong-mode.json"
        EXECUTOR.write_journal_atomic(mode_path, source, require_absent=True)
        mode_path.chmod(0o644)
        with self.assertRaises(EXECUTOR.ExecutorError):
            EXECUTOR.load_journal(mode_path)

        target = self.case / "symlink-target.json"
        EXECUTOR.write_journal_atomic(target, source, require_absent=True)
        link = self.case / "journal-link.json"
        link.symlink_to(target)
        with self.assertRaises(EXECUTOR.ExecutorError):
            EXECUTOR.load_journal(link)
        with self.assertRaises(EXECUTOR.ExecutorError):
            EXECUTOR.inspect_state(self.transaction, link)

    def test_import_time_hashes_and_executor_descriptor_detect_source_drift(self) -> None:
        self.assertEqual(
            dict(EXECUTOR.IMPLEMENTATION_HASHES),
            EXECUTOR.implementation_hashes())
        descriptor = EXECUTOR._executor_descriptor_sha256()
        self.assertEqual(len(descriptor), 64)
        reviewed = mock.Mock(campaign_id=EXECUTOR.EXPECTED_CAMPAIGN_ID)
        authorization = (
            mock.patch.object(EXECUTOR, "LIVE_PROOF_CAMPAIGN_ENABLED", True),
            mock.patch.object(EXECUTOR, "EXPECTED_IMPLEMENTATION_HASHES",
                              dict(EXECUTOR.IMPLEMENTATION_HASHES)),
            mock.patch.object(EXECUTOR, "EXPECTED_POLICY_SHA256",
                              EXECUTOR._policy_sha256()),
            mock.patch.object(EXECUTOR,
                              "EXPECTED_EXECUTOR_DESCRIPTOR_SHA256",
                              descriptor),
        )
        with authorization[0], authorization[1], authorization[2], \
                authorization[3]:
            EXECUTOR.require_live_authorization(reviewed)
        with mock.patch.object(EXECUTOR, "LIVE_PROOF_CAMPAIGN_ENABLED", True), \
                mock.patch.object(EXECUTOR, "EXPECTED_IMPLEMENTATION_HASHES",
                                  dict(EXECUTOR.IMPLEMENTATION_HASHES)), \
                mock.patch.object(EXECUTOR, "EXPECTED_POLICY_SHA256",
                                  EXECUTOR._policy_sha256()), \
                mock.patch.object(EXECUTOR,
                                  "EXPECTED_EXECUTOR_DESCRIPTOR_SHA256",
                                  descriptor), \
                mock.patch.object(EXECUTOR, "implementation_hashes",
                                  return_value={"drift": "0" * 64}):
            with self.assertRaises(EXECUTOR.ExecutionLocked):
                EXECUTOR.require_live_authorization(reviewed)

    def test_cli_has_no_raw_authority_and_dry_run_cannot_open_usb(self) -> None:
        for command in ("preflight", "step", "validate-reentry", "finalize",
                        "inspect"):
            result = subprocess.run(
                [sys.executable, str(EXECUTOR_PATH), command, "--help"],
                text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            lowered = result.stdout.lower()
            for forbidden in ("--offset", "--payload", "--cdb", "--force",
                              "--retry", "--operation-index", "--device"):
                self.assertNotIn(forbidden, lowered)
        self.assertNotIn("LIVE_MUTATION_ENABLED = True",
                         EXECUTOR_PATH.read_text(encoding="utf-8"))
        arguments = [
            "preflight",
            "--baseline-a", str(self.baseline_a),
            "--baseline-b", str(self.baseline_b),
            "--proof-core0-elf", str(self.proof_elf),
            "--campaign", str(self.campaign_dir),
            "--journal", str(self.journal),
        ]
        with mock.patch.object(EXECUTOR, "load_transaction",
                               return_value=self.transaction), \
                mock.patch.object(EXECUTOR, "live_preflight") as live:
            self.assertEqual(EXECUTOR.main(arguments), 0)
            live.assert_not_called()
            self.assertEqual(EXECUTOR.main(arguments + ["--commit"]), 2)
            live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
