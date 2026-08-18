from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CUiTests(unittest.TestCase):
    def test_touch_phases_slider_coordinates_and_toggle_state(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-ui-") as temporary:
            executable = Path(temporary) / "ui-test"
            subprocess.run([
                compiler, "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-DKB7_HOST_TEST", "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/ui_host.c"),
                str(ROOT / "replacement_fw/ui/renderer.c"),
                str(ROOT / "replacement_fw/ui/screen_parser.c"),
                str(ROOT / "replacement_fw/common/crc32.c"),
                "-o", str(executable),
            ], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
