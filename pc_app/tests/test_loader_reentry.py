from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_loader_reentry", ROOT / "tools" / "verify_loader_reentry.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


def put16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", data, offset, value)


def put32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def encode_ldr_literal(
    data: bytearray, instruction_offset: int, register: int, literal_offset: int
) -> None:
    pc = (instruction_offset + 4) & ~3
    displacement = literal_offset - pc
    assert displacement >= 0 and displacement % 4 == 0
    immediate = displacement // 4
    assert immediate <= 0xFF
    put16(data, instruction_offset, 0x4800 | (register << 8) | immediate)


def encode_bl(
    data: bytearray, instruction_offset: int, target: int, runtime_base: int
) -> None:
    displacement = target - (runtime_base + instruction_offset + 4)
    assert displacement % 2 == 0 and -(1 << 24) <= displacement < (1 << 24)
    encoded = displacement & ((1 << 25) - 1)
    sign = (encoded >> 24) & 1
    i1 = (encoded >> 23) & 1
    i2 = (encoded >> 22) & 1
    immediate_10 = (encoded >> 12) & 0x3FF
    immediate_11 = (encoded >> 1) & 0x7FF
    j1 = ((~i1) & 1) ^ sign
    j2 = ((~i2) & 1) ^ sign
    put16(data, instruction_offset, 0xF000 | (sign << 10) | immediate_10)
    put16(
        data,
        instruction_offset + 2,
        0xD000 | (j1 << 13) | (j2 << 11) | immediate_11,
    )


def encode_cbz_cbnz(
    data: bytearray,
    instruction_offset: int,
    register: int,
    target: int,
    runtime_base: int,
    *,
    nonzero: bool,
) -> None:
    displacement = target - (runtime_base + instruction_offset + 4)
    assert displacement >= 0 and displacement <= 126 and displacement % 2 == 0
    instruction = (
        0xB100
        | (int(nonzero) << 11)
        | (((displacement >> 6) & 1) << 9)
        | (((displacement >> 1) & 0x1F) << 3)
        | register
    )
    put16(data, instruction_offset, instruction)


def encode_conditional_branch(
    data: bytearray,
    instruction_offset: int,
    condition: int,
    target: int,
    runtime_base: int,
) -> None:
    displacement = target - (runtime_base + instruction_offset + 4)
    assert displacement % 2 == 0 and -256 <= displacement <= 254
    put16(data, instruction_offset, 0xD000 | (condition << 8) |
          ((displacement >> 1) & 0xFF))


def synthetic_pair() -> tuple[object, bytes, bytes]:
    template = VERIFIER.PROFILES["V1.22"]
    core1 = bytearray(template.core1_size)
    loader = bytearray(template.loader_size)

    handler = template.request_handler_offset
    put16(core1, handler + 0x10, 0x2E09)
    put16(core1, handler + 0x24, 0x2208)
    encode_ldr_literal(
        core1, handler + 0x26, 1, template.request_key_pointer_literal_offset
    )
    put16(core1, handler + 0x28, 0x4620)
    encode_bl(
        core1,
        handler + 0x2A,
        template.request_compare_target,
        VERIFIER.CORE1_RUNTIME_BASE,
    )
    encode_cbz_cbnz(
        core1,
        handler + 0x2E,
        0,
        VERIFIER.CORE1_RUNTIME_BASE + handler + 0x38,
        VERIFIER.CORE1_RUNTIME_BASE,
        nonzero=True,
    )
    encode_ldr_literal(
        core1,
        template.request_marker_value_load_offset,
        0,
        template.request_magic_literal_offset,
    )
    encode_ldr_literal(
        core1,
        template.request_marker_value_load_offset + 2,
        1,
        template.request_marker_address_literal_offset,
    )
    put16(core1, template.request_marker_value_load_offset + 4, 0x6008)
    put32(
        core1, template.request_key_pointer_literal_offset, template.request_key_pointer
    )
    put32(core1, template.request_magic_literal_offset, VERIFIER.LOADER_FLAG_VALUE)
    put32(
        core1,
        template.request_marker_address_literal_offset,
        VERIFIER.LOADER_FLAG_ADDRESS,
    )

    poll = template.marker_poll_offset
    encode_ldr_literal(
        core1, poll, 0, template.marker_poll_address_literal_offset
    )
    encode_ldr_literal(
        core1, poll + 2, 1, template.marker_poll_magic_literal_offset
    )
    put16(core1, poll + 4, 0x6800)
    put16(core1, poll + 6, 0x4288)
    encode_conditional_branch(
        core1,
        poll + 8,
        1,
        VERIFIER.CORE1_RUNTIME_BASE + poll + 0x20,
        VERIFIER.CORE1_RUNTIME_BASE,
    )
    put32(
        core1,
        template.marker_poll_address_literal_offset,
        VERIFIER.LOADER_FLAG_ADDRESS,
    )
    put32(
        core1,
        template.marker_poll_magic_literal_offset,
        VERIFIER.LOADER_FLAG_VALUE,
    )
    call = template.wrapper_call_offset
    for relative, value in ((-8, 0x2001), (-6, 0xF380), (-4, 0x8810)):
        put16(core1, call + relative, value)
    encode_bl(
        core1,
        call,
        VERIFIER.CORE1_RUNTIME_BASE + template.wrapper_offset,
        VERIFIER.CORE1_RUNTIME_BASE,
    )

    wrapper = template.wrapper_offset
    for relative, value in (
        (0x02, 0x2698),
        (0x0E, 0x2258),
        (0x12, 0x4620),
        (0x1C, 0x47A8),
    ):
        put16(core1, wrapper + relative, value)
    encode_ldr_literal(
        core1, wrapper + 0x10, 1, template.wrapper_source_literal_offset
    )
    encode_bl(
        core1,
        wrapper + 0x14,
        VERIFIER.CORE1_RUNTIME_BASE + 0xA,
        VERIFIER.CORE1_RUNTIME_BASE,
    )
    put32(
        core1,
        template.wrapper_source_literal_offset,
        VERIFIER.CORE1_RUNTIME_BASE + template.trampoline_offset,
    )

    trampoline = template.trampoline_offset
    # The fixture uses a deterministic non-vendor body.  The verifier maps its
    # digest to the same semantic schema without embedding the stock routine.
    core1[trampoline:trampoline + VERIFIER.TRAMPOLINE_BYTES] = bytes(
        (index * 73 + 19) & 0xFF for index in range(VERIFIER.TRAMPOLINE_BYTES)
    )
    put32(core1, trampoline + 0x4C, VERIFIER.LOADER_FLASH_SOURCE)
    put32(core1, trampoline + 0x50, VERIFIER.AIRCR_ADDRESS)
    put32(core1, trampoline + 0x54, VERIFIER.AIRCR_KEY_BASE)

    put32(loader, 0, 0x180148B8)
    put32(loader, 4, 0x000002C9)
    consumer = template.loader_marker_consumer_offset
    for relative, value in (
        (0x0C, 0x6800),
        (0x10, 0x4288),
        (0x14, 0x2000),
        (0x18, 0x6008),
        (0x1A, 0x6008),
        (0x1E, 0x6800),
        (0x32, 0x2001),
        (0x3C, 0x2000),
    ):
        put16(loader, consumer + relative, value)
    encode_conditional_branch(
        loader,
        consumer + 0x12,
        1,
        consumer + 0x36,
        VERIFIER.LOADER_RUNTIME_BASE,
    )
    encode_cbz_cbnz(
        loader,
        consumer + 0x20,
        0,
        consumer + 0x2C,
        VERIFIER.LOADER_RUNTIME_BASE,
        nonzero=False,
    )
    encode_ldr_literal(
        loader,
        consumer + 0x0A,
        0,
        template.loader_marker_address_literal_offset,
    )
    encode_ldr_literal(
        loader,
        consumer + 0x0E,
        1,
        template.loader_marker_magic_literal_offset,
    )
    encode_ldr_literal(
        loader,
        consumer + 0x16,
        1,
        template.loader_marker_address_literal_offset,
    )
    put32(
        loader,
        template.loader_marker_address_literal_offset,
        VERIFIER.LOADER_FLAG_ADDRESS,
    )
    put32(
        loader,
        template.loader_marker_magic_literal_offset,
        VERIFIER.LOADER_FLAG_VALUE,
    )
    encode_bl(
        loader,
        template.loader_marker_call_offset,
        template.loader_marker_consumer_offset,
        VERIFIER.LOADER_RUNTIME_BASE,
    )
    encode_cbz_cbnz(
        loader,
        template.loader_marker_call_offset + 4,
        0,
        template.loader_updater_call_offset + 4,
        VERIFIER.LOADER_RUNTIME_BASE,
        nonzero=False,
    )
    encode_bl(
        loader,
        template.loader_updater_call_offset,
        template.loader_updater_offset,
        VERIFIER.LOADER_RUNTIME_BASE,
    )
    encode_bl(
        loader,
        template.loader_updater_offset,
        0x5878,
        VERIFIER.LOADER_RUNTIME_BASE,
    )
    encode_bl(
        loader,
        template.loader_app_validation_call_offset,
        template.loader_app_validation_offset,
        VERIFIER.LOADER_RUNTIME_BASE,
    )
    encode_cbz_cbnz(
        loader,
        template.loader_app_validation_call_offset + 6,
        4,
        template.loader_app_failure_updater_call_offset + 4,
        VERIFIER.LOADER_RUNTIME_BASE,
        nonzero=True,
    )
    encode_bl(
        loader,
        template.loader_app_slot_check_call_offset,
        template.loader_app_slot_check_offset,
        VERIFIER.LOADER_RUNTIME_BASE,
    )
    encode_bl(
        loader,
        template.loader_app_failure_updater_call_offset,
        template.loader_updater_offset,
        VERIFIER.LOADER_RUNTIME_BASE,
    )

    core1_bytes = bytes(core1)
    loader_bytes = bytes(loader)
    profile = replace(
        template,
        version="synthetic",
        core1_sha256=hashlib.sha256(core1_bytes).hexdigest(),
        loader_sha256=hashlib.sha256(loader_bytes).hexdigest(),
        trampoline_sha256=hashlib.sha256(
            core1_bytes[trampoline:trampoline + VERIFIER.TRAMPOLINE_BYTES]
        ).hexdigest(),
    )
    return profile, core1_bytes, loader_bytes


class LoaderReentryEvidenceTests(unittest.TestCase):
    def test_all_pinned_release_profiles_are_present(self) -> None:
        self.assertEqual(set(VERIFIER.PROFILES), {"V1.22", "V1.24", "V1.33"})
        self.assertEqual(
            {profile.trampoline_sha256 for profile in VERIFIER.PROFILES.values()},
            {VERIFIER.COMMON_TRAMPOLINE_SHA256},
        )
        self.assertEqual(
            [VERIFIER.PROFILES[version].trampoline_offset
             for version in ("V1.22", "V1.24", "V1.33")],
            [0x59158, 0x5943C, 0x63A98],
        )

    def test_thumb_bl_decoder_handles_forward_and_backward_targets(self) -> None:
        data = bytearray(16)
        for target in (0x10000100, 0x0FFF0000):
            encode_bl(data, 4, target, VERIFIER.CORE1_RUNTIME_BASE)
            self.assertEqual(
                VERIFIER.decode_thumb_bl(data, 4, VERIFIER.CORE1_RUNTIME_BASE),
                target,
            )

    def test_pinned_profiles_match_machine_readable_facts(self) -> None:
        facts = json.loads(
            (ROOT / "hardware" / "kb7-stock-loader-reentry.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(facts["stock_relocation"]["trampoline_sha256"],
                         VERIFIER.COMMON_TRAMPOLINE_SHA256)
        releases = {item["version"]: item for item in facts["releases"]}
        self.assertEqual(set(releases), set(VERIFIER.PROFILES))
        for version, profile in VERIFIER.PROFILES.items():
            release = releases[version]
            with self.subTest(version=version):
                self.assertEqual(release["core1_size_bytes"], profile.core1_size)
                self.assertEqual(release["core1_sha256"], profile.core1_sha256)
                self.assertEqual(release["loader_size_bytes"], profile.loader_size)
                self.assertEqual(release["loader_sha256"], profile.loader_sha256)
                self.assertEqual(int(release["request_handler_offset"], 16),
                                 profile.request_handler_offset)
                self.assertEqual(int(release["request_marker_write_offset"], 16),
                                 profile.request_marker_value_load_offset + 4)
                self.assertEqual(int(release["marker_poll_offset"], 16),
                                 profile.marker_poll_offset)
                self.assertEqual(int(release["relocation_wrapper_offset"], 16),
                                 profile.wrapper_offset)
                self.assertEqual(int(release["stock_trampoline_offset"], 16),
                                 profile.trampoline_offset)
                self.assertEqual(int(release["loader_marker_consumer_offset"], 16),
                                 profile.loader_marker_consumer_offset)
                self.assertEqual(int(release["loader_marker_call_offset"], 16),
                                 profile.loader_marker_call_offset)
                self.assertEqual(int(release["marker_updater_call_offset"], 16),
                                 profile.loader_updater_call_offset)
                self.assertEqual(int(release["app_failure_updater_call_offset"], 16),
                                 profile.loader_app_failure_updater_call_offset)
                self.assertEqual(int(release["loader_updater_offset"], 16),
                                 profile.loader_updater_offset)

    def test_deterministic_synthetic_chain_passes(self) -> None:
        profile, core1, loader = synthetic_pair()
        report = VERIFIER.verify_images(profile, core1, loader)
        self.assertTrue(report["passed"])
        self.assertTrue(report["facts"]["request_handler"]
                        ["write_requires_zero_compare_result"])
        self.assertEqual(report["facts"]["trampoline"]["copy_bytes"], 0x10000)
        self.assertTrue(report["facts"]["loader_consumer"]["clears_marker_twice"])
        self.assertEqual(
            report["facts"]["loader_app_failure_fallback"]["failure_updater_entry"],
            "0x0000a5c0",
        )
        self.assertFalse(report["device_accessed"])
        self.assertFalse(report["files_written"])

    def test_path_report_discloses_basenames_only(self) -> None:
        profile, core1, loader = synthetic_pair()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            core1_path = directory / "owner-core1.dat"
            loader_path = directory / "owner-loader.dat"
            core1_path.write_bytes(core1)
            loader_path.write_bytes(loader)
            report = VERIFIER.verify_paths(profile, core1_path, loader_path)
        self.assertEqual(report["inputs"]["core1"]["name"], core1_path.name)
        self.assertEqual(report["inputs"]["loader"]["name"], loader_path.name)
        self.assertNotIn(temporary, json.dumps(report, sort_keys=True))

    def test_identity_mutation_is_rejected(self) -> None:
        profile, core1, loader = synthetic_pair()
        mutated = bytearray(core1)
        mutated[-1] ^= 1
        report = VERIFIER.verify_images(profile, bytes(mutated), loader)
        check = next(item for item in report["checks"]
                     if item["name"] == "core1_exact_identity")
        self.assertFalse(report["passed"])
        self.assertFalse(check["passed"])

    def test_semantic_mutation_is_rejected_even_with_rebased_identity(self) -> None:
        profile, core1, loader = synthetic_pair()
        mutated = bytearray(core1)
        put32(
            mutated,
            profile.request_marker_address_literal_offset,
            VERIFIER.LOADER_FLAG_ADDRESS - 4,
        )
        mutated_bytes = bytes(mutated)
        profile = replace(
            profile, core1_sha256=hashlib.sha256(mutated_bytes).hexdigest()
        )
        report = VERIFIER.verify_images(profile, mutated_bytes, loader)
        identity = next(item for item in report["checks"]
                        if item["name"] == "core1_exact_identity")
        semantic = next(item for item in report["checks"]
                        if item["name"] == "core1_request_type_9_marker_write")
        self.assertTrue(identity["passed"])
        self.assertFalse(semantic["passed"])
        self.assertIn("wrong address", semantic["error"])

    def test_loader_clear_sequence_mutation_is_rejected(self) -> None:
        profile, core1, loader = synthetic_pair()
        mutated = bytearray(loader)
        put16(mutated, profile.loader_marker_consumer_offset + 0x1A, 0xBF00)
        mutated_bytes = bytes(mutated)
        profile = replace(
            profile, loader_sha256=hashlib.sha256(mutated_bytes).hexdigest()
        )
        report = VERIFIER.verify_images(profile, core1, mutated_bytes)
        semantic = next(item for item in report["checks"]
                        if item["name"] == "loader_marker_consumer_and_updater_route")
        self.assertFalse(semantic["passed"])
        self.assertIn("0x00004806", semantic["error"])


if __name__ == "__main__":
    unittest.main()
