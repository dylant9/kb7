from __future__ import annotations

import json
import unittest
from pathlib import Path

from kb7studio.format import compile_document
from kb7studio.profile_binary import compile_profile_binary
from kb7studio.protocol import (BAD_LENGTH, BAD_STATE, COMMAND, FACTORY_RESET, OK, RANGE, WRITE,
                                QUERY_CAPABILITIES, READ, RESET_TOKEN, SELECT, STORE_PROFILE,
                                OfflineReceiver, ProtocolError, Report, transfer_reports)

ROOT = Path(__file__).resolve().parents[1]


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.screen = compile_document(json.loads(
            (ROOT / "samples/offline-example.json").read_text()))
        profile = json.loads((ROOT / "samples/offline-example-profile.json").read_text())
        profile["lighting"]["per_key"] = {}
        cls.profile = compile_profile_binary(profile)

    def test_report_round_trip(self) -> None:
        report = Report(1, 0x11, 7, 42, 72, 100, b"hello")
        parsed = Report.unpack(report.pack())
        self.assertEqual(parsed.sequence, 7)
        self.assertTrue(parsed.payload.startswith(b"hello"))

    def test_capabilities_expose_both_formats_and_store_sizes(self) -> None:
        response = OfflineReceiver().process(Report(COMMAND, QUERY_CAPABILITIES))
        fields = __import__("struct").unpack("<HHBBIBBBB HIII", response.payload)
        self.assertEqual(fields[:4], (480, 800, 16, 128))
        self.assertEqual(fields[4], 0x140000)
        self.assertEqual(fields[5:9], (1, 1, 5, 1))
        self.assertEqual(fields[9:12], (1792, 0x38000, 48 + 5 * 1792))
        self.assertEqual(fields[12], 0x1F)

    def test_frame_corruption_is_rejected(self) -> None:
        blob = bytearray(Report(1, 1).pack())
        blob[20] ^= 1
        with self.assertRaises(ProtocolError):
            Report.unpack(bytes(blob))

    def test_chunked_transfer_commits(self) -> None:
        payload = self.screen
        receiver = OfflineReceiver()
        statuses = [receiver.process(report).status for report in transfer_reports(payload, 99)]
        self.assertTrue(all(status == OK for status in statuses))
        self.assertEqual(receiver.committed, payload)

    def test_out_of_order_chunk_does_not_replace_committed(self) -> None:
        receiver = OfflineReceiver()
        stable = self.screen
        for report in transfer_reports(stable):
            receiver.process(report)
        replacement = bytearray(self.screen)
        replacement[-1] ^= 1
        reports = transfer_reports(bytes(replacement), 2)
        receiver.process(reports[0])
        self.assertEqual(receiver.process(reports[2]).status, BAD_STATE)
        self.assertEqual(receiver.committed, stable)

    def test_profile_store_is_independent(self) -> None:
        receiver = OfflineReceiver()
        screen = self.screen
        profile = self.profile
        for report in transfer_reports(screen, 1):
            self.assertEqual(receiver.process(report).status, OK)
        for report in transfer_reports(profile, 2, STORE_PROFILE):
            self.assertEqual(receiver.process(report).status, OK)
        response = receiver.process(Report(COMMAND, READ, flags=STORE_PROFILE))
        self.assertEqual(response.payload, profile[:36])
        self.assertEqual(receiver.committed, screen)

    def test_read_select_and_confirmed_factory_reset(self) -> None:
        receiver = OfflineReceiver(runtime_screen=self.screen)
        stored = self.screen
        for report in transfer_reports(stored, 7):
            self.assertEqual(receiver.process(report).status, OK)
        read = receiver.process(Report(COMMAND, READ, offset=3))
        self.assertEqual(read.payload, stored[3:3 + 36])
        self.assertEqual(read.total_length, len(stored))
        self.assertEqual(receiver.process(Report(COMMAND, SELECT, offset=1)).status, OK)
        self.assertEqual(receiver.selected_screen, 1)
        self.assertEqual(receiver.process(Report(COMMAND, SELECT, offset=42)).status, RANGE)
        self.assertEqual(receiver.selected_screen, 1)
        denied = receiver.process(Report(COMMAND, FACTORY_RESET))
        self.assertEqual(denied.status, BAD_STATE)
        reset = Report(COMMAND, FACTORY_RESET, transfer_id=RESET_TOKEN,
                       payload=b"RESETKB7", flags=0xA5)
        self.assertEqual(receiver.process(reset).status, OK)
        self.assertEqual(receiver.committed, b"")

    def test_factory_reset_is_rejected_during_transfer(self) -> None:
        receiver = OfflineReceiver()
        reports = transfer_reports(self.screen, 21)
        self.assertEqual(receiver.process(reports[0]).status, OK)
        reset = Report(COMMAND, FACTORY_RESET, transfer_id=RESET_TOKEN,
                       payload=b"RESETKB7", flags=0xA5)
        self.assertEqual(receiver.process(reset).status, BAD_STATE)
        self.assertTrue(receiver.receiving)
        self.assertEqual(receiver.transfer_id, 21)

    def test_begin_does_not_replace_an_active_transfer(self) -> None:
        receiver = OfflineReceiver()
        reports = transfer_reports(self.screen, 10)
        self.assertEqual(receiver.process(reports[0]).status, OK)
        replacement = transfer_reports(self.screen, 11)[0]
        self.assertEqual(receiver.process(replacement).status, BAD_STATE)
        self.assertEqual(receiver.transfer_id, 10)

    def test_commit_rejects_crc_valid_non_format_payload(self) -> None:
        receiver = OfflineReceiver()
        reports = transfer_reports(b"x" * 64, 12)
        statuses = [receiver.process(report).status for report in reports]
        self.assertEqual(statuses[-1], BAD_LENGTH)
        self.assertEqual(receiver.committed, b"")

    def test_profile_capacity_matches_kbp1_maximum(self) -> None:
        too_large = b"x" * (48 + 5 * 1792 + 1)
        with self.assertRaises(ProtocolError):
            transfer_reports(too_large, 13, STORE_PROFILE)

    def test_screen_begin_rejects_header_without_required_screen(self) -> None:
        with self.assertRaises(ProtocolError):
            transfer_reports(b"x" * 63, 14)

    def test_transfer_id_must_fit_the_wire_field(self) -> None:
        for invalid in (False, 0, -1, 0x100000000):
            with self.subTest(transfer_id=invalid), self.assertRaises(ProtocolError):
                transfer_reports(self.screen, invalid)

    def test_write_after_complete_payload_is_rejected(self) -> None:
        receiver = OfflineReceiver()
        reports = transfer_reports(self.screen, 44)
        for report in reports[:-1]:
            self.assertEqual(receiver.process(report).status, OK)
        extra = Report(COMMAND, WRITE, transfer_id=44, offset=len(self.screen),
                       total_length=len(self.screen))
        self.assertEqual(receiver.process(extra).status, BAD_STATE)


if __name__ == "__main__":
    unittest.main()
