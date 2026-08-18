from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CCompletionComponentTests(unittest.TestCase):
    def test_clean_room_components(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        common = [
            ROOT / "replacement_fw/common/memory.c",
            ROOT / "replacement_fw/common/crc32.c",
        ]
        cases = {
            "action_bar": ["tests/action_bar_host.c", "drivers/action_bar.c", "common/memory.c"],
            "encoder": ["tests/encoder_host.c", "drivers/encoder.c"],
            "input_pipeline": ["tests/input_pipeline_host.c", "drivers/input_pipeline.c",
                               "drivers/keymap.c", "drivers/hall_policy.c", *common],
            "input_profiles": ["tests/input_profiles_host.c", "drivers/input_profiles.c",
                               "drivers/input_pipeline.c", "drivers/keymap.c",
                               "drivers/hall_policy.c", *common],
            "lighting": ["tests/lighting_host.c", "drivers/lighting.c"],
            "lcd": ["tests/lcd_host.c", "drivers/lcd.c"],
            "rgb": ["tests/rgb_host.c", "drivers/rgb.c", "common/memory.c"],
            "touch": ["tests/touch_host.c", "drivers/touch.c"],
            "mcu2_protocol": ["tests/mcu2_protocol_host.c", "drivers/mcu2.c",
                              "common/memory.c"],
        }
        base = ROOT / "replacement_fw"
        with tempfile.TemporaryDirectory(prefix="kb7-c-completion-") as temporary:
            for name, sources in cases.items():
                with self.subTest(component=name):
                    executable = Path(temporary) / name
                    resolved = [str(item if isinstance(item, Path) else base / item)
                                for item in sources]
                    subprocess.run([
                        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-DKB7_HOST_TEST", "-DKB7_ENABLE_ENCODER=1",
                        "-I", str(base / "include"), *resolved,
                        "-o", str(executable),
                    ], check=True)
                    subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
