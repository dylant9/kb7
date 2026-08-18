from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CMcu2Tests(unittest.TestCase):
    def test_a3_samples_are_not_treated_as_a_request_trailer(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-mcu2-") as temporary:
            executable = Path(temporary) / "mcu2-test"
            subprocess.run([
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fno-builtin",
                "-DKB7_HOST_TEST", "-DKB7_ENABLE_MCU2=1",
                "-DKB7_MCU2_BOARD_PROFILE_VERIFIED=1",
                "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/mcu2_host.c"),
                str(ROOT / "replacement_fw/drivers/mcu2.c"),
                str(ROOT / "replacement_fw/drivers/gpio.c"),
                str(ROOT / "replacement_fw/common/memory.c"),
                "-o", str(executable),
            ], check=True)
            result = subprocess.run([str(executable)], check=False)
            if result.returncode == 77:
                self.skipTest("MCU2 register test address is already mapped")
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
