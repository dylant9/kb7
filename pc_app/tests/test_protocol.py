from __future__ import annotations

import unittest

from kb7studio.protocol import BAD_CRC, BAD_STATE, OK, OfflineReceiver, ProtocolError, Report, transfer_reports


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
        for report in transfer_reports(b"stable"):
            receiver.process(report)
        reports = transfer_reports(b"replacement" * 20, 2)
        receiver.process(reports[0])
        self.assertEqual(receiver.process(reports[2]).status, BAD_STATE)
        self.assertEqual(receiver.committed, b"stable")


if __name__ == "__main__":
    unittest.main()
