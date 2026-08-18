from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CStorageTests(unittest.TestCase):
    def test_payload_crc_fallback_and_incremental_crc(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-storage-") as temporary:
            executable = Path(temporary) / "storage-test"
            subprocess.run([
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fno-builtin",
                "-DKB7_HOST_TEST",
                "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/storage_host.c"),
                str(ROOT / "replacement_fw/core1/storage.c"),
                str(ROOT / "replacement_fw/common/crc32.c"),
                str(ROOT / "replacement_fw/common/memory.c"),
                "-o", str(executable),
            ], check=True)
            result = subprocess.run([str(executable)], check=False)
            if result.returncode == 77:
                self.skipTest("runtime API test address is already mapped")
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
