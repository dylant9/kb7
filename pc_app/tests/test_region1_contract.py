"""Tests for the read-only stock Core0/region-1 boot-contract verifier.

The fixtures are synthetic images that reproduce only the pinned instruction
shapes at the pinned offsets.  No stock bytes are embedded; the identity and
closure hashes of the synthetic profile are recomputed so that the semantic
checks, not the hash pins, are what these tests exercise.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_region1_contract", ROOT / "tools" / "verify_region1_contract.py")
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

REENTRY_SPEC = importlib.util.spec_from_file_location(
    "verify_loader_reentry_for_contract_tests",
    ROOT / "tools" / "verify_loader_reentry.py")
assert REENTRY_SPEC is not None and REENTRY_SPEC.loader is not None
REENTRY = importlib.util.module_from_spec(REENTRY_SPEC)
sys.modules[REENTRY_SPEC.name] = REENTRY
REENTRY_SPEC.loader.exec_module(REENTRY)

STOCK = VERIFIER.PROFILES["V1.22"]


def put16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", data, offset, value)


def put32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def put_bytes(data: bytearray, offset: int, value: str) -> None:
    raw = bytes.fromhex(value)
    data[offset:offset + len(raw)] = raw


def encode_bl(data: bytearray, offset: int, target: int) -> None:
    displacement = target - (offset + 4)
    assert displacement % 2 == 0 and -(1 << 24) <= displacement < (1 << 24)
    encoded = displacement & ((1 << 25) - 1)
    sign = (encoded >> 24) & 1
    i1 = (encoded >> 23) & 1
    i2 = (encoded >> 22) & 1
    j1 = ((~i1) & 1) ^ sign
    j2 = ((~i2) & 1) ^ sign
    put16(data, offset, 0xF000 | (sign << 10) | ((encoded >> 12) & 0x3FF))
    put16(data, offset + 2, 0xD000 | (j1 << 13) | (j2 << 11) | ((encoded >> 1) & 0x7FF))


def encode_ldr_literal(data: bytearray, offset: int, register: int,
                       literal_offset: int) -> None:
    pc = (offset + 4) & ~3
    displacement = literal_offset - pc
    assert displacement >= 0 and displacement % 4 == 0 and displacement // 4 <= 0xFF
    put16(data, offset, 0x4800 | (register << 8) | (displacement // 4))


def encode_movw_movt(data: bytearray, offset: int, register: int, value: int) -> None:
    for index, (opcode, half) in enumerate(((0xF240, value & 0xFFFF),
                                            (0xF2C0, value >> 16))):
        imm4 = half >> 12
        i = (half >> 11) & 1
        imm3 = (half >> 8) & 7
        imm8 = half & 0xFF
        put16(data, offset + index * 4, opcode | (i << 10) | imm4)
        put16(data, offset + index * 4 + 2, (imm3 << 12) | (register << 8) | imm8)


def synthetic_core0() -> bytearray:
    image = bytearray(STOCK.core0_size)
    # Vector table: stack top, reset, region-0 handlers, five region-1 handlers.
    put32(image, 0, STOCK.stack_top)
    put32(image, 4, STOCK.reset_offset + 1)
    for index in range(2, VERIFIER.VECTOR_COUNT):
        put32(image, index * 4, 0x32B)
    for index in STOCK.zero_vectors:
        put32(image, index * 4, 0)
    for index, handler in STOCK.region1_vectors:
        put32(image, index * 4, handler)
    put32(image, STOCK.usb_irq_vector[0] * 4, STOCK.usb_irq_vector[1])

    # Scatter entry: bl walker; bl runtime entry; adr r0; ldm; ... ; bx r3.
    base = STOCK.scatter_entry_offset
    encode_bl(image, base, base + 8)
    encode_bl(image, base + 4, STOCK.runtime_entry_offset)
    put_bytes(image, base + 8, "0aa090e8000c82448344aaf10107da4501d1")
    encode_bl(image, base + 0x1A, STOCK.runtime_entry_offset)
    put_bytes(image, base + 0x1E, "aff2090ebae80f0013f0010f18bffb1a43f001031847")
    put32(image, base + 0x34, STOCK.scatter_table_offset - (base + 0x34))
    put32(image, base + 0x38, STOCK.scatter_table_end - (base + 0x34))
    put_bytes(image, STOCK.decompress_handler, "10f8013b0a44")
    put_bytes(image, STOCK.copy_handler, "103a24bf78c878c1")
    put_bytes(image, STOCK.zero_handler, "0023002400250026103a")
    for index, entry in enumerate(STOCK.scatter_entries):
        struct.pack_into("<IIII", image, STOCK.scatter_table_offset + index * 16, *entry)

    # Runtime entry: bl stack setup; mov r1, r2; bl library init; bl veneer.
    base = STOCK.runtime_entry_offset
    encode_bl(image, base, STOCK.stack_setup_offset)
    put16(image, base + 4, 0x4611)
    encode_bl(image, base + 6, STOCK.runtime_library_init_offset)
    encode_bl(image, base + 10, STOCK.handoff_veneer_offset)
    put_bytes(image, base + 14, "01f041fb03b4fff7f2ff03bc07f015f8")
    # Reset handler.
    base = STOCK.reset_offset
    encode_movw_movt(image, base, 0, VERIFIER.VTOR)
    put_bytes(image, base + 8, "0068d0f800d0")
    encode_ldr_literal(image, base + 14, 0, 0x338)
    put16(image, base + 16, 0x4780)
    encode_ldr_literal(image, base + 18, 0, 0x33C)
    put16(image, base + 20, 0x4700)
    put32(image, 0x338, STOCK.hardware_init_offset + 1)
    put32(image, 0x33C, STOCK.scatter_entry_offset + 1)
    # Stack/heap descriptor and its pool.
    base = STOCK.stack_descriptor_offset
    for register in range(4):
        encode_ldr_literal(image, base + register * 2, register, 0x340 + register * 4)
    put16(image, base + 8, 0x4770)
    for offset, value in zip((0x340, 0x344, 0x348, 0x34C),
                             (STOCK.heap_base, STOCK.stack_top, STOCK.heap_limit,
                              STOCK.stack_limit)):
        put32(image, offset, value)
    # Stack setup: bl descriptor at +0x18, mov sp, r1 at +0x46, bx lr at +0x48.
    base = STOCK.stack_setup_offset
    encode_bl(image, base + 0x18, STOCK.stack_descriptor_offset)
    put16(image, base + 0x46, 0x468D)
    put16(image, base + 0x48, 0x4770)
    # Library init and the runtime library helpers are opaque returns.
    put16(image, STOCK.runtime_library_init_offset, 0x4770)
    # Handoff veneer.
    encode_movw_movt(image, STOCK.handoff_veneer_offset, 12, STOCK.region1_entry)
    put16(image, STOCK.handoff_veneer_offset + 8, 0x4760)
    # Hardware init: push; 0x28 bytes of watchdog handling; seven bl; pop.
    base = STOCK.hardware_init_offset
    put16(image, base, 0xB510)
    for index, target in enumerate(STOCK.hardware_init_calls):
        encode_bl(image, base + 0x2A + index * 4, target)
    put16(image, base + 0x2A + len(STOCK.hardware_init_calls) * 4, 0xBD10)
    # Priority setup tail with the PRIMASK release.
    base = STOCK.primask_release_offset
    put_bytes(image, base - 8, "401c0028e4d100bf80f3108800bf30bd")
    # Region-1 copy and aperture programming.
    base = STOCK.region1_copy_offset
    put16(image, base, 0xB510)
    encode_ldr_literal(image, base + 2, 1, base + 0x74)
    put_bytes(image, base + 4, "086820f0f00040f040000860")
    put_bytes(image, base + 0x10, "4ff45e22")
    encode_ldr_literal(image, base + 0x14, 1, base + 0x78)
    encode_ldr_literal(image, base + 0x16, 0, base + 0x7C)
    encode_bl(image, base + 0x18, STOCK.memcpy_offset)
    put_bytes(image, base + 0x1C, "00bf")
    encode_ldr_literal(image, base + 0x1E, 0, base + 0x74)
    put_bytes(image, base + 0x20,
              "0078001d00f002000028f8d1")
    encode_ldr_literal(image, base + 0x2C, 1, base + 0x74)
    put_bytes(image, base + 0x2E, "086820f0f00040f08000086000bf")
    encode_ldr_literal(image, base + 0x3C, 0, base + 0x80)
    put_bytes(image, base + 0x3E, "006820f4006000f500604ff08a41c1f80c01")
    encode_ldr_literal(image, base + 0x50, 0, base + 0x7C)
    encode_ldr_literal(image, base + 0x52, 1, base + 0x84)
    put_bytes(image, base + 0x54, "486048600220086000bfc0060068")
    encode_ldr_literal(image, base + 0x62, 1, base + 0x78)
    put_bytes(image, base + 0x64, "09688842")
    for offset, value in ((0x74, VERIFIER.SFC_BASE),
                          (0x78, VERIFIER.REGION1_FLASH_SOURCE),
                          (0x7C, VERIFIER.REGION1_OPI_COPY),
                          (0x80, VERIFIER.SYS1_CLOCK_RESET),
                          (0x84, VERIFIER.ICACHE_BASE)):
        put32(image, base + offset, value)
    # Thirty-five more veneers so the veneer count matches the pin.
    offset = STOCK.handoff_veneer_offset + 10
    for index in range(STOCK.veneer_count - 1):
        encode_movw_movt(image, offset, 12, 0x10001001 + index * 0x100)
        put16(image, offset + 8, 0x4760)
        offset += 10
    return image


def synthetic_core1() -> bytearray:
    image = bytearray(STOCK.core1_size)
    for index, target in enumerate(STOCK.thunk_targets):
        encode_movw_movt(image, index * 10, 12, target)
        put16(image, index * 10 + 8, 0x4760)
    entry = STOCK.region1_entry - VERIFIER.REGION1_RUNTIME_BASE - 1
    put16(image, entry, 0x2103)
    put_bytes(image, entry + 2, "0620")
    return image


def synthetic_loader() -> bytearray:
    return bytearray(STOCK.loader_size)


def synthetic_profile(core0: bytes, core1: bytes, loader: bytes):
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
    entry = STOCK.region1_entry - VERIFIER.REGION1_RUNTIME_BASE - 1
    return replace(
        STOCK,
        version="synthetic",
        core0_sha256=digest(core0),
        core1_sha256=digest(core1),
        loader_sha256=digest(loader),
        reset_closure_sha256=digest(
            VERIFIER._closure_blob(core0, STOCK.reset_closure_ranges)),
        loader_closure_sha256=digest(
            VERIFIER._closure_blob(loader, STOCK.loader_closure_ranges)),
        reset_closure_sram_constants=(
            STOCK.heap_base, STOCK.heap_limit, STOCK.stack_limit, STOCK.stack_top),
        reset_closure_rom_calls=(),
        loader_closure_aperture_bit_immediates=(),
        region1_main_sha256=digest(core1[entry:entry + STOCK.region1_main_length]),
    )


class Region1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.core0 = bytes(synthetic_core0())
        self.core1 = bytes(synthetic_core1())
        self.loader = bytes(synthetic_loader())
        self.profile = synthetic_profile(self.core0, self.core1, self.loader)

    def verify(self, core0=None, core1=None, loader=None, profile=None):
        return VERIFIER.verify_images(
            profile or self.profile, core0 or self.core0, core1 or self.core1,
            loader or self.loader)

    def failed(self, report) -> set[str]:
        return {check["name"] for check in report["checks"] if not check["passed"]}

    def test_synthetic_chain_passes_every_check(self) -> None:
        report = self.verify()
        self.assertEqual(self.failed(report), set(), json.dumps(report["checks"]))
        self.assertTrue(report["passed"])
        self.assertFalse(report["device_accessed"])
        self.assertFalse(report["files_written"])
        json.dumps(report)

    def test_stock_profile_pins_are_self_consistent(self) -> None:
        self.assertEqual(len(STOCK.thunk_targets), STOCK.thunk_count)
        self.assertEqual(STOCK.scatter_table_end - STOCK.scatter_table_offset,
                         16 * len(STOCK.scatter_entries))
        self.assertEqual(STOCK.scatter_entries[2][1] + STOCK.scatter_entries[2][2],
                         STOCK.stack_top)
        self.assertEqual(VERIFIER.REGION1_OPI_COPY + VERIFIER.REGION1_COPY_BYTES,
                         0x30800000)
        self.assertEqual(STOCK.region1_entry & 1, 1)
        for start, end in STOCK.reset_closure_ranges:
            self.assertLess(start, end)
            self.assertLessEqual(end, STOCK.core0_size)
        for start, end in STOCK.loader_closure_ranges:
            self.assertLess(start, end)
            self.assertLessEqual(end, STOCK.loader_size)
        self.assertNotIn(STOCK.handoff_veneer_offset,
                         [start for start, _ in STOCK.reset_closure_ranges])

    def test_synthetic_fixture_is_not_stock(self) -> None:
        self.assertNotEqual(self.profile.core0_sha256, STOCK.core0_sha256)
        self.assertNotEqual(self.profile.reset_closure_sha256,
                            STOCK.reset_closure_sha256)

    def test_report_derives_the_documented_facts(self) -> None:
        facts = self.verify()["facts"]
        self.assertEqual(facts["runtime_entry"]["region1_entry"], "0x1004a525")
        self.assertEqual(facts["runtime_entry"]["stack_top_at_entry"], "0x1803f5c0")
        self.assertEqual(facts["region1_copy"]["copy_bytes"], "0x000de000")
        self.assertEqual(facts["region1_copy"]["cache_control_value"], 2)
        self.assertEqual(facts["primask_release"]["interrupts_enabled_at_handoff"], True)
        self.assertEqual(facts["reset_closure"]["region1_constants"], 0)
        self.assertEqual(facts["loader_closure"]["region1_constants"], 0)
        self.assertEqual([entry["handler"] for entry in facts["scatter"]["entries"]],
                         ["decompress", "copy", "zero", "zero"])
        self.assertEqual(len(facts["vectors"]["region1_vectors"]), 5)
        self.assertEqual(facts["thunks"]["count"], 79)

    def test_wrong_region1_entry_is_rejected(self) -> None:
        core0 = bytearray(self.core0)
        encode_movw_movt(core0, STOCK.handoff_veneer_offset, 12, 0x1004A529)
        profile = synthetic_profile(bytes(core0), self.core1, self.loader)
        self.assertIn("runtime_entry", self.failed(self.verify(bytes(core0), profile=profile)))

    def test_second_handoff_caller_is_rejected(self) -> None:
        core0 = bytearray(self.core0)
        encode_bl(core0, 0x8000, STOCK.handoff_veneer_offset)
        profile = synthetic_profile(bytes(core0), self.core1, self.loader)
        self.assertIn("runtime_entry", self.failed(self.verify(bytes(core0), profile=profile)))

    def test_region1_constant_inside_reset_closure_is_rejected(self) -> None:
        core0 = bytearray(self.core0)
        # A literal load of a region-1 address inside a reached range.
        encode_ldr_literal(core0, 0x848, 0, 0x8B0)
        put32(core0, 0x8B0, 0x10008ADD)
        profile = synthetic_profile(bytes(core0), self.core1, self.loader)
        self.assertIn("reset_closure", self.failed(self.verify(bytes(core0), profile=profile)))

    def test_nvic_enable_inside_reset_closure_is_rejected(self) -> None:
        core0 = bytearray(self.core0)
        encode_movw_movt(core0, 0x848, 0, VERIFIER.NVIC_ISER_START)
        profile = synthetic_profile(bytes(core0), self.core1, self.loader)
        self.assertIn("reset_closure", self.failed(self.verify(bytes(core0), profile=profile)))

    def test_primask_set_instead_of_cleared_is_rejected(self) -> None:
        core0 = bytearray(self.core0)
        # cmp r0, #1 breaks the proof that r0 is zero when PRIMASK is written.
        put16(core0, STOCK.primask_release_offset - 6, 0x2801)
        profile = synthetic_profile(bytes(core0), self.core1, self.loader)
        self.assertIn("primask_release", self.failed(self.verify(bytes(core0), profile=profile)))

    def test_changed_copy_length_is_rejected(self) -> None:
        core0 = bytearray(self.core0)
        put_bytes(core0, STOCK.region1_copy_offset + 0x10, "4ff4de22")
        profile = synthetic_profile(bytes(core0), self.core1, self.loader)
        self.assertIn("region1_copy", self.failed(self.verify(bytes(core0), profile=profile)))

    def test_changed_vector_into_region1_is_rejected(self) -> None:
        core0 = bytearray(self.core0)
        put32(core0, 22 * 4, 0x1000C000 | 1)
        profile = synthetic_profile(bytes(core0), self.core1, self.loader)
        self.assertIn("vectors", self.failed(self.verify(bytes(core0), profile=profile)))

    def test_changed_thunk_target_is_rejected(self) -> None:
        core1 = bytearray(self.core1)
        encode_movw_movt(core1, 8 * 10, 12, 0x0000BCFF)
        profile = synthetic_profile(self.core0, bytes(core1), self.loader)
        self.assertIn("thunks", self.failed(self.verify(core1=bytes(core1), profile=profile)))

    def test_identity_mutation_is_rejected_without_rebased_profile(self) -> None:
        core0 = bytearray(self.core0)
        core0[-1] ^= 1
        report = self.verify(bytes(core0))
        self.assertIn("core0_exact_identity", self.failed(report))

    def test_loader_region1_literal_is_rejected(self) -> None:
        loader = bytearray(self.loader)
        encode_ldr_literal(loader, 0x1F4, 0, 0x284)
        put32(loader, 0x284, 0x10000001)
        profile = synthetic_profile(self.core0, self.core1, bytes(loader))
        self.assertIn("loader_closure", self.failed(self.verify(loader=bytes(loader), profile=profile)))

    def test_cli_reports_missing_input_without_writing(self) -> None:
        import io
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = VERIFIER.main([
                "--version", "V1.22", "--core0", "/nonexistent/core0.bin",
                "--core1", "/nonexistent/core1.bin",
                "--loader", "/nonexistent/loader.bin"])
        report = json.loads(buffer.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        self.assertEqual(report["error"]["input_name"], "core0.bin")
        self.assertFalse(report["files_written"])


if __name__ == "__main__":
    unittest.main()
