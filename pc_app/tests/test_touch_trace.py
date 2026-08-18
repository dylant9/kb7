from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATH = ROOT / "web" / "touch-trace.js"


class TouchTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is required for browser math tests")

    def evaluate(self, expression: str):
        script = (
            f"const m=require({json.dumps(str(MATH))});"
            f"process.stdout.write(JSON.stringify({expression}));"
        )
        result = subprocess.run(
            [self.node, "-e", script], check=True, capture_output=True, text=True,
        )
        return json.loads(result.stdout)

    def test_pointer_coordinates_map_to_native_display_pixels(self) -> None:
        rectangle = "{left:100,top:50,width:300,height:500}"
        self.assertEqual(self.evaluate(f"m.coordinate(100,50,{rectangle})"), {"x": 0, "y": 0})
        self.assertEqual(self.evaluate(f"m.coordinate(250,300,{rectangle})"), {"x": 240, "y": 400})
        self.assertEqual(self.evaluate(f"m.coordinate(400,550,{rectangle})"), {"x": 479, "y": 799})

    def test_radial_deadzone_and_joystick_extents(self) -> None:
        center = self.evaluate("m.vector(240,400,240,400,.08)")
        within_deadzone = self.evaluate("m.vector(250,400,240,400,.08)")
        right = self.evaluate("m.vector(479,400,240,400,.08)")
        up = self.evaluate("m.vector(240,0,240,400,.08)")
        corner = self.evaluate("m.vector(479,799,240,400,.08)")

        self.assertEqual((center["x"], center["y"], center["magnitude"]), (0, 0, 0))
        self.assertEqual(within_deadzone["magnitude"], 0)
        self.assertAlmostEqual(right["x"], 1.0, places=6)
        self.assertAlmostEqual(right["y"], 0.0, places=6)
        self.assertAlmostEqual(up["y"], -1.0, places=6)
        self.assertAlmostEqual(corner["magnitude"], 1.0, places=6)
        self.assertAlmostEqual(corner["x"], 2 ** -0.5, places=6)
        self.assertAlmostEqual(corner["y"], 2 ** -0.5, places=6)

    def test_trace_mode_is_exposed_by_the_display_editor(self) -> None:
        html = (ROOT / "web" / "index.html").read_text()
        script = (ROOT / "web" / "app.js").read_text()
        self.assertLess(html.index('src="touch-trace.js"'), html.index('src="app.js"'))
        self.assertIn('data-mode="trace"', html)
        self.assertIn('format: "touch-trace-v1"', script)
        self.assertIn('scope: "browser-pointer-events-only"', script)


if __name__ == "__main__":
    unittest.main()
