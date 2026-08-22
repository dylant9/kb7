from __future__ import annotations

import copy
import json
import random
import struct
import unittest
from pathlib import Path

from kb7studio.format import (HEADER, MAX_BINARY_SIZE, SCREEN, WIDGET, ScreenFormatError,
                              compile_document, crc32, parse_binary)

ROOT = Path(__file__).resolve().parents[1]


class ScreenFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads((ROOT / "samples/offline-example.json").read_text())
        cls.blob = compile_document(cls.document)

    def test_round_trip_is_canonical(self) -> None:
        parsed = parse_binary(self.blob)
        self.assertEqual(compile_document(parsed), self.blob)
        self.assertEqual(parsed["boot_screen"], 1)
        self.assertEqual(len(parsed["screens"]), 2)

    def test_every_truncation_is_rejected(self) -> None:
        for length in range(len(self.blob)):
            with self.subTest(length=length), self.assertRaises(ScreenFormatError):
                parse_binary(self.blob[:length])

    def test_body_corruption_is_rejected(self) -> None:
        corrupted = bytearray(self.blob)
        corrupted[-1] ^= 0x80
        with self.assertRaisesRegex(ScreenFormatError, "CRC"):
            parse_binary(bytes(corrupted))

    def test_firmware_screen_slot_capacity_is_enforced(self) -> None:
        widgets = [{
            "id": index + 1, "type": "label", "x": 0, "y": 0,
            "width": 1, "height": 1, "text": "x" * 65535,
        } for index in range(33)]
        oversized = {"format": "kb7-screen-v1", "boot_screen": 1,
                     "screens": [{"id": 1, "name": "", "widgets": widgets}]}
        with self.assertRaisesRegex(ScreenFormatError, "screen-slot capacity"):
            compile_document(oversized)
        with self.assertRaisesRegex(ScreenFormatError, "screen-slot capacity"):
            parse_binary(b"\0" * (MAX_BINARY_SIZE + 1))

    def test_version_mismatch_is_rejected(self) -> None:
        corrupted = bytearray(self.blob)
        struct.pack_into("<H", corrupted, 4, 99)
        with self.assertRaisesRegex(ScreenFormatError, "version"):
            parse_binary(bytes(corrupted))

    def test_geometry_and_duplicate_ids_are_rejected(self) -> None:
        bad = copy.deepcopy(self.document)
        bad["screens"][0]["widgets"][0]["x"] = 479
        bad["screens"][0]["widgets"][0]["width"] = 2
        with self.assertRaises(ScreenFormatError):
            compile_document(bad)
        bad = copy.deepcopy(self.document)
        bad["screens"][1]["widgets"][0]["id"] = bad["screens"][0]["widgets"][0]["id"]
        with self.assertRaises(ScreenFormatError):
            compile_document(bad)
        bad = copy.deepcopy(self.document)
        bad["screens"][0]["widgets"][0]["action"] = {
            "type": "navigate", "target_screen": 0xFFFF,
        }
        with self.assertRaises(ScreenFormatError):
            compile_document(bad)

    def _body_recrc(self, blob: bytearray) -> bytes:
        struct.pack_into("<I", blob, 12, crc32(blob[HEADER.size:]))
        return bytes(blob)

    def test_noncanonical_and_reserved_fields_are_rejected(self) -> None:
        bad = bytearray(self.blob)
        struct.pack_into("<H", bad, 22, 1)  # header flags
        with self.assertRaises(ScreenFormatError):
            parse_binary(bytes(bad))

    def test_boolean_is_not_an_rgb565_integer(self) -> None:
        bad = copy.deepcopy(self.document)
        bad["screens"][0]["background"] = True
        with self.assertRaisesRegex(ScreenFormatError, "boolean"):
            compile_document(bad)

        bad = bytearray(self.blob)
        widget_offset = HEADER.size + len(self.document["screens"]) * SCREEN.size
        struct.pack_into("<H", bad, widget_offset + WIDGET.size - 2, 1)
        with self.assertRaises(ScreenFormatError):
            parse_binary(self._body_recrc(bad))

    def test_action_specific_ranges_and_flags_are_rejected(self) -> None:
        bad = copy.deepcopy(self.document)
        bad["screens"][0]["widgets"][2]["maximum"] = 101
        with self.assertRaises(ScreenFormatError):
            compile_document(bad)
        bad = copy.deepcopy(self.document)
        bad["screens"][0]["widgets"][1]["action"]["flags"] = 1
        with self.assertRaises(ScreenFormatError):
            compile_document(bad)
        bad = copy.deepcopy(self.document)
        bad["screens"][0]["widgets"][3]["action"]["arg1"] = 0x1000000
        with self.assertRaises(ScreenFormatError):
            compile_document(bad)
        for action in (
            {"type": "rgb_effect", "arg0": 5},
            {"type": "profile", "arg0": 5},
            {"type": "hid_key", "arg0": 0},
            {"type": "media_key", "arg0": 0},
        ):
            bad = copy.deepcopy(self.document)
            bad["screens"][0]["widgets"][0]["action"] = action
            with self.subTest(action=action), self.assertRaises(ScreenFormatError):
                compile_document(bad)

    def test_binary_duplicate_widget_and_bad_range_are_rejected(self) -> None:
        bad = bytearray(self.blob)
        widget_offset = HEADER.size + len(self.document["screens"]) * SCREEN.size
        first_id = struct.unpack_from("<H", bad, widget_offset)[0]
        struct.pack_into("<H", bad, widget_offset + WIDGET.size, first_id)
        with self.assertRaises(ScreenFormatError):
            parse_binary(self._body_recrc(bad))

        bad = bytearray(self.blob)
        struct.pack_into("<h", bad, widget_offset + 16, 100)
        struct.pack_into("<h", bad, widget_offset + 18, 10)
        with self.assertRaises(ScreenFormatError):
            parse_binary(self._body_recrc(bad))

    def test_invalid_utf8_and_widget_partition_are_rejected(self) -> None:
        bad = bytearray(self.blob)
        strings_offset = struct.unpack_from("<I", bad, 32)[0]
        bad[strings_offset] = 0xFF
        with self.assertRaises(ScreenFormatError):
            parse_binary(self._body_recrc(bad))

        bad = bytearray(self.blob)
        second_screen = HEADER.size + SCREEN.size
        struct.pack_into("<H", bad, second_screen + 2, 0)
        with self.assertRaises(ScreenFormatError):
            parse_binary(self._body_recrc(bad))

    def test_deterministic_mutation_fuzz_never_crashes(self) -> None:
        randomizer = random.Random(0x4B4237)
        accepted = 0
        for _ in range(5000):
            mutated = bytearray(self.blob)
            for _ in range(randomizer.randrange(1, 10)):
                if mutated:
                    mutated[randomizer.randrange(len(mutated))] ^= randomizer.randrange(1, 256)
            if randomizer.randrange(4) == 0:
                mutated = mutated[:randomizer.randrange(len(mutated) + 1)]
            try:
                parse_binary(bytes(mutated))
                accepted += 1
            except ScreenFormatError:
                pass
        # Some semantically valid header mutations (for example a valid alternate
        # boot screen) are not covered by the body CRC, but acceptance stays rare.
        self.assertLess(accepted, 10)


if __name__ == "__main__":
    unittest.main()
