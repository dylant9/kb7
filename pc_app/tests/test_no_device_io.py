from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoDeviceIoTests(unittest.TestCase):
    def test_no_live_device_libraries_or_paths(self) -> None:
        forbidden = ("hidraw", "hidapi", "pyusb", "/dev/", "libusb", "serial.Serial")
        for path in (ROOT / "kb7studio").rglob("*.py"):
            source = path.read_text().lower()
            for needle in forbidden:
                self.assertNotIn(needle.lower(), source, f"{needle} in {path}")

    def test_browser_has_no_live_hardware_or_network_api(self) -> None:
        forbidden = (
            "navigator.hid", "navigator.usb", "navigator.serial", "webusb",
            "xmlhttprequest", "websocket(", "fetch(",
        )
        for path in (ROOT / "web").rglob("*"):
            if path.suffix not in {".html", ".js"}:
                continue
            source = path.read_text().lower()
            for needle in forbidden:
                self.assertNotIn(needle, source, f"{needle} in {path}")

    def test_browser_import_is_validate_then_commit_and_has_csp(self) -> None:
        script = (ROOT / "web" / "app.js").read_text()
        html = (ROOT / "web" / "index.html").read_text()
        self.assertIn("validateScreens(parsed);\n        doc = parsed;", script)
        self.assertNotIn("doc = parsed;\n        validateScreens();", script)
        self.assertIn("background:${esc(item.background)}", script)
        self.assertIn("background:${esc(widget.foreground)}", script)
        self.assertIn('Content-Security-Policy', html)
        self.assertIn("connect-src 'none'", html)

    def test_browser_geometry_and_color_parity_guards(self) -> None:
        script = (ROOT / "web" / "app.js").read_text()
        self.assertIn("x: clamp(x, 0, 480 - width)", script)
        self.assertIn("y: clamp(y, 0, 800 - height)", script)
        self.assertIn("Math.floor((value >> 11 & 31) * 255 / 31)", script)

    def test_visible_editor_chrome_has_no_product_branding(self) -> None:
        html = (ROOT / "web" / "index.html").read_text()
        for legacy_label in (
            "KB7 Studio", "COMMAND DISPLAY", ">TB<", "NEON CONTROL", "No KB7",
        ):
            self.assertNotIn(legacy_label, html)

        sample_text = "\n".join(path.read_text() for path in (ROOT / "samples").glob("*.json"))
        for legacy_label in ("Neon Control", "Command Center", "COMMAND CENTER", '"AURORA"'):
            self.assertNotIn(legacy_label, sample_text)

    def test_keyboard_preview_models_the_modified_tkl_geometry(self) -> None:
        script = (ROOT / "web" / "app.js").read_text()
        styles = (ROOT / "web" / "styles.css").read_text()
        self.assertIn('physical.dataset.layout = "modified-tkl-78"', script)
        self.assertIn('key("RIGHTSHIFT", "Shift", 2.75)', script)
        self.assertIn('key("SPACE", "Space", 6.25)', script)
        self.assertIn('const ARROW_KEYS = [key("UP", "↑")', script)
        self.assertIn(".keyboard-mini-display", styles)
        self.assertIn(".arrow-up { grid-column: 2; grid-row: 1; }", styles)


if __name__ == "__main__":
    unittest.main()
