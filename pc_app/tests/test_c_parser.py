from __future__ import annotations

import ctypes
import json
import random
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from kb7studio.format import HEADER, SCREEN, WIDGET, ScreenFormatError, compile_document, crc32, parse_binary

ROOT = Path(__file__).resolve().parents[2]


class _Store(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_void_p), ("length", ctypes.c_size_t),
                ("header", ctypes.c_void_p)]


class CParserParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary = tempfile.TemporaryDirectory(prefix="kb7-c-parser-")
        library = Path(cls.temporary.name) / "libkb7parser.so"
        subprocess.run([
            compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-DKB7_HOST_TEST",
            "-fPIC", "-shared",
            "-I", str(ROOT / "replacement_fw/include"),
            str(ROOT / "replacement_fw/ui/screen_parser.c"),
            str(ROOT / "replacement_fw/common/crc32.c"),
            "-o", str(library),
        ], check=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.kb7_screen_parse.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                  ctypes.POINTER(_Store)]
        cls.library.kb7_screen_parse.restype = ctypes.c_int
        document = json.loads((ROOT / "pc_app/samples/offline-example.json").read_text())
        cls.blob = compile_document(document)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def c_accepts(self, blob: bytes) -> bool:
        buffer = ctypes.create_string_buffer(blob)
        store = _Store()
        return self.library.kb7_screen_parse(buffer, len(blob), ctypes.byref(store)) == 0

    def python_accepts(self, blob: bytes) -> bool:
        try:
            parse_binary(blob)
            return True
        except ScreenFormatError:
            return False

    def test_c_accepts_canonical_compiler_output(self) -> None:
        self.assertTrue(self.c_accepts(self.blob))

    def test_referenced_strings_must_begin_and_end_on_utf8_boundaries(self) -> None:
        blob = bytearray(compile_document({
            "format": "kb7-screen-v1", "boot_screen": 1,
            "screens": [{"id": 1, "name": "é", "widgets": []}],
        }))
        # Keep the complete string pool valid, but reference only the
        # continuation byte of this two-byte codepoint.
        struct.pack_into("<I", blob, HEADER.size + 8, 1)
        struct.pack_into("<H", blob, HEADER.size + 12, 1)
        struct.pack_into("<I", blob, 12, crc32(blob[HEADER.size:]))
        malformed = bytes(blob)
        self.assertFalse(self.python_accepts(malformed))
        self.assertFalse(self.c_accepts(malformed))

    def test_mutation_corpus_has_exact_python_c_parity(self) -> None:
        randomizer = random.Random(0xC0DEC0DE)
        corpus = [self.blob[:length] for length in range(len(self.blob))]
        for _ in range(1500):
            mutated = bytearray(self.blob)
            for _ in range(randomizer.randrange(1, 8)):
                mutated[randomizer.randrange(len(mutated))] ^= randomizer.randrange(1, 256)
            corpus.append(bytes(mutated))
        widget_offset = HEADER.size + 2 * SCREEN.size
        for action, arg0 in ((0x11, 5), (0x20, 4), (0x30, 0), (0x31, 0)):
            mutated = bytearray(self.blob)
            struct.pack_into("<H", mutated, widget_offset + 22, 0)
            mutated[widget_offset + 24] = action
            mutated[widget_offset + 25] = 0
            struct.pack_into("<H", mutated, widget_offset + 26, arg0)
            struct.pack_into("<I", mutated, widget_offset + 28, 0)
            struct.pack_into("<I", mutated, 12, crc32(mutated[HEADER.size:]))
            corpus.append(bytes(mutated))
        for index, blob in enumerate(corpus):
            with self.subTest(index=index, length=len(blob)):
                self.assertEqual(self.c_accepts(blob), self.python_accepts(blob))


if __name__ == "__main__":
    unittest.main()
