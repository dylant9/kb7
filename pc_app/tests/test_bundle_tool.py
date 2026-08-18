from __future__ import annotations

import importlib.util
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "build_firmware_bundle", ROOT / "tools" / "build_firmware_bundle.py"
)
assert SPEC is not None and SPEC.loader is not None
BUNDLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUNDLE)


class BundleToolTests(unittest.TestCase):
    @staticmethod
    def _fake_stock() -> dict[str, bytes]:
        core0 = bytes(0x13C)
        core1 = bytes(0x100)
        manifest = bytearray(0x1000)
        manifest[:8] = b"SN_FWIN\0"
        records = (
            (0, 0x60011000, len(core0), BUNDLE.fwin_checksum(core0)),
            (0x10000000, 0x60021000, len(core1), BUNDLE.fwin_checksum(core1)),
            (0x60100000, 0x60100000, BUNDLE.REGION2_END - BUNDLE.REGION2_START, 3),
            (0, 0, 0, 0),
        )
        for offset, record in zip((0x20, 0x30, 0x40, 0x50), records):
            struct.pack_into("<IIII", manifest, offset, *record)
        return {"header": bytes(0x1000), "loader": bytes(0xF000),
                "manifest": bytes(manifest), "core0": core0, "core1": core1}

    @staticmethod
    def _fake_extract(_elf: Path, expected_vma: int, _maximum: int,
                      _objcopy: str, _readelf: str, _nm: str,
                      destination: Path) -> dict[str, object]:
        if expected_vma == BUNDLE.CORE0_VMA:
            raw = bytearray(0x13C)
            struct.pack_into("<II", raw, 0, BUNDLE.CORE0_STACK, 0x101)
            entry = 0x101
        else:
            raw = bytearray(0x80)
            entry = BUNDLE.CORE1_VMA + 1
        destination.write_bytes(raw)
        return {"entry": f"0x{entry:08x}", "raw_length": len(raw),
                "elf_sha256": "0" * 64, "raw_sha256": BUNDLE.digest(raw)}

    def test_chunk_checksum_and_bounds(self) -> None:
        data = bytes(range(256)) * 300
        expected = (
            zlib.crc32(data[:0x10000]) + zlib.crc32(data[0x10000:])
        ) & 0xFFFFFFFF
        self.assertEqual(BUNDLE.fwin_checksum(data), expected)
        self.assertTrue(BUNDLE.bounded_operation(0x10000, 0x1000))
        self.assertTrue(BUNDLE.bounded_operation(0x11000, 0xF35C))
        self.assertFalse(BUNDLE.bounded_operation(0x0, 0x1000))
        self.assertFalse(BUNDLE.bounded_operation(0xFF00, 0x200))
        self.assertFalse(BUNDLE.bounded_operation(0xFFFF0, 0x20))
        self.assertFalse(BUNDLE.bounded_operation(0x100000, 0x1000))

    def test_expected_manifest_layout(self) -> None:
        manifest = bytearray(0x1000)
        manifest[:8] = b"SN_FWIN\0"
        records = (
            (0x00000000, 0x60011000, 0xF35C, 1),
            (0x10000000, 0x60021000, 0x6B168, 2),
            (0x60100000, 0x60100000, 0x146AF8C, 3),
            (0, 0, 0, 0),
        )
        for offset, record in zip((0x20, 0x30, 0x40, 0x50), records):
            struct.pack_into("<IIII", manifest, offset, *record)
        parsed = BUNDLE.manifest_regions(bytes(manifest))
        self.assertEqual(parsed[1]["load"], 0x10000000)
        self.assertEqual(parsed[2]["length"], 0x146AF8C)

    def test_load_segments_must_start_at_and_stay_inside_manifest_region(self) -> None:
        canonical = """
  LOAD 0x001000 0x10000000 0x10000000 0x001000 0x001000 R E 0x1000
  LOAD 0x002000 0x18020000 0x10001000 0x000004 0x000100 RW  0x1000
"""
        self.assertEqual(BUNDLE.validate_load_ranges(canonical, 0x10000000, 0x2000),
                         0x1004)
        shifted = canonical.replace(
            "0x10000000 0x10000000", "0x10000004 0x10000004", 1)
        with self.assertRaisesRegex(BUNDLE.BundleError, "lowest file-backed"):
            BUNDLE.validate_load_ranges(shifted, 0x10000000, 0x2000)
        outside = canonical.replace(
            "0x10001000 0x000004", "0x10001fff 0x000004")
        with self.assertRaisesRegex(BUNDLE.BundleError, "outside"):
            BUNDLE.validate_load_ranges(outside, 0x10000000, 0x2000)

    def test_rejects_manifest_overlap(self) -> None:
        manifest = bytearray(0x1000)
        struct.pack_into("<IIII", manifest, 0x20, 0, 0x60011000, 1, 0)
        struct.pack_into("<IIII", manifest, 0x30, 0x10000000, 0x60021000, 1, 0)
        struct.pack_into("<IIII", manifest, 0x40, 0x60100000, 0x60100000, 1, 0)
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.manifest_regions(bytes(manifest))

    def test_build_declares_every_output_and_programs_manifest_last(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kb7-bundle-test-") as temporary:
            root = Path(temporary)
            core0_elf = root / "core0.elf"
            core1_elf = root / "core1.elf"
            core0_elf.write_bytes(b"elf0")
            core1_elf.write_bytes(b"elf1")
            output = root / "bundle"
            with mock.patch.object(BUNDLE, "load_stock", return_value=self._fake_stock()), \
                 mock.patch.object(BUNDLE, "inspect_and_extract", side_effect=self._fake_extract), \
                 mock.patch.object(BUNDLE.shutil, "which", return_value="tool"):
                result = BUNDLE.build(root, core0_elf, core1_elf, output, "arm-none-eabi-")
            self.assertEqual(set(path.name for path in output.iterdir()),
                             set(result["files"]) | {"audit.json", "flash-plan.json"})
            plan = __import__("json").loads((output / "flash-plan.json").read_text())
            self.assertEqual(plan["program"][-1]["source"], "replacement-manifest.bin")
            self.assertIn("not atomic", plan["power_loss_warning"])
            self.assertTrue(plan["operation_order_is_normative"])
            self.assertTrue(all(int(item["offset"], 0) % 0x1000 == 0 and
                                item["length"] % 0x1000 == 0
                                for item in plan["erase"]))
            self.assertEqual(plan["erase"][-1]["offset"], "0x00010000")
            self.assertEqual([item["operation"] for item in plan["operations"][-3:]],
                             ["erase", "program", "readback_sha256"])
            self.assertEqual(plan["operations"][-2]["source"],
                             "replacement-manifest.bin")

    def test_build_rejects_noncanonical_core1_entry(self) -> None:
        def wrong_entry(*args: object, **kwargs: object) -> dict[str, object]:
            result = self._fake_extract(*args, **kwargs)
            if int(str(result["entry"]), 0) >= BUNDLE.CORE1_VMA:
                result["entry"] = "0x10000005"
            return result

        with tempfile.TemporaryDirectory(prefix="kb7-bundle-entry-") as temporary:
            root = Path(temporary)
            core0_elf = root / "core0.elf"
            core1_elf = root / "core1.elf"
            core0_elf.write_bytes(b"elf0")
            core1_elf.write_bytes(b"elf1")
            with mock.patch.object(BUNDLE, "load_stock", return_value=self._fake_stock()), \
                 mock.patch.object(BUNDLE, "inspect_and_extract", side_effect=wrong_entry), \
                 mock.patch.object(BUNDLE.shutil, "which", return_value="tool"), \
                 self.assertRaisesRegex(BUNDLE.BundleError, "exactly 0x10000001"):
                BUNDLE.build(root, core0_elf, core1_elf, root / "bundle",
                             "arm-none-eabi-")


if __name__ == "__main__":
    unittest.main()
