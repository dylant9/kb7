from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoDeviceIoTests(unittest.TestCase):
    def test_no_live_device_libraries_or_paths(self) -> None:
        forbidden = ("hidraw", "hidapi", "pyusb", "/dev/", "libusb", "serial.Serial")
        for path in (ROOT / "kb7studio").glob("*.py"):
            source = path.read_text().lower()
            for needle in forbidden:
                self.assertNotIn(needle.lower(), source, f"{needle} in {path}")

    def test_browser_has_no_live_hardware_or_network_api(self) -> None:
        forbidden = (
            "navigator.hid", "navigator.usb", "navigator.serial", "webusb",
            "xmlhttprequest", "websocket(", "fetch(",
        )
        for path in (ROOT / "web").glob("*"):
            if path.suffix not in {".html", ".js"}:
                continue
            source = path.read_text().lower()
            for needle in forbidden:
                self.assertNotIn(needle, source, f"{needle} in {path}")


if __name__ == "__main__":
    unittest.main()
