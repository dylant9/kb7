from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CDramTests(unittest.TestCase):
    def test_true_training_timeout_cannot_reach_march_test(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-dram-") as temporary:
            executable = Path(temporary) / "dram-test"
            subprocess.run([
                compiler, "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-fno-builtin", "-DKB7_HOST_TEST", "-DKB7_ENABLE_UNVERIFIED_DRAM_INIT=1",
                "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/dram_host.c"),
                str(ROOT / "replacement_fw/drivers/dram.c"),
                "-o", str(executable),
            ], check=True)
            result = subprocess.run([str(executable)], check=False)
            if result.returncode == 77:
                self.skipTest("DRAM register test addresses are already mapped")
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
