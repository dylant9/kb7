"""In-memory NOR model for atomic A/B screen-slot tests."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

MAGIC = 0x314C534B
VERSION = 1
ERASED, WRITING, VALID = 0xFFFFFFFF, 0x7FFFFFFF, 0x3FFFFFFF
HEADER = struct.Struct("<IHHIIIII36s")


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def make_header(state: int, generation: int, payload: bytes) -> bytes:
    values = [MAGIC, VERSION, HEADER.size, state, generation, len(payload), crc32(payload), 0, b"\0" * 36]
    normalized = values.copy()
    normalized[3] = VALID
    draft = HEADER.pack(*normalized)
    values[7] = crc32(draft)
    return HEADER.pack(*values)


def parse_header(blob: bytes) -> tuple[int, int, int] | None:
    if len(blob) != HEADER.size:
        return None
    magic, version, length, state, generation, payload_length, payload_crc, header_crc, reserved = HEADER.unpack(blob)
    values = [magic, version, length, VALID, generation, payload_length, payload_crc, 0, reserved]
    if (magic, version, length, state) != (MAGIC, VERSION, HEADER.size, VALID):
        return None
    if crc32(HEADER.pack(*values)) != header_crc:
        return None
    return generation, payload_length, payload_crc


class PowerLoss(RuntimeError):
    pass


class AtomicSlots:
    def __init__(self, slot_size: int = 0x140000):
        self.slot_size = slot_size
        self.flash = bytearray(b"\xff" * (slot_size * 2))

    def _program(self, offset: int, data: bytes) -> None:
        for index, value in enumerate(data):
            old = self.flash[offset + index]
            if value | old != old:
                raise ValueError("NOR programming attempted a zero-to-one transition")
            self.flash[offset + index] &= value

    def _slot(self, index: int) -> tuple[bytes, bytes] | None:
        base = index * self.slot_size
        parsed = parse_header(bytes(self.flash[base:base + HEADER.size]))
        if parsed is None:
            return None
        generation, length, expected_crc = parsed
        if length > self.slot_size - HEADER.size:
            return None
        payload = bytes(self.flash[base + HEADER.size:base + HEADER.size + length])
        return (struct.pack("<I", generation), payload) if crc32(payload) == expected_crc else None

    def active(self) -> bytes | None:
        slots = [self._slot(0), self._slot(1)]
        if slots[0] is None:
            return slots[1][1] if slots[1] is not None else None
        if slots[1] is None:
            return slots[0][1]
        left = struct.unpack("<I", slots[0][0])[0]
        right = struct.unpack("<I", slots[1][0])[0]
        return slots[0][1] if 0 < ((left - right) & 0xFFFFFFFF) < 0x80000000 else slots[1][1]

    def commit(self, payload: bytes, fail_after: str | None = None) -> None:
        if not payload or len(payload) > self.slot_size - HEADER.size:
            raise ValueError("payload does not fit slot")
        valid = [self._slot(0), self._slot(1)]
        generations = [struct.unpack("<I", value[0])[0] if value else 0 for value in valid]
        if valid[0] is None and valid[1] is None:
            active, target, generation = None, 0, 1
        elif valid[0] is None:
            active, target = 1, 0
            generation = (generations[1] + 1) & 0xFFFFFFFF
        elif valid[1] is None:
            active, target = 0, 1
            generation = (generations[0] + 1) & 0xFFFFFFFF
        else:
            active = 0 if 0 < ((generations[0] - generations[1]) & 0xFFFFFFFF) < 0x80000000 else 1
            target = 1 - active
            generation = (generations[active] + 1) & 0xFFFFFFFF
        assert active != target
        base = target * self.slot_size
        self.flash[base:base + self.slot_size] = b"\xff" * self.slot_size
        if fail_after == "erase": raise PowerLoss
        self._program(base, make_header(WRITING, generation, payload))
        if fail_after == "header": raise PowerLoss
        self._program(base + HEADER.size, payload)
        if fail_after == "payload": raise PowerLoss
        self._program(base + 8, struct.pack("<I", VALID))
