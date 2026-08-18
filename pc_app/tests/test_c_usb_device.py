from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CUsbDeviceTests(unittest.TestCase):
    def _build_and_run(self, test: str, defines: list[str]) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-usb-device-") as temporary:
            executable = Path(temporary) / test
            subprocess.run([
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-DKB7_HOST_TEST",
                "-DKB7_USB_TEST", *defines, "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / f"replacement_fw/tests/{test}.c"),
                str(ROOT / "replacement_fw/core0/usb.c"),
                str(ROOT / "replacement_fw/common/memory.c"),
                "-o", str(executable),
            ], check=True)
            subprocess.run([str(executable)], check=True)

    def test_descriptor_ep0_queue_and_controller_model(self) -> None:
        self._build_and_run("usb_device_host", [
            "-DKB7_USB_VENDOR_ID=0xcafe", "-DKB7_USB_PRODUCT_ID=0x4001",
            "-DKB7_USB_BOARD_PROFILE_VERIFIED=1",
        ])

    def test_public_profile_does_no_mmio(self) -> None:
        self._build_and_run("usb_failclosed_host", [])


if __name__ == "__main__":
    unittest.main()
