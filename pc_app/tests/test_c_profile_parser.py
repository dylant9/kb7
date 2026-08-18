from __future__ import annotations

import ctypes
import json
import random
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from kb7studio.profile import ProfileFormatError
from kb7studio.profile_binary import compile_profile_binary, parse_profile_binary

ROOT = Path(__file__).resolve().parents[2]


class CProfileParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory(prefix="kb7-c-profile-parser-")
        library = Path(cls.temporary.name) / "libkb7profile.so"
        subprocess.run([
            compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-DKB7_HOST_TEST",
            "-fPIC", "-shared", "-I", str(ROOT / "replacement_fw/include"),
            str(ROOT / "replacement_fw/core1/profile_blob.c"),
            str(ROOT / "replacement_fw/drivers/input_profiles.c"),
            str(ROOT / "replacement_fw/drivers/input_pipeline.c"),
            str(ROOT / "replacement_fw/drivers/keymap.c"),
            str(ROOT / "replacement_fw/drivers/hall_policy.c"),
            str(ROOT / "replacement_fw/common/memory.c"),
            str(ROOT / "replacement_fw/common/crc32.c"),
            "-o", str(library),
        ], check=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.kb7_profile_parse.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                   ctypes.c_void_p]
        cls.library.kb7_profile_parse.restype = ctypes.c_int
        document = json.loads((ROOT / "pc_app/samples/offline-example-profile.json").read_text())
        document["lighting"]["per_key"] = {}
        cls.blob = compile_profile_binary(document)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def parse(self, blob: bytes) -> int:
        source = ctypes.create_string_buffer(blob)
        output = ctypes.create_string_buffer(16384)
        return self.library.kb7_profile_parse(source, len(blob), output)

    def python_accepts(self, blob: bytes) -> bool:
        try:
            parse_profile_binary(blob)
            return True
        except ProfileFormatError:
            return False

    def test_c_accepts_python_compiler_output(self) -> None:
        self.assertEqual(self.parse(self.blob), 0)

    def test_c_accepts_four_authored_profile_records(self) -> None:
        document = json.loads(
            (ROOT / "pc_app/samples/offline-example-profile.json").read_text())
        document["lighting"]["per_key"] = {}
        profiles = []
        for index in range(4):
            profile = json.loads(json.dumps(document))
            profile["name"] = f"Profile {index + 1}"
            profile["firmware"] = {
                "layout_variant": index,
                "initial_mode": "game" if index == 1 else "primary",
                "actions": {"game": {"A": {"type": "keyboard", "usage": "B"}}},
            }
            profiles.append(profile)
        blob = compile_profile_binary({"format": "kb7-profile-set-v1",
                                       "active_profile": 1, "profiles": profiles})
        self.assertEqual(self.parse(blob), 0)

    def test_c_rejects_truncation_and_corruption(self) -> None:
        self.assertNotEqual(self.parse(self.blob[:-1]), 0)
        changed = bytearray(self.blob)
        changed[-1] ^= 1
        self.assertNotEqual(self.parse(bytes(changed)), 0)

    def test_c_python_record_validation_parity(self) -> None:
        randomizer = random.Random(0x4B425031)
        corpus = [self.blob[:length] for length in range(0, 49)]
        for _ in range(500):
            changed = bytearray(self.blob)
            for _ in range(randomizer.randrange(1, 6)):
                offset = randomizer.randrange(48, len(changed))
                changed[offset] ^= randomizer.randrange(1, 256)
            struct.pack_into("<I", changed, 12, zlib.crc32(changed[48:]) & 0xFFFFFFFF)
            corpus.append(bytes(changed))
        actions = 48 + 420
        fn = 0x4E
        targeted = (
            (actions + fn * 4, struct.pack("<HBB", 4, 2, 0)),
            (actions + fn * 4, struct.pack("<HBB", 0x00CD, 3, 0)),
            (actions + fn * 4, struct.pack("<HBB", 0, 4, 1)),
            (actions + (85 + fn) * 4, struct.pack("<HBB", 0, 4, 2)),
            (actions + fn * 4, struct.pack("<HBB", 0, 1, 0)),
        )
        for offset, replacement in targeted:
            changed = bytearray(self.blob)
            changed[offset:offset + 4] = replacement
            struct.pack_into("<I", changed, 12, zlib.crc32(changed[48:]) & 0xFFFFFFFF)
            corpus.append(bytes(changed))
        for index, blob in enumerate(corpus):
            with self.subTest(index=index):
                self.assertEqual(self.parse(blob) == 0, self.python_accepts(blob))


if __name__ == "__main__":
    unittest.main()
