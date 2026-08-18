from __future__ import annotations

import unittest

from kb7studio.protocol import (BAD_CRC, BAD_STATE, COMMAND, FACTORY_RESET, OK, READ,
                                RESET_TOKEN, SELECT, OfflineReceiver, ProtocolError, Report,
                                transfer_reports)


class ProtocolTests(unittest.TestCase):
    def test_report_round_trip(self) -> None:
        report = Report(1, 0x11, 7, 42, 72, 100, b"hello")
        parsed = Report.unpack(report.pack())
        self.assertEqual(parsed.sequence, 7)
        self.assertTrue(parsed.payload.startswith(b"hello"))

    def test_frame_corruption_is_rejected(self) -> None:
        blob = bytearray(Report(1, 1).pack())
        blob[20] ^= 1
        with self.assertRaises(ProtocolError):
            Report.unpack(bytes(blob))

    def test_chunked_transfer_commits(self) -> None:
        payload = bytes(range(251)) * 29
        receiver = OfflineReceiver()
        statuses = [receiver.process(report).status for report in transfer_reports(payload, 99)]
        self.assertTrue(all(status == OK for status in statuses))
        self.assertEqual(receiver.committed, payload)

    def test_out_of_order_chunk_does_not_replace_committed(self) -> None:
        receiver = OfflineReceiver()
        stable = b"stable" * 10
        for report in transfer_reports(stable):
            receiver.process(report)
        reports = transfer_reports(b"replacement" * 20, 2)
        receiver.process(reports[0])
        self.assertEqual(receiver.process(reports[2]).status, BAD_STATE)
        self.assertEqual(receiver.committed, stable)

    def test_read_select_and_confirmed_factory_reset(self) -> None:
        receiver = OfflineReceiver()
        stored = b"stored-screen" * 5
        for report in transfer_reports(stored, 7):
            self.assertEqual(receiver.process(report).status, OK)
        read = receiver.process(Report(COMMAND, READ, offset=3))
        self.assertEqual(read.payload, stored[3:3 + 36])
        self.assertEqual(read.total_length, len(stored))
        self.assertEqual(receiver.process(Report(COMMAND, SELECT, offset=42)).status, OK)
        self.assertEqual(receiver.selected_screen, 42)
        denied = receiver.process(Report(COMMAND, FACTORY_RESET))
        self.assertEqual(denied.status, BAD_STATE)
        reset = Report(COMMAND, FACTORY_RESET, transfer_id=RESET_TOKEN,
                       payload=b"RESETKB7", flags=0xA5)
        self.assertEqual(receiver.process(reset).status, OK)
        self.assertEqual(receiver.committed, b"")

    def test_begin_does_not_replace_an_active_transfer(self) -> None:
        receiver = OfflineReceiver()
        reports = transfer_reports(b"first transfer" * 4, 10)
        self.assertEqual(receiver.process(reports[0]).status, OK)
        replacement = transfer_reports(b"second transfer" * 4, 11)[0]
        self.assertEqual(receiver.process(replacement).status, BAD_STATE)
        self.assertEqual(receiver.transfer_id, 10)


if __name__ == "__main__":
    unittest.main()
