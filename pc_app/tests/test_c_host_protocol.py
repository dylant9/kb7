from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CHostProtocolTests(unittest.TestCase):
    def test_validation_distinguishes_version_and_crc_failures(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-protocol-") as temporary:
            executable = Path(temporary) / "protocol-test"
            subprocess.run([
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fno-builtin",
                "-DKB7_HOST_TEST",
                "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/host_protocol_host.c"),
                str(ROOT / "replacement_fw/common/host_protocol.c"),
                str(ROOT / "replacement_fw/common/crc32.c"),
                str(ROOT / "replacement_fw/common/memory.c"),
                "-o", str(executable),
            ], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
