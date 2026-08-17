from __future__ import annotations

import copy
import json
import random
import struct
import unittest
from pathlib import Path

from kb7studio.format import HEADER, ScreenFormatError, compile_document, parse_binary

ROOT = Path(__file__).resolve().parents[1]


class ScreenFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads((ROOT / "samples/neon-control.json").read_text())
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
        # Header flags are intentionally mutable and are not covered by body CRC.
        # Random mutations may therefore remain semantically valid, but must be rare.
        self.assertLess(accepted, 10)


if __name__ == "__main__":
    unittest.main()
