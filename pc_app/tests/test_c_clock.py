from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CClockTests(unittest.TestCase):
    def test_recovered_clock_sentinels_and_divider(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-clock-") as temporary:
            executable = Path(temporary) / "clock-test"
            subprocess.run([
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-DKB7_HOST_TEST",
                "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/clock_host.c"),
                str(ROOT / "replacement_fw/drivers/clock.c"),
                "-o", str(executable),
            ], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
