from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CHostServerTests(unittest.TestCase):
    def test_atomic_write_fallback_read_select_and_reset(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-host-server-") as temporary:
            executable = Path(temporary) / "host-server-test"
            subprocess.run([
                compiler, "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fno-builtin",
                "-DKB7_HOST_TEST", "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/host_server_host.c"),
                str(ROOT / "replacement_fw/core1/host_server.c"),
                str(ROOT / "replacement_fw/core1/storage.c"),
                str(ROOT / "replacement_fw/ui/screen_parser.c"),
                str(ROOT / "replacement_fw/common/host_protocol.c"),
                str(ROOT / "replacement_fw/common/crc32.c"),
                str(ROOT / "replacement_fw/common/memory.c"),
                "-o", str(executable),
            ], check=True)
            result = subprocess.run([str(executable)], check=False)
            if result.returncode == 77:
                self.skipTest("fixed-address host test mappings are unavailable")
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
