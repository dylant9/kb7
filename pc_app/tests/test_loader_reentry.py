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


def encode_modified_immediate(value: int) -> tuple[int, int, int]:
    """Return ``(i, imm3, imm8)`` for a Thumb-2 modified immediate."""

    value &= 0xFFFFFFFF
    if value <= 0xFF:
        imm12 = value
    elif value == (value & 0xFF) * 0x00010001:
        imm12 = 0x100 | (value & 0xFF)
    elif value == ((value >> 8) & 0xFF) * 0x01000100:
        imm12 = 0x200 | ((value >> 8) & 0xFF)
    elif value == (value & 0xFF) * 0x01010101:
        imm12 = 0x300 | (value & 0xFF)
    else:
        for rotation in range(8, 32):
            rotated = ((value << rotation) | (value >> (32 - rotation))) & 0xFFFFFFFF
            if rotated <= 0xFF and rotated & 0x80:
                imm12 = (rotation << 7) | (rotated & 0x7F)
                break
        else:
            raise AssertionError(f"{value:#x} is not a Thumb-2 modified immediate")
    return imm12 >> 11, (imm12 >> 8) & 7, imm12 & 0xFF


def encode_data_processing_immediate(
    data: bytearray,
    instruction_offset: int,
    operation: int,
    rd: int,
    rn: int,
    value: int,
    *,
    set_flags: bool = False,
) -> None:
    """Thumb-2 data processing with a modified immediate.

    ``operation`` is the four-bit opcode (AND 0, ORR/MOV 2, ADD 8, SUB/CMP
    13); CMP is SUB with ``rd`` 15 and ``set_flags``; MOV is ORR with ``rn``
    15.
    """

    i, imm3, imm8 = encode_modified_immediate(value)
    put16(
        data,
        instruction_offset,
        0xF000 | (i << 10) | (operation << 5) | (int(set_flags) << 4) | rn,
    )
    put16(data, instruction_offset + 2, (imm3 << 12) | (rd << 8) | imm8)


def encode_word_transfer_post_indexed(
    data: bytearray, instruction_offset: int, rt: int, rn: int, delta: int, *, load: bool
) -> None:
    """Thumb-2 word LDR/STR (immediate) T4 with post-indexed writeback."""

    assert delta != 0 and -255 <= delta <= 255
    put16(data, instruction_offset, 0xF840 | (int(load) << 4) | rn)
    put16(
        data,
        instruction_offset + 2,
        (rt << 12) | 0x0800 | (int(delta > 0) << 9) | 0x0100 | abs(delta),
    )


def encode_unconditional_branch(
    data: bytearray, instruction_offset: int, target: int
) -> None:
    displacement = target - (instruction_offset + 4)
    assert displacement % 2 == 0 and -2048 <= displacement <= 2046
    put16(data, instruction_offset, 0xE000 | ((displacement >> 1) & 0x7FF))


def encode_barrier(data: bytearray, instruction_offset: int, option: int) -> None:
    """DSB (4), DMB (5) or ISB (6) with the SY option."""

    put16(data, instruction_offset, 0xF3BF)
    put16(data, instruction_offset + 2, 0x8F0F | (option << 4))


def synthetic_relocation_routine(
    *,
    copy_bytes: int = VERIFIER.LOADER_COPY_BYTES,
    guard_bound: int | None = None,
    prigroup_mask: int | None = VERIFIER.AIRCR_PRIGROUP_MASK,
    disable_interrupts: bool = True,
    park: bool = True,
) -> bytes:
    """Independently authored 88-byte routine with the stock semantics.

    It is deliberately not the stock encoding: a CPSID instead of an MSR, a
    count-down loop over post-indexed wide loads and stores, a wide ORR for
    SYSRESETREQ and explicit barriers.  Only the semantics the verifier must
    derive match: a self-location guard against the copy bound that returns
    one when inside the destination window, an interrupt disable before the
    first store, a contiguous word copy of ``copy_bytes`` from the +0x4C
    literal to PRAM zero, an AIRCR read-modify-write that keeps only PRIGROUP
    and sets VECTKEY plus SYSRESETREQ as the last store, then an endless
    loop.  The keyword arguments produce the negative fixtures.
    """

    routine = bytearray(VERIFIER.TRAMPOLINE_BYTES)
    bound = copy_bytes if guard_bound is None else guard_bound
    put16(routine, 0x00, 0x4600 | (15 << 3) | 3)                     # mov r3, pc
    encode_data_processing_immediate(routine, 0x02, 0b1101, 15, 3, bound,
                                     set_flags=True)                 # cmp.w r3, #bound
    encode_conditional_branch(routine, 0x06, 2, 0x0C, 0)             # bhs body
    put16(routine, 0x08, 0x2001)                                     # movs r0, #1
    put16(routine, 0x0A, 0x4770)                                     # bx lr
    put16(routine, 0x0C, 0xB672 if disable_interrupts else 0xBF00)   # cpsid i
    encode_ldr_literal(routine, 0x0E, 1, 0x4C)                       # ldr r1, =source
    put16(routine, 0x10, 0x2000)                                     # movs r0, #0
    encode_data_processing_immediate(routine, 0x12, 0b0010, 2, 15, copy_bytes)
    encode_word_transfer_post_indexed(routine, 0x16, 4, 1, 4, load=True)
    encode_word_transfer_post_indexed(routine, 0x1A, 4, 0, 4, load=False)
    put16(routine, 0x1E, 0x3A04)                                     # subs r2, #4
    encode_conditional_branch(routine, 0x20, 1, 0x16, 0)             # bne loop
    encode_ldr_literal(routine, 0x22, 5, 0x50)                       # ldr r5, =AIRCR
    put16(routine, 0x24, 0x6800 | (5 << 3) | 6)                      # ldr r6, [r5]
    if prigroup_mask is None:
        put16(routine, 0x26, 0xBF00)
        put16(routine, 0x28, 0xBF00)
    else:
        encode_data_processing_immediate(routine, 0x26, 0b0000, 6, 6, prigroup_mask)
    encode_ldr_literal(routine, 0x2A, 7, 0x54)                       # ldr r7, =key
    put16(routine, 0x2C, 0x4300 | (7 << 3) | 6)                      # orrs r6, r7
    encode_data_processing_immediate(routine, 0x2E, 0b0010, 6, 6,
                                     VERIFIER.AIRCR_SYSRESETREQ)     # orr.w r6, r6, #4
    encode_barrier(routine, 0x32, 4)                                 # dsb sy
    put16(routine, 0x36, 0x6000 | (5 << 3) | 6)                      # str r6, [r5]
    encode_barrier(routine, 0x38, 4)                                 # dsb sy
    encode_barrier(routine, 0x3C, 6)                                 # isb sy
    if park:
        encode_unconditional_branch(routine, 0x40, 0x40)             # b .
    else:
        put16(routine, 0x40, 0x4770)                                 # bx lr
    for padding in (0x42, 0x44, 0x46, 0x48, 0x4A):
        put16(routine, padding, 0xBF00)                              # nop
    put32(routine, 0x4C, VERIFIER.LOADER_FLASH_SOURCE)
    put32(routine, 0x50, VERIFIER.AIRCR_ADDRESS)
    put32(routine, 0x54, VERIFIER.AIRCR_KEY_BASE)
    return bytes(routine)


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
    # The fixture carries an independently authored routine with the stock
    # semantics so the verifier's decoder and interpreter are exercised.
    core1[trampoline:trampoline + VERIFIER.TRAMPOLINE_BYTES] = (
        synthetic_relocation_routine()
    )

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


def pair_with_routine(routine: bytes) -> tuple[object, bytes, bytes]:
    """Return the synthetic pair with ``routine`` in place of the fixture's."""

    profile, core1, loader = synthetic_pair()
    assert len(routine) == VERIFIER.TRAMPOLINE_BYTES
    mutated = bytearray(core1)
    start = profile.trampoline_offset
    mutated[start:start + len(routine)] = routine
    mutated_bytes = bytes(mutated)
    profile = replace(
        profile,
        core1_sha256=hashlib.sha256(mutated_bytes).hexdigest(),
        trampoline_sha256=hashlib.sha256(routine).hexdigest(),
    )
    return profile, mutated_bytes, loader


def trampoline_check(report: dict) -> dict:
    return next(item for item in report["checks"]
                if item["name"] == "core1_88_byte_loader_trampoline")


class RelocationRoutineDecodingTests(unittest.TestCase):
    def test_synthetic_routine_is_not_the_stock_routine(self) -> None:
        routine = synthetic_relocation_routine()
        self.assertEqual(len(routine), VERIFIER.TRAMPOLINE_BYTES)
        self.assertNotEqual(hashlib.sha256(routine).hexdigest(),
                            VERIFIER.COMMON_TRAMPOLINE_SHA256)

    def test_modified_immediate_encoder_round_trips(self) -> None:
        for value in (0x00, 0x7F, 0xFF, 0x00AB00AB, 0xCD00CD00, 0x12121212,
                      0x700, 0x8000, 0x10000, 0x3FC, 0x80000000, 0xFF000000,
                      0x000001FE):
            with self.subTest(value=hex(value)):
                i, imm3, imm8 = encode_modified_immediate(value)
                self.assertEqual(VERIFIER.thumb_expand_imm(i, imm3, imm8), value)

    def test_decoder_recognises_the_wide_forms_used_by_the_fixture(self) -> None:
        data = bytearray(64)
        encode_data_processing_immediate(data, 0, 0b1101, 15, 3, 0x10000,
                                         set_flags=True)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 0),
                         ("cmp_imm", 4, 3, 0x10000))
        encode_data_processing_immediate(data, 4, 0b0010, 2, 15, 0x8000)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 4),
                         ("mov_imm", 4, 2, 0x8000, False))
        encode_data_processing_immediate(data, 8, 0b0000, 6, 6, 0x700)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 8),
                         ("and_imm", 4, 6, 6, 0x700, False))
        encode_data_processing_immediate(data, 12, 0b0010, 6, 6, 4)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 12),
                         ("orr_imm", 4, 6, 6, 4, False))
        encode_word_transfer_post_indexed(data, 16, 4, 1, 4, load=True)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 16),
                         ("ldr_imm", 4, 4, 1, 0, 4))
        encode_word_transfer_post_indexed(data, 20, 4, 0, -8, load=False)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 20),
                         ("str_imm", 4, 4, 0, 0, -8))
        encode_barrier(data, 24, 4)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 24),
                         ("barrier", 4, "dsb"))
        encode_barrier(data, 28, 6)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 28),
                         ("barrier", 4, "isb"))
        put16(data, 32, 0xB672)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 32),
                         ("cps", 2, True, True, False))
        put16(data, 34, 0x4600 | (15 << 3) | 3)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 34),
                         ("mov_reg", 2, 3, 15))
        encode_unconditional_branch(data, 36, 36)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 36), ("b", 2, 36))
        encode_conditional_branch(data, 38, 1, 20, 0)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 38),
                         ("bcond", 2, 1, 20))
        put16(data, 40, 0x3A04)
        self.assertEqual(VERIFIER.decode_thumb_instruction(data, 40),
                         ("sub_imm", 2, 2, 2, 4, True))
        self.assertEqual(VERIFIER.decode_thumb_instruction(bytes(4), 0)[0],
                         "unknown")

    def test_trampoline_facts_are_derived_from_decoded_instructions(self) -> None:
        profile, core1, loader = synthetic_pair()
        report = VERIFIER.verify_images(profile, core1, loader)
        self.assertTrue(trampoline_check(report)["passed"])
        facts = report["facts"]["trampoline"]
        self.assertIn("decoded", facts["semantic_basis"])
        self.assertEqual(facts["source_start"], "0x60001000")
        self.assertEqual(facts["destination_start"], "0x00000000")
        self.assertEqual(facts["copy_bytes"], 0x10000)
        self.assertEqual(facts["word_bytes"], 4)
        self.assertEqual(facts["copy_order"], "ascending")
        self.assertEqual(facts["self_location_guard_bound"], "0x00010000")
        self.assertTrue(facts["refuses_to_run_inside_destination_window"])
        self.assertEqual(facts["inside_window_return_value"], "0x00000001")
        self.assertTrue(facts["interrupts_disabled"])
        self.assertEqual(facts["interrupt_mask"], "PRIMASK")
        self.assertEqual(facts["aircr_address"], "0xe000ed0c")
        self.assertEqual(facts["aircr_prigroup_mask"], "0x00000700")
        self.assertEqual(facts["aircr_write"], "(AIRCR & 0x00000700) | 0x05fa0004")
        self.assertTrue(facts["reset_write_is_last_store"])
        self.assertTrue(facts["non_returning"])
        self.assertEqual(facts["terminal_behaviour"], "branch_to_self")
        self.assertEqual(facts["interpreted_steps"], 4 * 0x4000 + 18)

    def test_relocation_facts_match_machine_readable_record(self) -> None:
        record = json.loads(
            (ROOT / "hardware" / "kb7-stock-loader-reentry.json").read_text(
                encoding="utf-8"
            )
        )["stock_relocation"]
        profile, core1, loader = synthetic_pair()
        facts = VERIFIER.verify_images(profile, core1, loader)["facts"]["trampoline"]
        self.assertEqual(record["facts_basis"],
                         "decoded_and_interpreted_thumb2_instructions_plus_pinned_digest")
        for key in ("source_start", "destination_start", "copy_bytes", "word_bytes",
                    "self_location_guard_bound", "executes_outside_pram",
                    "interrupts_disabled", "interrupt_mask", "aircr_address",
                    "reset_write_is_last_store", "non_returning"):
            with self.subTest(key=key):
                self.assertEqual(record[key], facts[key])
        self.assertEqual(record["aircr_expression"], facts["aircr_write"])
        self.assertEqual(record["trampoline_bytes"], facts["bytes"])

    def test_undecodable_body_with_correct_literals_is_rejected(self) -> None:
        routine = bytearray(
            (index * 73 + 19) & 0xFF for index in range(VERIFIER.TRAMPOLINE_BYTES)
        )
        put32(routine, 0x4C, VERIFIER.LOADER_FLASH_SOURCE)
        put32(routine, 0x50, VERIFIER.AIRCR_ADDRESS)
        put32(routine, 0x54, VERIFIER.AIRCR_KEY_BASE)
        profile, core1, loader = pair_with_routine(bytes(routine))
        report = VERIFIER.verify_images(profile, core1, loader)
        check = trampoline_check(report)
        self.assertFalse(report["passed"])
        self.assertFalse(check["passed"])
        self.assertNotIn("trampoline", report["facts"])

    def test_wrong_copy_length_is_rejected(self) -> None:
        profile, core1, loader = pair_with_routine(
            synthetic_relocation_routine(copy_bytes=0x8000)
        )
        check = trampoline_check(VERIFIER.verify_images(profile, core1, loader))
        self.assertFalse(check["passed"])
        self.assertIn("copies 0x00008000 bytes", check["error"])

    def test_missing_aircr_mask_is_rejected(self) -> None:
        profile, core1, loader = pair_with_routine(
            synthetic_relocation_routine(prigroup_mask=None)
        )
        check = trampoline_check(VERIFIER.verify_images(profile, core1, loader))
        self.assertFalse(check["passed"])
        self.assertIn("preserves AIRCR bits 0xfa05fffb", check["error"])

    def test_wider_aircr_mask_is_rejected(self) -> None:
        profile, core1, loader = pair_with_routine(
            synthetic_relocation_routine(prigroup_mask=0xFF00)
        )
        check = trampoline_check(VERIFIER.verify_images(profile, core1, loader))
        self.assertFalse(check["passed"])
        self.assertIn("preserves AIRCR bits 0x0000ff00", check["error"])

    def test_returning_routine_is_rejected(self) -> None:
        profile, core1, loader = pair_with_routine(
            synthetic_relocation_routine(park=False)
        )
        check = trampoline_check(VERIFIER.verify_images(profile, core1, loader))
        self.assertFalse(check["passed"])
        self.assertIn("does not park", check["error"])

    def test_missing_interrupt_disable_is_rejected(self) -> None:
        profile, core1, loader = pair_with_routine(
            synthetic_relocation_routine(disable_interrupts=False)
        )
        check = trampoline_check(VERIFIER.verify_images(profile, core1, loader))
        self.assertFalse(check["passed"])
        self.assertIn("never disables interrupts", check["error"])

    def test_guard_bound_mismatch_is_rejected(self) -> None:
        profile, core1, loader = pair_with_routine(
            synthetic_relocation_routine(guard_bound=0x8000)
        )
        check = trampoline_check(VERIFIER.verify_images(profile, core1, loader))
        self.assertFalse(check["passed"])
        self.assertIn("guard bound 0x00008000 differs", check["error"])

    def test_digest_pin_still_applies_to_a_semantically_valid_routine(self) -> None:
        profile, core1, loader = pair_with_routine(synthetic_relocation_routine())
        profile = replace(profile, trampoline_sha256="0" * 64)
        check = trampoline_check(VERIFIER.verify_images(profile, core1, loader))
        self.assertFalse(check["passed"])
        self.assertIn("unexpected 88-byte trampoline hash", check["error"])

if __name__ == "__main__":
    unittest.main()
