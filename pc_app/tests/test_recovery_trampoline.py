"""Offline checks for the default-off preserved-loader re-entry proof."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "replacement_fw"
TRAMPOLINE_SHA256 = (
    "43bde11ee9089c930b8e67c6b7d569aec736d719f59f24c6b207d80309a2f539"
)
RELOCATOR_SHA256 = (
    "a8c82aa423cc089a563fed7bf2f319f39b2945addf065b47849c04c4d7c793eb"
)


def run(*arguments: str) -> str:
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


class RecoveryTrampolineTests(unittest.TestCase):
    def test_trampoline_is_exact_self_contained_thumb_blob(self) -> None:
        source = FIRMWARE / "drivers" / "recovery_trampoline.S"
        with tempfile.TemporaryDirectory() as temporary:
            object_path = Path(temporary) / "recovery_trampoline.o"
            binary_path = Path(temporary) / "recovery_trampoline.bin"
            relocator_path = Path(temporary) / "recovery_relocator.bin"
            run(
                "arm-none-eabi-gcc",
                "-mcpu=cortex-m3",
                "-mthumb",
                "-c",
                str(source),
                "-o",
                str(object_path),
            )
            run(
                "arm-none-eabi-objcopy",
                "--dump-section",
                f".text.kb7_loader_trampoline={binary_path}",
                str(object_path),
            )
            raw = binary_path.read_bytes()
            self.assertEqual(len(raw), 72)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), TRAMPOLINE_SHA256)
            run(
                "arm-none-eabi-objcopy",
                "--dump-section",
                f".text.kb7_loader_relocator={relocator_path}",
                str(object_path),
            )
            relocator = relocator_path.read_bytes()
            self.assertEqual(len(relocator), 84)
            self.assertEqual(
                hashlib.sha256(relocator).hexdigest(), RELOCATOR_SHA256
            )

            symbols = run("arm-none-eabi-readelf", "-sW", str(object_path))
            self.assertRegex(
                symbols,
                r"\b00000000\s+72\s+OBJECT\s+GLOBAL\s+DEFAULT\s+\d+\s+"
                r"kb7_loader_trampoline_blob_start\b",
            )
            self.assertRegex(
                symbols,
                r"\b00000001\s+72\s+FUNC\s+GLOBAL\s+DEFAULT\s+\d+\s+"
                r"kb7_loader_trampoline_start\b",
            )
            self.assertRegex(
                symbols,
                r"\b00000001\s+84\s+FUNC\s+GLOBAL\s+DEFAULT\s+\d+\s+"
                r"kb7_loader_trampoline_relocate_and_enter\b",
            )
            relocations = run("arm-none-eabi-readelf", "-rW", str(object_path))
            self.assertIn("There are no relocations in this file", relocations)

            disassembly = run("arm-none-eabi-objdump", "-dr", str(object_path))
            for instruction in (
                "cmp.w\tr1, #65536",
                "cpsid\ti",
                "ldr\tr2, [r3, r0]",
                "str\tr2, [r0, #0]",
                "dsb\tsy",
                "and.w\tr1, r1, #1792",
            ):
                self.assertIn(instruction, disassembly)
            self.assertNotRegex(disassembly, r"\bblx?\b")
            for literal in ("60001000", "00010000", "e000ed0c", "05fa0004"):
                self.assertIn(literal, disassembly)

            relocator_disassembly = disassembly[
                disassembly.index("<kb7_loader_trampoline_relocate_and_enter>:"):
                disassembly.index("Disassembly of section .text.kb7_loader_trampoline")
            ]
            for instruction in (
                "mrs\tr2, MSP",
                "cmp\tr1, #192",
                "cmp.w\tr2, #256",
                "sub.w\tr2, r2, #256",
                "ldrb.w\tr3, [r0], #1",
                "strb.w\tr3, [r2], #1",
                "bx\tip",
                "1803e000",
                "1803f5c0",
            ):
                self.assertIn(instruction, relocator_disassembly)
            self.assertNotRegex(
                relocator_disassembly,
                r"\b(?:push|pop|bl|blx)\b",
            )

    def test_copy_and_reset_model_preserves_source_and_mailbox(self) -> None:
        source = bytes((index * 29 + 7) & 0xFF for index in range(0x10000))
        pram = bytearray(b"\xa5" * 0x10000)
        mailbox = {0x20000FFC: 0x73207320}
        aircr_before = 0x00000300

        for offset in range(0, 0x10000, 4):
            pram[offset:offset + 4] = source[offset:offset + 4]
        aircr_after = (aircr_before & 0x700) | 0x05FA0004

        self.assertEqual(bytes(pram), source)
        self.assertEqual(mailbox[0x20000FFC], 0x73207320)
        self.assertEqual(aircr_after, 0x05FA0304)

    def test_feature_defaults_off_and_proof_enters_before_application(self) -> None:
        config = (FIRMWARE / "include" / "kb7" / "config.h").read_text(
            encoding="utf-8"
        )
        startup = (FIRMWARE / "core0" / "startup.c").read_text(encoding="utf-8")
        recovery = (FIRMWARE / "drivers" / "recovery.c").read_text(
            encoding="utf-8"
        )
        regs = (FIRMWARE / "include" / "kb7" / "regs.h").read_text(
            encoding="utf-8"
        )

        self.assertIn("#define KB7_ENABLE_UNVERIFIED_LOADER_REENTRY 0", config)
        self.assertIn("#define KB7_BUILD_LOADER_REENTRY_PROOF 0", config)
        proof = startup.index("#if KB7_BUILD_LOADER_REENTRY_PROOF")
        entry = startup.index("kb7_enter_loader();", proof)
        application = startup.index("core0_main();", entry)
        self.assertLess(entry, application)
        self.assertIn("kb7_loader_trampoline_blob_start", recovery)
        self.assertIn("trampoline_end <= trampoline_start", recovery)
        self.assertIn("trampoline_end - trampoline_start", recovery)
        self.assertNotIn(
            "kb7_loader_trampoline_blob_end -\n"
            "                 kb7_loader_trampoline_blob_start",
            recovery,
        )
        self.assertIn("kb7_loader_trampoline_relocate_and_enter", recovery)
        self.assertNotIn("kb7_memcpy(relocated", recovery)
        self.assertNotIn("SNC_SCB_AIRCR", recovery)
        for definition in (
            "KB7_LOADER_TRAMPOLINE_STACK_RESERVE UINT32_C(0x100)",
            "KB7_LOADER_TRAMPOLINE_MIN_STACK_GAP UINT32_C(0x40)",
            "KB7_LOADER_TRAMPOLINE_MAX_BYTES UINT32_C(0x0c0)",
            "KB7_LOADER_TRAMPOLINE_STACK_FLOOR UINT32_C(0x1803e000)",
            "KB7_CORE0_STACK_TOP UINT32_C(0x1803f5c0)",
        ):
            self.assertIn(definition, regs)

    def test_stock_active_watchdog_selection_is_not_inverted(self) -> None:
        startup = (FIRMWARE / "core0" / "startup.c").read_text(encoding="utf-8")
        selection = startup[
            startup.index("const uint32_t active_wdt"):
            startup.index("KB7_MMIO32(active_wdt", startup.index("const uint32_t active_wdt"))
        ]
        self.assertIn("? SNC_WDT1_BASE", selection)
        self.assertIn(": SNC_WDT0_BASE", selection)
        disable0 = startup.index(
            "SNC_WDT0_BASE + SNC_WDT_CONFIGURATION", selection.index(": SNC_WDT0_BASE")
        )
        disable1 = startup.index(
            "SNC_WDT1_BASE + SNC_WDT_CONFIGURATION", disable0
        )
        self.assertLess(disable0, disable1)


if __name__ == "__main__":
    unittest.main()
