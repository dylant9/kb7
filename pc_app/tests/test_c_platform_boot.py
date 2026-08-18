from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CPlatformBootTests(unittest.TestCase):
    def test_platform_helpers_pinmux_flash_bounds_and_xip_read(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-platform-") as temporary:
            executable = Path(temporary) / "platform-test"
            subprocess.run([
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-DKB7_HOST_TEST", "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/platform_boot_host.c"),
                str(ROOT / "replacement_fw/drivers/clock.c"),
                str(ROOT / "replacement_fw/drivers/gpio.c"),
                str(ROOT / "replacement_fw/drivers/timer.c"),
                str(ROOT / "replacement_fw/drivers/flash.c"),
                str(ROOT / "replacement_fw/common/memory.c"),
                "-o", str(executable),
            ], check=True)
            result = subprocess.run([str(executable)], check=False)
            if result.returncode == 77:
                self.skipTest("platform test addresses are already mapped")
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
