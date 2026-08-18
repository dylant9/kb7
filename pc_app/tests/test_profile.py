from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from kb7studio.profile import ProfileFormatError, canonical_profile, validate_profile

ROOT = Path(__file__).resolve().parents[1]


class ProfileFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads((ROOT / "samples/offline-example-profile.json").read_text())

    def test_sample_is_valid_and_canonical(self) -> None:
        canonical = canonical_profile(self.document)
        self.assertEqual(canonical["format"], "kb7-profile-v1")
        self.assertEqual(canonical["analog"]["bindings"]["x_negative"], "LEFT")
        self.assertEqual(canonical["switches"]["per_key"]["W"]["actuation_mm"], 1.0)
        self.assertEqual(canonical["capabilities"]["rgb_position_mapping"], "pending_hardware")
        self.assertEqual(canonical["capabilities"]["hall_keymap"],
                         "implemented-hardware-unverified")
        self.assertEqual(canonical["capabilities"]["analog_hid_output"],
                         "implemented-hardware-unverified")
        self.assertFalse(canonical["capabilities"]["device_io"])
        validate_profile(canonical)

    def test_canonicalization_sorts_per_key_entries(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["lighting"]["per_key"] = {"W": "#FFFFFF", "A": "#000000"}
        canonical = canonical_profile(changed)
        self.assertEqual(list(canonical["lighting"]["per_key"]), ["A", "W"])
        self.assertEqual(canonical["lighting"]["per_key"]["W"], "#ffffff")

    def test_firmware_layer_authoring_is_validated_and_preserved(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["firmware"] = {
            "layout_variant": 1, "initial_mode": "game",
            "actions": {"game": {"A": {"type": "keyboard", "usage": "B"}}},
        }
        canonical = canonical_profile(changed)
        self.assertEqual(canonical["firmware"], changed["firmware"])
        bad = copy.deepcopy(changed)
        bad["firmware"]["actions"] = {"primary": {"FN": {"type": "consumer",
                                                               "usage": 233}}}
        with self.assertRaisesRegex(ProfileFormatError, "consumer usage"):
            canonical_profile(bad)

    def test_rejects_unknown_key_and_duplicate_axis_bindings(self) -> None:
        bad = copy.deepcopy(self.document)
        bad["lighting"]["per_key"]["ACTION_BAR_1"] = "#ffffff"
        with self.assertRaisesRegex(ProfileFormatError, "unknown or unverified"):
            validate_profile(bad)

        bad = copy.deepcopy(self.document)
        bad["analog"]["bindings"]["x_positive"] = "LEFT"
        with self.assertRaisesRegex(ProfileFormatError, "four distinct"):
            validate_profile(bad)

    def test_rejects_impossible_hall_and_axis_ranges(self) -> None:
        bad = copy.deepcopy(self.document)
        bad["switches"]["actuation_mm"] = 4.0
        with self.assertRaisesRegex(ProfileFormatError, "actuation_mm"):
            validate_profile(bad)

        bad = copy.deepcopy(self.document)
        bad["analog"]["deadzone_mm"] = 2.0
        bad["analog"]["saturation_mm"] = 1.0
        with self.assertRaisesRegex(ProfileFormatError, "below"):
            validate_profile(bad)

    def test_rejects_invalid_lighting_and_embedded_screen(self) -> None:
        bad = copy.deepcopy(self.document)
        bad["lighting"]["primary"] = "cyan"
        with self.assertRaisesRegex(ProfileFormatError, "#rrggbb"):
            validate_profile(bad)

        bad = copy.deepcopy(self.document)
        bad["screen_document"]["screens"][0]["widgets"][0]["width"] = 999
        with self.assertRaisesRegex(ProfileFormatError, "screen_document"):
            validate_profile(bad)


if __name__ == "__main__":
    unittest.main()
