from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CTimerTests(unittest.TestCase):
    def test_tick_delay_is_wrap_safe_and_requires_runtime_clock(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-timer-") as temporary:
            executable = Path(temporary) / "timer-test"
            subprocess.run([
                compiler, "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-fno-builtin", "-DKB7_HOST_TEST",
                "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/timer_host.c"),
                str(ROOT / "replacement_fw/drivers/timer.c"),
                "-o", str(executable),
            ], check=True)
            result = subprocess.run([str(executable)], check=False)
            if result.returncode == 77:
                self.skipTest("runtime API test address is already mapped")
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
