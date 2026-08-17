"""Device-free model of the KB7 vendor-HID transfer protocol."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

REPORT_ID = 0x5C
VERSION = 1
REPORT = struct.Struct("<BBBBBBHIIII36sI")
PAYLOAD = 36

COMMAND, RESPONSE, EVENT = 1, 2, 3
QUERY_VERSION, QUERY_CAPABILITIES = 0x01, 0x02
BEGIN, WRITE, COMMIT, ABORT, READ, SELECT, FACTORY_RESET = range(0x10, 0x17)
WIDGET_EVENT = 0x40
OK, BAD_VERSION, BAD_CRC, BAD_LENGTH, BAD_STATE, RANGE, STORAGE, UNSUPPORTED = range(8)


class ProtocolError(ValueError):
    pass


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


@dataclass(frozen=True)
class Report:
    kind: int
    opcode: int
    sequence: int = 0
    transfer_id: int = 0
    offset: int = 0
    total_length: int = 0
    payload: bytes = b""
    flags: int = 0
    status: int = 0

    def pack(self) -> bytes:
        if len(self.payload) > PAYLOAD:
            raise ProtocolError("payload exceeds 36 bytes")
        padded = self.payload.ljust(PAYLOAD, b"\0")
        prefix = REPORT.pack(REPORT_ID, VERSION, self.kind, self.opcode, self.flags, self.status,
                             self.sequence, self.transfer_id, self.offset, self.total_length,
                             crc32(padded), padded, 0)
        return prefix[:-4] + struct.pack("<I", crc32(prefix[1:-4]))

    @classmethod
    def unpack(cls, blob: bytes) -> "Report":
        if len(blob) != REPORT.size:
            raise ProtocolError("report must be exactly 64 bytes")
        (report_id, version, kind, opcode, flags, status, sequence, transfer_id, offset,
         total_length, payload_crc, payload, frame_crc) = REPORT.unpack(blob)
        if report_id != REPORT_ID or version != VERSION:
            raise ProtocolError("wrong report ID/version")
        if crc32(payload) != payload_crc or crc32(blob[1:-4]) != frame_crc:
            raise ProtocolError("report CRC mismatch")
        return cls(kind, opcode, sequence, transfer_id, offset, total_length,
                   payload, flags, status)


def transfer_reports(payload: bytes, transfer_id: int = 1) -> list[Report]:
    if not payload:
        raise ProtocolError("empty transfer")
    checksum = crc32(payload)
    reports = [Report(COMMAND, BEGIN, 0, transfer_id, 0, len(payload), struct.pack("<I", checksum))]
    sequence = 1
    for offset in range(0, len(payload), PAYLOAD):
        chunk = payload[offset:offset + PAYLOAD]
        reports.append(Report(COMMAND, WRITE, sequence, transfer_id, offset, len(payload), chunk))
        sequence += 1
    reports.append(Report(COMMAND, COMMIT, sequence, transfer_id, len(payload), len(payload),
                          struct.pack("<I", checksum)))
    return reports


class OfflineReceiver:
    """Strict receiver used by tests and the UI; performs no USB/device I/O."""

    def __init__(self, capacity: int = 0x200000):
        self.capacity = capacity
        self.abort()
        self.committed = b""

    def abort(self) -> None:
        self.transfer_id = 0
        self.expected = 0
        self.expected_crc = 0
        self.next_offset = 0
        self.buffer = bytearray()

    def process(self, report: Report) -> Report:
        status = OK
        if report.kind != COMMAND:
            status = BAD_STATE
        elif report.opcode == BEGIN:
            if report.total_length <= 0 or report.total_length > self.capacity:
                status = RANGE
            else:
                self.transfer_id = report.transfer_id
                self.expected = report.total_length
                self.expected_crc = struct.unpack_from("<I", report.payload)[0]
                self.next_offset = 0
                self.buffer = bytearray()
        elif report.opcode == WRITE:
            if report.transfer_id != self.transfer_id or report.offset != self.next_offset:
                status = BAD_STATE
            else:
                count = min(PAYLOAD, self.expected - self.next_offset)
                self.buffer.extend(report.payload[:count])
                self.next_offset += count
        elif report.opcode == COMMIT:
            if (report.transfer_id != self.transfer_id or self.next_offset != self.expected or
                    crc32(self.buffer) != self.expected_crc):
                status = BAD_CRC
            else:
                self.committed = bytes(self.buffer)
                self.abort()
        elif report.opcode == ABORT:
            self.abort()
        else:
            status = UNSUPPORTED
        return Report(RESPONSE, report.opcode, report.sequence, report.transfer_id,
                      self.next_offset, self.expected, status=status)
