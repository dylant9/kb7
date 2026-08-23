#!/usr/bin/env python3
"""Verify pinned stock evidence for the volatile loader-reentry sequence.

The inputs remain owner-local.  This tool reads two flat binaries, emits only
identity hashes, offsets, and decoded facts, and performs no device access or
filesystem writes.

Release-specific ordered code is represented only by one-way hashes and
offsets.  The masked decoders below describe public Arm Thumb instruction
formats; no stock payload byte string is embedded in this source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


CORE1_RUNTIME_BASE = 0x10000000
LOADER_RUNTIME_BASE = 0x00000000
LOADER_FLAG_ADDRESS = 0x20000FFC
LOADER_FLAG_VALUE = 0x73207320
LOADER_FLASH_SOURCE = 0x60001000
LOADER_COPY_BYTES = 0x00010000
AIRCR_ADDRESS = 0xE000ED0C
AIRCR_PRIGROUP_MASK = 0x00000700
AIRCR_KEY_BASE = 0x05FA0000
AIRCR_SYSRESETREQ = 0x00000004
TRAMPOLINE_BYTES = 88
COMMON_TRAMPOLINE_SHA256 = (
    "570dc848c53aad3d18ae090580c2dd0687f7273c22693b4860e18dbf99a46315"
)


@dataclass(frozen=True)
class StockProfile:
    version: str
    core1_size: int
    core1_sha256: str
    loader_size: int
    loader_sha256: str
    request_handler_offset: int
    request_key_pointer_literal_offset: int
    request_key_pointer: int
    request_compare_target: int
    request_marker_value_load_offset: int
    request_magic_literal_offset: int
    request_marker_address_literal_offset: int
    marker_poll_offset: int
    marker_poll_address_literal_offset: int
    marker_poll_magic_literal_offset: int
    wrapper_call_offset: int
    wrapper_offset: int
    wrapper_source_literal_offset: int
    trampoline_offset: int
    trampoline_sha256: str
    loader_marker_consumer_offset: int
    loader_marker_address_literal_offset: int
    loader_marker_magic_literal_offset: int
    loader_marker_call_offset: int
    loader_updater_call_offset: int
    loader_updater_offset: int
    loader_app_validation_call_offset: int
    loader_app_validation_offset: int
    loader_app_slot_check_call_offset: int
    loader_app_slot_check_offset: int
    loader_app_failure_updater_call_offset: int


PROFILES: dict[str, StockProfile] = {
    "V1.22": StockProfile(
        version="V1.22",
        core1_size=438632,
        core1_sha256=(
            "b2869bc657ba896474e760f513e4514fac678a951364efc29cbf9b6bb5e2ba72"
        ),
        loader_size=61440,
        loader_sha256=(
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56"
        ),
        request_handler_offset=0x581FC,
        request_key_pointer_literal_offset=0x5825C,
        request_key_pointer=0x1801481C,
        request_compare_target=0x100002EE,
        request_marker_value_load_offset=0x5822C,
        request_magic_literal_offset=0x58260,
        request_marker_address_literal_offset=0x58264,
        marker_poll_offset=0x4A740,
        marker_poll_address_literal_offset=0x4A8B8,
        marker_poll_magic_literal_offset=0x4A8BC,
        wrapper_call_offset=0x4A77A,
        wrapper_offset=0x19A98,
        wrapper_source_literal_offset=0x19AB8,
        trampoline_offset=0x59158,
        trampoline_sha256=COMMON_TRAMPOLINE_SHA256,
        loader_marker_consumer_offset=0x47EC,
        loader_marker_address_literal_offset=0x4840,
        loader_marker_magic_literal_offset=0x4844,
        loader_marker_call_offset=0x5922,
        loader_updater_call_offset=0x5934,
        loader_updater_offset=0xA5C0,
        loader_app_validation_call_offset=0x5938,
        loader_app_validation_offset=0x2134,
        loader_app_slot_check_call_offset=0x213A,
        loader_app_slot_check_offset=0x6FB4,
        loader_app_failure_updater_call_offset=0x594C,
    ),
    "V1.24": StockProfile(
        version="V1.24",
        core1_size=439372,
        core1_sha256=(
            "dcb06f976dcaff81d0c5ccd1fdfebcb5b6ca4ec3d7e003ad1e90f896a4139aa7"
        ),
        loader_size=61440,
        loader_sha256=(
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56"
        ),
        request_handler_offset=0x584E0,
        request_key_pointer_literal_offset=0x58540,
        request_key_pointer=0x1801482C,
        request_compare_target=0x10000302,
        request_marker_value_load_offset=0x58510,
        request_magic_literal_offset=0x58544,
        request_marker_address_literal_offset=0x58548,
        marker_poll_offset=0x4A9DC,
        marker_poll_address_literal_offset=0x4AB54,
        marker_poll_magic_literal_offset=0x4AB58,
        wrapper_call_offset=0x4AA16,
        wrapper_offset=0x19CDC,
        wrapper_source_literal_offset=0x19CFC,
        trampoline_offset=0x5943C,
        trampoline_sha256=COMMON_TRAMPOLINE_SHA256,
        loader_marker_consumer_offset=0x47EC,
        loader_marker_address_literal_offset=0x4840,
        loader_marker_magic_literal_offset=0x4844,
        loader_marker_call_offset=0x5922,
        loader_updater_call_offset=0x5934,
        loader_updater_offset=0xA5C0,
        loader_app_validation_call_offset=0x5938,
        loader_app_validation_offset=0x2134,
        loader_app_slot_check_call_offset=0x213A,
        loader_app_slot_check_offset=0x6FB4,
        loader_app_failure_updater_call_offset=0x594C,
    ),
    "V1.33": StockProfile(
        version="V1.33",
        core1_size=487404,
        core1_sha256=(
            "d64df057dbdd125b12f156b57de5ad75a9a0d5804e30a16bb9ef1a56830d101f"
        ),
        loader_size=61440,
        loader_sha256=(
            "453753e431609116e303a12548ec21c2efd500af4569034bd7947eb5bf43b298"
        ),
        request_handler_offset=0x626F8,
        request_key_pointer_literal_offset=0x62758,
        request_key_pointer=0x18014918,
        request_compare_target=0x10000190,
        request_marker_value_load_offset=0x62728,
        request_magic_literal_offset=0x6275C,
        request_marker_address_literal_offset=0x62760,
        marker_poll_offset=0x545AA,
        marker_poll_address_literal_offset=0x54728,
        marker_poll_magic_literal_offset=0x5472C,
        wrapper_call_offset=0x545E4,
        wrapper_offset=0x22EE0,
        wrapper_source_literal_offset=0x22F00,
        trampoline_offset=0x63A98,
        trampoline_sha256=COMMON_TRAMPOLINE_SHA256,
        loader_marker_consumer_offset=0x47EC,
        loader_marker_address_literal_offset=0x4840,
        loader_marker_magic_literal_offset=0x4844,
        loader_marker_call_offset=0x5922,
        loader_updater_call_offset=0x5964,
        loader_updater_offset=0xA5F0,
        loader_app_validation_call_offset=0x5968,
        loader_app_validation_offset=0x2134,
        loader_app_slot_check_call_offset=0x213A,
        loader_app_slot_check_offset=0x6FE4,
        loader_app_failure_updater_call_offset=0x597C,
    ),
}


class EvidenceError(ValueError):
    """A pinned instruction or literal did not establish the claimed fact."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hex32(value: int) -> str:
    return f"0x{value:08x}"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise EvidenceError(f"16-bit read outside input at {hex32(offset)}")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise EvidenceError(f"32-bit read outside input at {hex32(offset)}")
    return struct.unpack_from("<I", data, offset)[0]


def decode_thumb_movs_immediate(data: bytes, instruction_offset: int) -> tuple[int, int]:
    instruction = _u16(data, instruction_offset)
    _require(
        instruction & 0xF800 == 0x2000,
        f"not a Thumb MOVS-immediate at {hex32(instruction_offset)}",
    )
    return (instruction >> 8) & 7, instruction & 0xFF


def decode_thumb_cmp_immediate(data: bytes, instruction_offset: int) -> tuple[int, int]:
    instruction = _u16(data, instruction_offset)
    _require(
        instruction & 0xF800 == 0x2800,
        f"not a Thumb CMP-immediate at {hex32(instruction_offset)}",
    )
    return (instruction >> 8) & 7, instruction & 0xFF


def decode_thumb_word_transfer(
    data: bytes, instruction_offset: int
) -> tuple[bool, int, int, int]:
    """Decode Thumb-1 word LDR/STR immediate.

    Returns ``(is_load, value_register, base_register, byte_offset)``.
    """

    instruction = _u16(data, instruction_offset)
    operation = instruction & 0xF800
    _require(
        operation in (0x6000, 0x6800),
        f"not a Thumb word LDR/STR immediate at {hex32(instruction_offset)}",
    )
    return (
        operation == 0x6800,
        instruction & 7,
        (instruction >> 3) & 7,
        ((instruction >> 6) & 0x1F) * 4,
    )


def decode_thumb_cmp_register(data: bytes, instruction_offset: int) -> tuple[int, int]:
    instruction = _u16(data, instruction_offset)
    _require(
        instruction & 0xFFC0 == 0x4280,
        f"not a Thumb CMP-register at {hex32(instruction_offset)}",
    )
    return instruction & 7, (instruction >> 3) & 7


def decode_thumb_mov_register(data: bytes, instruction_offset: int) -> tuple[int, int]:
    instruction = _u16(data, instruction_offset)
    _require(
        instruction & 0xFF00 == 0x4600,
        f"not a Thumb MOV-register at {hex32(instruction_offset)}",
    )
    destination = (instruction & 7) | ((instruction >> 4) & 8)
    source = (instruction >> 3) & 0xF
    return destination, source


def decode_thumb_cbz_cbnz(
    data: bytes, instruction_offset: int, runtime_base: int
) -> tuple[bool, int, int]:
    instruction = _u16(data, instruction_offset)
    _require(
        instruction & 0xF500 == 0xB100,
        f"not a Thumb CBZ/CBNZ at {hex32(instruction_offset)}",
    )
    displacement = (((instruction >> 9) & 1) << 6) | (
        ((instruction >> 3) & 0x1F) << 1
    )
    target = runtime_base + instruction_offset + 4 + displacement
    return bool(instruction & 0x0800), instruction & 7, target


def decode_thumb_conditional_branch(
    data: bytes, instruction_offset: int, runtime_base: int
) -> tuple[int, int]:
    instruction = _u16(data, instruction_offset)
    _require(
        instruction & 0xF000 == 0xD000 and (instruction >> 8) & 0xF < 0xE,
        f"not a Thumb conditional branch at {hex32(instruction_offset)}",
    )
    displacement = (instruction & 0xFF) << 1
    if displacement & 0x100:
        displacement -= 0x200
    return (instruction >> 8) & 0xF, runtime_base + instruction_offset + 4 + displacement


def decode_thumb_blx_register(data: bytes, instruction_offset: int) -> int:
    instruction = _u16(data, instruction_offset)
    _require(
        instruction & 0xFF87 == 0x4780,
        f"not a Thumb BLX-register at {hex32(instruction_offset)}",
    )
    return (instruction >> 3) & 0xF


def decode_thumb_msr_special(data: bytes, instruction_offset: int) -> tuple[int, int]:
    first = _u16(data, instruction_offset)
    second = _u16(data, instruction_offset + 2)
    _require(
        first & 0xFFF0 == 0xF380 and second & 0xFF00 == 0x8800,
        f"not a Thumb MSR-special-register at {hex32(instruction_offset)}",
    )
    return first & 0xF, second & 0xFF


def decode_thumb_ldr_literal(
    data: bytes,
    instruction_offset: int,
    expected_register: int,
) -> int:
    """Return the file offset addressed by a Thumb-1 LDR literal."""

    instruction = _u16(data, instruction_offset)
    _require(
        instruction & 0xF800 == 0x4800,
        f"not a Thumb LDR literal at {hex32(instruction_offset)}",
    )
    register = (instruction >> 8) & 7
    _require(
        register == expected_register,
        f"LDR literal at {hex32(instruction_offset)} targets r{register}, "
        f"not r{expected_register}",
    )
    pc = (instruction_offset + 4) & ~3
    return pc + (instruction & 0xFF) * 4


def decode_thumb_bl(data: bytes, instruction_offset: int, runtime_base: int) -> int:
    """Decode a Thumb-2 BL immediate and return its absolute target."""

    first = _u16(data, instruction_offset)
    second = _u16(data, instruction_offset + 2)
    _require(
        first & 0xF800 == 0xF000 and second & 0xD000 == 0xD000,
        f"not a Thumb BL at {hex32(instruction_offset)}",
    )
    sign = (first >> 10) & 1
    immediate_10 = first & 0x03FF
    j1 = (second >> 13) & 1
    j2 = (second >> 11) & 1
    i1 = (~(j1 ^ sign)) & 1
    i2 = (~(j2 ^ sign)) & 1
    immediate_11 = second & 0x07FF
    displacement = (
        (sign << 24)
        | (i1 << 23)
        | (i2 << 22)
        | (immediate_10 << 12)
        | (immediate_11 << 1)
    )
    if displacement & (1 << 24):
        displacement -= 1 << 25
    return (runtime_base + instruction_offset + 4 + displacement) & 0xFFFFFFFF


def _resolved_literal(
    data: bytes,
    instruction_offset: int,
    expected_register: int,
    expected_literal_offset: int,
) -> int:
    literal_offset = decode_thumb_ldr_literal(
        data, instruction_offset, expected_register
    )
    _require(
        literal_offset == expected_literal_offset,
        f"LDR at {hex32(instruction_offset)} resolves to "
        f"{hex32(literal_offset)}, expected {hex32(expected_literal_offset)}",
    )
    return _u32(data, literal_offset)


def _verify_request_handler(core1: bytes, profile: StockProfile) -> dict[str, Any]:
    base = profile.request_handler_offset
    value_load = profile.request_marker_value_load_offset
    _require(value_load == base + 0x30,
             "request marker-value load offset is not canonical")
    request_register, request_type = decode_thumb_cmp_immediate(core1, base + 0x10)
    length_register, comparison_bytes = decode_thumb_movs_immediate(
        core1, base + 0x24
    )
    _require((request_register, request_type) == (6, 9),
             "request handler does not compare request register r6 with type 9")
    _require((length_register, comparison_bytes) == (2, 8),
             "request handler does not request an eight-byte comparison")
    key_pointer = _resolved_literal(
        core1,
        base + 0x26,
        1,
        profile.request_key_pointer_literal_offset,
    )
    _require(
        key_pointer == profile.request_key_pointer,
        f"unexpected request-key pointer {hex32(key_pointer)}",
    )
    _require(decode_thumb_mov_register(core1, base + 0x28) == (0, 4),
             "request handler does not pass payload pointer r4 in r0")
    comparison_target = decode_thumb_bl(core1, base + 0x2A, CORE1_RUNTIME_BASE)
    _require(comparison_target == profile.request_compare_target,
             f"unexpected request comparison target {hex32(comparison_target)}")
    branch_nonzero, branch_register, branch_target = decode_thumb_cbz_cbnz(
        core1, base + 0x2E, CORE1_RUNTIME_BASE
    )
    _require(branch_nonzero and branch_register == 0,
             "request comparison failure does not use CBNZ r0")
    _require(branch_target > CORE1_RUNTIME_BASE + value_load + 4,
             "request comparison failure does not skip the marker write")
    marker_value = _resolved_literal(
        core1, value_load, 0, profile.request_magic_literal_offset
    )
    marker_address = _resolved_literal(
        core1, value_load + 2, 1, profile.request_marker_address_literal_offset
    )
    marker_store = decode_thumb_word_transfer(core1, value_load + 4)
    _require(marker_store == (False, 0, 1, 0),
             "request path does not store marker r0 at [r1]")
    _require(marker_value == LOADER_FLAG_VALUE, "request path writes wrong marker")
    _require(marker_address == LOADER_FLAG_ADDRESS, "request path writes wrong address")
    return {
        "request_type": request_type,
        "comparison_bytes": comparison_bytes,
        "comparison_target": hex32(comparison_target),
        "key_pointer": hex32(key_pointer),
        "marker_address": hex32(marker_address),
        "marker_value": hex32(marker_value),
        "write_requires_zero_compare_result": True,
    }


def _verify_marker_poll(core1: bytes, profile: StockProfile) -> dict[str, Any]:
    base = profile.marker_poll_offset
    marker_address = _resolved_literal(
        core1, base, 0, profile.marker_poll_address_literal_offset
    )
    marker_value = _resolved_literal(
        core1, base + 2, 1, profile.marker_poll_magic_literal_offset
    )
    _require(decode_thumb_word_transfer(core1, base + 4) == (True, 0, 0, 0),
             "marker poll does not load marker through r0")
    _require(decode_thumb_cmp_register(core1, base + 6) == (0, 1),
             "marker poll does not compare r0 with r1")
    condition, mismatch_target = decode_thumb_conditional_branch(
        core1, base + 8, CORE1_RUNTIME_BASE
    )
    _require(condition == 1, "marker mismatch branch is not BNE")
    _require(marker_address == LOADER_FLAG_ADDRESS, "poll reads wrong marker address")
    _require(marker_value == LOADER_FLAG_VALUE, "poll compares wrong marker value")
    call = profile.wrapper_call_offset
    interrupt_value = decode_thumb_movs_immediate(core1, call - 8)
    msr_source, special_register = decode_thumb_msr_special(core1, call - 6)
    _require(interrupt_value == (0, 1),
             "marker path does not prepare r0=1 before disabling interrupts")
    _require((msr_source, special_register) == (0, 0x10),
             "marker path does not write r0 to PRIMASK")
    wrapper_target = decode_thumb_bl(core1, call, CORE1_RUNTIME_BASE)
    expected_wrapper = CORE1_RUNTIME_BASE + profile.wrapper_offset
    _require(
        wrapper_target == expected_wrapper,
        f"marker path calls {hex32(wrapper_target)}, expected "
        f"{hex32(expected_wrapper)}",
    )
    return {
        "marker_address": hex32(marker_address),
        "marker_value": hex32(marker_value),
        "marker_mismatch_target": hex32(mismatch_target),
        "interrupts_disabled_before_wrapper": True,
        "wrapper_target": hex32(wrapper_target),
    }


def _verify_wrapper(core1: bytes, profile: StockProfile) -> dict[str, Any]:
    base = profile.wrapper_offset
    reserve_register, stack_reserve = decode_thumb_movs_immediate(core1, base + 2)
    length_register, copied_bytes = decode_thumb_movs_immediate(core1, base + 0xE)
    _require((reserve_register, stack_reserve) == (6, 0x98),
             "wrapper does not pin the stock 152-byte stack reserve")
    _require((length_register, copied_bytes) == (2, TRAMPOLINE_BYTES),
             "wrapper does not pass the 88-byte trampoline copy length in r2")
    source = _resolved_literal(
        core1, base + 0x10, 1, profile.wrapper_source_literal_offset
    )
    expected_source = CORE1_RUNTIME_BASE + profile.trampoline_offset
    _require(
        source == expected_source,
        f"wrapper copies from {hex32(source)}, expected {hex32(expected_source)}",
    )
    copy_target = decode_thumb_bl(core1, base + 0x14, CORE1_RUNTIME_BASE)
    _require(copy_target == CORE1_RUNTIME_BASE + 0xA, "unexpected copy-helper target")
    _require(decode_thumb_mov_register(core1, base + 0x12) == (0, 4),
             "wrapper does not pass relocated stack address r4 in r0")
    _require(decode_thumb_blx_register(core1, base + 0x1C) == 5,
             "wrapper does not call relocated Thumb entry through r5")
    return {
        "stack_reserve_bytes": stack_reserve,
        "copied_bytes": copied_bytes,
        "copy_source": hex32(source),
        "copy_helper_target": hex32(copy_target),
        "thumb_entry_bit_set": True,
    }


def _verify_trampoline(core1: bytes, profile: StockProfile) -> dict[str, Any]:
    base = profile.trampoline_offset
    end = base + TRAMPOLINE_BYTES
    _require(end <= len(core1), "trampoline extends outside Core1 input")
    observed_hash = sha256(core1[base:end])
    _require(
        observed_hash == profile.trampoline_sha256,
        f"unexpected 88-byte trampoline hash {observed_hash}",
    )
    # The ordered implementation is represented by its one-way digest rather
    # than reproduced as a stock byte sequence.  The three pinned profiles all
    # resolve to this independently audited semantic record.
    source = _u32(core1, base + 0x4C)
    aircr = _u32(core1, base + 0x50)
    key = _u32(core1, base + 0x54)
    _require(source == LOADER_FLASH_SOURCE, "trampoline uses wrong flash source")
    _require(aircr == AIRCR_ADDRESS, "trampoline uses wrong AIRCR address")
    _require(key == AIRCR_KEY_BASE, "trampoline uses wrong AIRCR key base")
    _require(
        CORE1_RUNTIME_BASE + base >= LOADER_COPY_BYTES,
        "stock trampoline is unexpectedly located inside overwritten PRAM",
    )
    return {
        "offset": hex32(base),
        "bytes": TRAMPOLINE_BYTES,
        "sha256": observed_hash,
        "semantic_basis": "pinned audited 88-byte digest",
        "executes_outside_pram": True,
        "interrupts_disabled": True,
        "source_start": hex32(source),
        "destination_start": hex32(0),
        "copy_bytes": LOADER_COPY_BYTES,
        "word_bytes": 4,
        "aircr_address": hex32(aircr),
        "aircr_prigroup_mask": hex32(AIRCR_PRIGROUP_MASK),
        "aircr_write": "(AIRCR & 0x00000700) | 0x05fa0004",
        "non_returning": True,
    }


def _verify_loader_consumer(loader: bytes, profile: StockProfile) -> dict[str, Any]:
    base = profile.loader_marker_consumer_offset
    marker_address = _resolved_literal(
        loader,
        base + 0x0A,
        0,
        profile.loader_marker_address_literal_offset,
    )
    marker_value = _resolved_literal(
        loader,
        base + 0x0E,
        1,
        profile.loader_marker_magic_literal_offset,
    )
    second_address = _resolved_literal(
        loader,
        base + 0x16,
        1,
        profile.loader_marker_address_literal_offset,
    )
    _require(marker_address == second_address == LOADER_FLAG_ADDRESS,
             "loader consumes or clears the wrong marker address")
    _require(marker_value == LOADER_FLAG_VALUE,
             "loader compares the wrong marker value")
    _require(decode_thumb_word_transfer(loader, base + 0x0C) == (True, 0, 0, 0),
             "loader does not read the retained marker through r0")
    _require(decode_thumb_cmp_register(loader, base + 0x10) == (0, 1),
             "loader does not compare retained marker r0 with magic r1")
    condition, absent_target = decode_thumb_conditional_branch(
        loader, base + 0x12, LOADER_RUNTIME_BASE
    )
    _require(condition == 1, "loader marker mismatch branch is not BNE")
    _require(decode_thumb_movs_immediate(loader, base + 0x14) == (0, 0),
             "loader does not prepare a zero marker-clear value")
    first_clear = decode_thumb_word_transfer(loader, base + 0x18)
    second_clear = decode_thumb_word_transfer(loader, base + 0x1A)
    _require(first_clear == second_clear == (False, 0, 1, 0),
             "loader does not clear [r1] from r0 twice")
    _require(decode_thumb_word_transfer(loader, base + 0x1E) == (True, 0, 0, 0),
             "loader does not read the cleared marker back")
    present_branch_nonzero, present_branch_register, present_return_target = (
        decode_thumb_cbz_cbnz(loader, base + 0x20, LOADER_RUNTIME_BASE)
    )
    _require(not present_branch_nonzero and present_branch_register == 0,
             "loader clear-readback success path is not CBZ r0")
    _require(decode_thumb_movs_immediate(loader, base + 0x32) == (0, 1),
             "loader marker-present result is not one")
    _require(decode_thumb_movs_immediate(loader, base + 0x3C) == (0, 0),
             "loader marker-absent result is not zero")

    consumer_target = decode_thumb_bl(
        loader, profile.loader_marker_call_offset, LOADER_RUNTIME_BASE
    )
    _require(
        consumer_target == profile.loader_marker_consumer_offset,
        f"early loader call targets {hex32(consumer_target)}, not marker consumer",
    )
    branch_nonzero, branch_register, no_marker_target = decode_thumb_cbz_cbnz(
        loader, profile.loader_marker_call_offset + 4, LOADER_RUNTIME_BASE
    )
    _require(not branch_nonzero and branch_register == 0,
             "loader does not use CBZ r0 after checking the marker")
    _require(no_marker_target == profile.loader_updater_call_offset + 4,
             "marker-absent branch does not skip the updater call")
    updater_target = decode_thumb_bl(
        loader, profile.loader_updater_call_offset, LOADER_RUNTIME_BASE
    )
    _require(
        updater_target == profile.loader_updater_offset,
        f"marker-present path targets {hex32(updater_target)}, expected updater "
        f"entry {hex32(profile.loader_updater_offset)}",
    )
    updater_init_target = decode_thumb_bl(
        loader, profile.loader_updater_offset, LOADER_RUNTIME_BASE
    )
    _require(updater_init_target == 0x5878, "unexpected updater initialization target")
    return {
        "consumer_offset": hex32(base),
        "marker_address": hex32(marker_address),
        "marker_value": hex32(marker_value),
        "clears_marker_twice": True,
        "verifies_clear_by_readback": True,
        "marker_absent_consumer_target": hex32(absent_target),
        "marker_present_return_target": hex32(present_return_target),
        "early_loader_call_offset": hex32(profile.loader_marker_call_offset),
        "marker_present_updater_entry": hex32(updater_target),
    }


def _verify_loader_app_failure_fallback(
    loader: bytes, profile: StockProfile
) -> dict[str, Any]:
    validation_target = decode_thumb_bl(
        loader, profile.loader_app_validation_call_offset, LOADER_RUNTIME_BASE
    )
    _require(validation_target == profile.loader_app_validation_offset,
             "loader app-validation call target changed")
    slot_check_target = decode_thumb_bl(
        loader, profile.loader_app_slot_check_call_offset, LOADER_RUNTIME_BASE
    )
    _require(slot_check_target == profile.loader_app_slot_check_offset,
             "loader app-slot check target changed")
    branch_nonzero, branch_register, valid_target = decode_thumb_cbz_cbnz(
        loader, profile.loader_app_validation_call_offset + 6, LOADER_RUNTIME_BASE
    )
    _require(branch_nonzero and branch_register == 4,
             "loader does not branch past fallback when app validation succeeds")
    _require(valid_target == profile.loader_app_failure_updater_call_offset + 4,
             "successful app-validation branch does not skip fallback updater call")
    updater_target = decode_thumb_bl(
        loader,
        profile.loader_app_failure_updater_call_offset,
        LOADER_RUNTIME_BASE,
    )
    _require(updater_target == profile.loader_updater_offset,
             "app-validation failure does not enter the updater")
    return {
        "app_validation_call_offset": hex32(profile.loader_app_validation_call_offset),
        "app_validation_target": hex32(validation_target),
        "app_slot_check_call_offset": hex32(profile.loader_app_slot_check_call_offset),
        "app_slot_check_target": hex32(slot_check_target),
        "success_branch_target": hex32(valid_target),
        "failure_updater_call_offset": hex32(
            profile.loader_app_failure_updater_call_offset
        ),
        "failure_updater_entry": hex32(updater_target),
    }


def _verify_loader_vectors(loader: bytes) -> dict[str, Any]:
    stack_pointer = _u32(loader, 0)
    reset_vector = _u32(loader, 4)
    _require(stack_pointer == 0x180148B8, "unexpected preserved-loader stack pointer")
    _require(reset_vector == 0x000002C9, "unexpected preserved-loader reset vector")
    _require(reset_vector & 1 == 1, "preserved-loader reset vector is not Thumb")
    return {
        "initial_stack_pointer": hex32(stack_pointer),
        "reset_vector": hex32(reset_vector),
    }


def profile_offsets(profile: StockProfile) -> dict[str, str]:
    names = (
        "request_handler_offset",
        "request_marker_value_load_offset",
        "marker_poll_offset",
        "wrapper_call_offset",
        "wrapper_offset",
        "trampoline_offset",
        "loader_marker_consumer_offset",
        "loader_marker_call_offset",
        "loader_updater_call_offset",
        "loader_updater_offset",
        "loader_app_validation_call_offset",
        "loader_app_slot_check_call_offset",
        "loader_app_failure_updater_call_offset",
    )
    return {name: hex32(getattr(profile, name)) for name in names}


def verify_images(
    profile: StockProfile,
    core1: bytes,
    loader: bytes,
    *,
    core1_label: str = "<memory>",
    loader_label: str = "<memory>",
) -> dict[str, Any]:
    """Return a JSON-serializable evidence report for one pinned pair."""

    core1_hash = sha256(core1)
    loader_hash = sha256(loader)
    checks: list[dict[str, Any]] = []
    facts: dict[str, Any] = {}

    def identity_check(
        name: str, actual_size: int, expected_size: int,
        actual_hash: str, expected_hash: str,
    ) -> None:
        passed = actual_size == expected_size and actual_hash == expected_hash
        checks.append({
            "name": name,
            "passed": passed,
            "actual_size": actual_size,
            "expected_size": expected_size,
            "actual_sha256": actual_hash,
            "expected_sha256": expected_hash,
        })

    identity_check(
        "core1_exact_identity",
        len(core1),
        profile.core1_size,
        core1_hash,
        profile.core1_sha256,
    )
    identity_check(
        "loader_exact_identity",
        len(loader),
        profile.loader_size,
        loader_hash,
        profile.loader_sha256,
    )

    semantic_checks: tuple[
        tuple[str, str, Callable[[], dict[str, Any]]], ...
    ] = (
        ("core1_request_type_9_marker_write", "request_handler",
         lambda: _verify_request_handler(core1, profile)),
        ("core1_marker_poll_to_wrapper", "marker_poll",
         lambda: _verify_marker_poll(core1, profile)),
        ("core1_stack_relocation_wrapper", "wrapper",
         lambda: _verify_wrapper(core1, profile)),
        ("core1_88_byte_loader_trampoline", "trampoline",
         lambda: _verify_trampoline(core1, profile)),
        ("loader_marker_consumer_and_updater_route", "loader_consumer",
         lambda: _verify_loader_consumer(loader, profile)),
        ("loader_app_failure_fallback_to_updater", "loader_app_failure_fallback",
         lambda: _verify_loader_app_failure_fallback(loader, profile)),
        ("loader_vector_identity", "loader_vectors",
         lambda: _verify_loader_vectors(loader)),
    )
    for check_name, fact_name, operation in semantic_checks:
        try:
            facts[fact_name] = operation()
        except (EvidenceError, struct.error) as error:
            checks.append({"name": check_name, "passed": False, "error": str(error)})
        else:
            checks.append({"name": check_name, "passed": True})

    passed = all(check["passed"] for check in checks)
    return {
        "format": "KB7 stock loader-reentry static evidence v1",
        "profile": profile.version,
        "passed": passed,
        "inputs": {
            "core1": {"name": core1_label, "size": len(core1), "sha256": core1_hash},
            "loader": {"name": loader_label, "size": len(loader), "sha256": loader_hash},
        },
        "pinned_offsets": profile_offsets(profile),
        "checks": checks,
        "facts": facts,
        "proof_boundary": (
            "Static identity and instruction semantics only. This proves the stock "
            "software-reset path copies the preserved loader into PRAM and routes "
            "the retained marker to updater entry; it does not prove custom code or "
            "hardware behavior."
        ),
        "device_accessed": False,
        "files_written": False,
    }


def verify_paths(
    profile: StockProfile,
    core1_path: Path,
    loader_path: Path,
) -> dict[str, Any]:
    core1_input = core1_path.expanduser()
    loader_input = loader_path.expanduser()
    return verify_images(
        profile,
        core1_input.read_bytes(),
        loader_input.read_bytes(),
        core1_label=core1_input.name,
        loader_label=loader_input.name,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only verification of a pinned stock loader/Core1 pair"
    )
    parser.add_argument("--version", required=True, choices=tuple(PROFILES))
    parser.add_argument("--core1", required=True, type=Path)
    parser.add_argument("--loader", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = verify_paths(PROFILES[args.version], args.core1, args.loader)
    except OSError as error:
        input_name = Path(error.filename).name if error.filename else None
        report = {
            "format": "KB7 stock loader-reentry static evidence v1",
            "profile": args.version,
            "passed": False,
            "error": {
                "type": type(error).__name__,
                "message": error.strerror or "input read failed",
                "input_name": input_name,
            },
            "device_accessed": False,
            "files_written": False,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
