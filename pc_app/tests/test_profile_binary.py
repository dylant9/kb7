from __future__ import annotations

import copy
import json
import struct
import unittest
from pathlib import Path

from kb7studio.profile import ProfileFormatError
from kb7studio.profile_binary import compile_profile_binary, parse_profile_binary

ROOT = Path(__file__).resolve().parents[1]


class ProfileBinaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads((ROOT / "samples/offline-example-profile.json").read_text())
        cls.document["lighting"]["per_key"] = {}

    def test_compile_and_parse(self) -> None:
        blob = compile_profile_binary(self.document)
        parsed = parse_profile_binary(blob)
        self.assertEqual(len(blob), 48 + 1792)
        self.assertEqual(parsed["names"], ["Offline Profile"])

    def test_rejects_crc_corruption(self) -> None:
        blob = bytearray(compile_profile_binary(self.document))
        blob[-1] ^= 1
        with self.assertRaisesRegex(ProfileFormatError, "CRC"):
            parse_profile_binary(bytes(blob))

    def test_refuses_unmapped_per_key_rgb(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["lighting"]["per_key"] = {"W": "#ffffff"}
        with self.assertRaisesRegex(ProfileFormatError, "112 RGB positions"):
            compile_profile_binary(changed)

    def test_python_rejects_record_invalid_even_with_updated_crc(self) -> None:
        import struct
        import zlib

        blob = bytearray(compile_profile_binary(self.document))
        blob[48 + 80] = 0  # first Hall actuation cannot be zero
        struct.pack_into("<I", blob, 12, zlib.crc32(blob[48:]) & 0xFFFFFFFF)
        with self.assertRaisesRegex(ProfileFormatError, "Hall record"):
            parse_profile_binary(bytes(blob))

    def test_travel_quantization_is_decimal_half_up(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["switches"]["rapid_press_delta_mm"] = 0.05
        changed["switches"]["rapid_release_delta_mm"] = 0.25
        blob = compile_profile_binary(changed)
        # First Hall record begins at header 48 + record offset 80.
        self.assertEqual(blob[48 + 80 + 1], 1)
        self.assertEqual(blob[48 + 80 + 2], 3)

    def test_layout_layers_and_action_overrides_are_authored(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["firmware"] = {
            "layout_variant": 1,
            "initial_mode": "game",
            "actions": {
                "game": {
                    "A": {"type": "keyboard", "usage": "B"},
                    "FN": {"type": "none"},
                    "logical:80": {"type": "consumer", "usage": 0x00e9},
                },
                "easy_shift": {"A": {"type": "none"}},
            },
        }
        blob = compile_profile_binary(changed)
        record = 48
        self.assertEqual(blob[record + 64:record + 66], bytes((1, 1)))
        # Recovered logical selector for ANSI A is 22.
        action_offset = record + 420 + (1 * 85 + 22) * 4
        self.assertEqual(struct.unpack_from("<HBB", blob, action_offset), (0x05, 2, 0))
        extra_offset = record + 420 + (1 * 85 + 80) * 4
        self.assertEqual(struct.unpack_from("<HBB", blob, extra_offset), (0x00e9, 3, 0))
        fn_offset = record + 420 + (1 * 85 + 0x4e) * 4
        self.assertEqual(struct.unpack_from("<HBB", blob, fn_offset), (0, 1, 0))
        self.assertEqual(parse_profile_binary(blob)["profile_count"], 1)

    def test_compiles_four_profile_container_and_active_slot(self) -> None:
        profiles = []
        for index in range(4):
            profile = copy.deepcopy(self.document)
            profile["name"] = f"Slot {index + 1}"
            profiles.append(profile)
        blob = compile_profile_binary({
            "format": "kb7-profile-set-v1",
            "active_profile": 2,
            "profiles": profiles,
        })
        parsed = parse_profile_binary(blob)
        self.assertEqual(len(blob), 48 + 4 * 1792)
        self.assertEqual(parsed["profile_count"], 4)
        self.assertEqual(parsed["active_profile"], 2)
        self.assertEqual(parsed["names"], ["Slot 1", "Slot 2", "Slot 3", "Slot 4"])

    def test_rejects_invalid_layer_and_fn_overrides(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["firmware"] = {
            "actions": {"primary": {"FN": {"type": "none"}}},
        }
        with self.assertRaisesRegex(ProfileFormatError, "primary Fn"):
            compile_profile_binary(changed)
        changed["firmware"] = {"initial_mode": "fn1"}
        with self.assertRaisesRegex(ProfileFormatError, "initial_mode"):
            compile_profile_binary(changed)


if __name__ == "__main__":
    unittest.main()
