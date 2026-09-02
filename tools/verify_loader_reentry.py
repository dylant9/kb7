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


# ---------------------------------------------------------------------------
# Generic Thumb/Thumb-2 decoding and interpretation of the relocation routine
# ---------------------------------------------------------------------------
#
# The 88-byte routine is decoded instruction by instruction from the public
# Arm Thumb encodings (masks and field extraction only) and then interpreted
# with a symbolic memory model: every loaded word is tracked as
# ``(word at address) & mask | bits`` so that the copy loop, the interrupt
# mask, the AIRCR read-modify-write and the final control flow are derived
# from what the code does, not from where its bytes happen to sit.  No stock
# byte sequence or listing appears here; the decoder is release-agnostic.

MASK32 = 0xFFFFFFFF
REG_PC = 15
SYSTEM_CONTROL_START = 0xE000E000  # System Control Space (SCB, NVIC, SysTick)
SYSTEM_CONTROL_END = 0xE000F000
SPECIAL_REGISTER_NAMES = {
    0x10: "PRIMASK",
    0x11: "BASEPRI",
    0x12: "BASEPRI_MAX",
    0x13: "FAULTMASK",
    0x14: "CONTROL",
}
CONDITION_NAMES = (
    "eq", "ne", "hs", "lo", "mi", "pl", "vs", "vc",
    "hi", "ls", "ge", "lt", "gt", "le", "al",
)
# The wrapper copies the routine onto its SRAM stack and branches into that
# copy, so its own address is far above every PRAM address.  Any base at or
# above the routine's self-location bound yields the same interpreted path.
MODELLED_SRAM_EXECUTION_BASE = 0x18000000
MAX_INTERPRETED_STEPS = 1 << 20


def thumb_expand_imm(i: int, imm3: int, imm8: int) -> int:
    """Expand a Thumb-2 12-bit modified immediate (Armv7-M ThumbExpandImm)."""

    imm12 = (i << 11) | (imm3 << 8) | imm8
    if imm12 < 0x400:
        selector = (imm12 >> 8) & 3
        if selector == 0:
            return imm8
        if selector == 1:
            return (imm8 << 16) | imm8
        if selector == 2:
            return (imm8 << 24) | (imm8 << 8)
        return (imm8 << 24) | (imm8 << 16) | (imm8 << 8) | imm8
    rotation = (imm12 >> 7) & 0x1F
    unrotated = 0x80 | (imm8 & 0x7F)
    return ((unrotated >> rotation) | (unrotated << (32 - rotation))) & MASK32


def _sign_extend(value: int, bits: int) -> int:
    if value & (1 << (bits - 1)):
        return value - (1 << bits)
    return value


def _literal_operand(data: bytes, literal_offset: int) -> int | None:
    if literal_offset < 0 or literal_offset + 4 > len(data):
        return None
    return _u32(data, literal_offset)


def decode_thumb_instruction(data: bytes, offset: int) -> tuple[Any, ...]:
    """Decode one Thumb/Thumb-2 instruction into ``(op, size, *operands)``.

    Only general-purpose forms that a small stackless copy-and-reset routine
    can use are recognised (moves, immediate/register arithmetic and logic,
    compares, word loads/stores, LDM/STM, branches, CPS/MSR, barriers and
    hints).  Anything else decodes to ``("unknown", size, ...)`` and the
    interpreter refuses it, so an undecoded body can never pass.
    """

    first = _u16(data, offset)
    if (first >> 11) in (0b11101, 0b11110, 0b11111):
        return _decode_thumb32(data, offset, first, _u16(data, offset + 2))
    return _decode_thumb16(data, offset, first)


def _decode_thumb16(data: bytes, offset: int, first: int) -> tuple[Any, ...]:
    top5 = first >> 11
    if top5 == 0b00100:
        return ("mov_imm", 2, (first >> 8) & 7, first & 0xFF, True)
    if top5 == 0b00101:
        return ("cmp_imm", 2, (first >> 8) & 7, first & 0xFF)
    if top5 == 0b00110:
        rdn = (first >> 8) & 7
        return ("add_imm", 2, rdn, rdn, first & 0xFF, True)
    if top5 == 0b00111:
        rdn = (first >> 8) & 7
        return ("sub_imm", 2, rdn, rdn, first & 0xFF, True)
    if first & 0xFE00 == 0x1C00:
        return ("add_imm", 2, first & 7, (first >> 3) & 7, (first >> 6) & 7, True)
    if first & 0xFE00 == 0x1E00:
        return ("sub_imm", 2, first & 7, (first >> 3) & 7, (first >> 6) & 7, True)
    if first & 0xFE00 == 0x1800:
        return ("add_reg", 2, first & 7, (first >> 3) & 7, (first >> 6) & 7, True)
    if first & 0xFE00 == 0x1A00:
        return ("sub_reg", 2, first & 7, (first >> 3) & 7, (first >> 6) & 7, True)
    if first & 0xFF00 == 0x4400:
        rdn = (first & 7) | ((first >> 4) & 8)
        return ("add_reg", 2, rdn, rdn, (first >> 3) & 0xF, False)
    if first & 0xFF00 == 0x4600:
        return ("mov_reg", 2, (first & 7) | ((first >> 4) & 8), (first >> 3) & 0xF)
    if first & 0xFFC0 == 0x4280:
        return ("cmp_reg", 2, first & 7, (first >> 3) & 7)
    if first & 0xFFC0 == 0x4000:
        return ("and_reg", 2, first & 7, first & 7, (first >> 3) & 7, True)
    if first & 0xFFC0 == 0x4040:
        return ("eor_reg", 2, first & 7, first & 7, (first >> 3) & 7, True)
    if first & 0xFFC0 == 0x4300:
        return ("orr_reg", 2, first & 7, first & 7, (first >> 3) & 7, True)
    if first & 0xFFC0 == 0x4380:
        return ("bic_reg", 2, first & 7, first & 7, (first >> 3) & 7, True)
    if first & 0xFF87 == 0x4700:
        return ("bx", 2, (first >> 3) & 0xF)
    if first & 0xFF87 == 0x4780:
        return ("blx", 2, (first >> 3) & 0xF)
    if top5 == 0b01001:
        literal = ((offset + 4) & ~3) + (first & 0xFF) * 4
        return ("ldr_lit", 2, (first >> 8) & 7, literal, _literal_operand(data, literal))
    if top5 == 0b01101:
        return ("ldr_imm", 2, first & 7, (first >> 3) & 7, ((first >> 6) & 0x1F) * 4, None)
    if top5 == 0b01100:
        return ("str_imm", 2, first & 7, (first >> 3) & 7, ((first >> 6) & 0x1F) * 4, None)
    if first & 0xFE00 == 0x5800:
        return ("ldr_reg", 2, first & 7, (first >> 3) & 7, (first >> 6) & 7, 0)
    if first & 0xFE00 == 0x5000:
        return ("str_reg", 2, first & 7, (first >> 3) & 7, (first >> 6) & 7, 0)
    if top5 == 0b11001:
        return ("ldm", 2, (first >> 8) & 7, first & 0xFF)
    if top5 == 0b11000:
        return ("stm", 2, (first >> 8) & 7, first & 0xFF)
    if first & 0xF500 == 0xB100:
        displacement = (((first >> 9) & 1) << 6) | (((first >> 3) & 0x1F) << 1)
        return ("cbnz" if first & 0x0800 else "cbz", 2, first & 7, offset + 4 + displacement)
    if first & 0xFFE8 == 0xB660:
        return ("cps", 2, bool(first & 0x10), bool(first & 2), bool(first & 1))
    if first & 0xFF0F == 0xBF00:
        return ("hint", 2, (first >> 4) & 0xF)
    if first & 0xFE00 == 0xBC00:
        return ("pop", 2, first & 0x1FF)
    if first & 0xFE00 == 0xB400:
        return ("push", 2, first & 0x1FF)
    if top5 in (0b11010, 0b11011):
        condition = (first >> 8) & 0xF
        if condition < 0xE:
            target = offset + 4 + _sign_extend(first & 0xFF, 8) * 2
            return ("bcond", 2, condition, target)
        return ("unknown", 2, first)
    if top5 == 0b11100:
        return ("b", 2, offset + 4 + _sign_extend(first & 0x7FF, 11) * 2)
    return ("unknown", 2, first)


def _decode_thumb32(
    data: bytes, offset: int, first: int, second: int
) -> tuple[Any, ...]:
    if first == 0xF3BF and second & 0xFF00 == 0x8F00:
        barrier = {4: "dsb", 5: "dmb", 6: "isb"}.get((second >> 4) & 0xF)
        if barrier is not None:
            return ("barrier", 4, barrier)
        return ("unknown", 4, first, second)
    if first & 0xFFF0 == 0xF380 and second & 0xFF00 == 0x8800:
        return ("msr", 4, first & 0xF, second & 0xFF)
    if first & 0xF800 == 0xF000 and second & 0x8000:
        sign = (first >> 10) & 1
        j1 = (second >> 13) & 1
        j2 = (second >> 11) & 1
        imm11 = second & 0x7FF
        if second & 0x5000 == 0x1000:
            if second & 0x4000:
                return ("bl", 4)
            i1 = (~(j1 ^ sign)) & 1
            i2 = (~(j2 ^ sign)) & 1
            displacement = _sign_extend(
                (sign << 24) | (i1 << 23) | (i2 << 22) | ((first & 0x3FF) << 12)
                | (imm11 << 1),
                25,
            )
            return ("b", 4, offset + 4 + displacement)
        if second & 0x5000 == 0 and (first >> 7) & 7 != 7:
            displacement = _sign_extend(
                (sign << 20) | (j2 << 19) | (j1 << 18) | ((first & 0x3F) << 12)
                | (imm11 << 1),
                21,
            )
            return ("bcond", 4, (first >> 6) & 0xF, offset + 4 + displacement)
        return ("unknown", 4, first, second)
    if first & 0xFA00 == 0xF000 and not second & 0x8000:
        operation = (first >> 5) & 0xF
        set_flags = bool(first & 0x10)
        rn = first & 0xF
        rd = (second >> 8) & 0xF
        immediate = thumb_expand_imm(
            (first >> 10) & 1, (second >> 12) & 7, second & 0xFF
        )
        if operation == 0b0000:
            if rd == REG_PC and set_flags:
                return ("tst_imm", 4, rn, immediate)
            return ("and_imm", 4, rd, rn, immediate, set_flags)
        if operation == 0b0001:
            return ("bic_imm", 4, rd, rn, immediate, set_flags)
        if operation == 0b0010:
            if rn == REG_PC:
                return ("mov_imm", 4, rd, immediate, set_flags)
            return ("orr_imm", 4, rd, rn, immediate, set_flags)
        if operation == 0b0100:
            if rd == REG_PC and set_flags:
                return ("unknown", 4, first, second)
            return ("eor_imm", 4, rd, rn, immediate, set_flags)
        if operation == 0b1000:
            if rd == REG_PC and set_flags:
                return ("unknown", 4, first, second)
            return ("add_imm", 4, rd, rn, immediate, set_flags)
        if operation == 0b1101:
            if rd == REG_PC and set_flags:
                return ("cmp_imm", 4, rn, immediate)
            return ("sub_imm", 4, rd, rn, immediate, set_flags)
        return ("unknown", 4, first, second)
    if first & 0xFA00 == 0xF200 and not second & 0x8000:
        operation = (first >> 4) & 0x1F
        rd = (second >> 8) & 0xF
        imm12 = (((first >> 10) & 1) << 11) | (((second >> 12) & 7) << 8) | (second & 0xFF)
        if operation == 0b00000:
            return ("add_imm", 4, rd, first & 0xF, imm12, False)
        if operation == 0b01010:
            return ("sub_imm", 4, rd, first & 0xF, imm12, False)
        if operation == 0b00100:
            return ("mov_imm", 4, rd, ((first & 0xF) << 12) | imm12, False)
        if operation == 0b01100:
            return ("movt", 4, rd, ((first & 0xF) << 12) | imm12)
        return ("unknown", 4, first, second)
    if first & 0xFF60 == 0xF840:
        is_load = bool(first & 0x10)
        rn = first & 0xF
        rt = second >> 12
        if rn == REG_PC:
            if not is_load:
                return ("unknown", 4, first, second)
            imm12 = second & 0xFFF
            literal = ((offset + 4) & ~3) + (imm12 if first & 0x80 else -imm12)
            return ("ldr_lit", 4, rt, literal, _literal_operand(data, literal))
        name = "ldr_imm" if is_load else "str_imm"
        if first & 0x80:
            return (name, 4, rt, rn, second & 0xFFF, None)
        if second & 0x0800:
            index_first = bool(second & 0x0400)
            writeback = bool(second & 0x0100)
            if not (index_first or writeback):
                return ("unknown", 4, first, second)
            delta = second & 0xFF
            if not second & 0x0200:
                delta = -delta
            return (name, 4, rt, rn, delta if index_first else 0,
                    delta if writeback else None)
        if second & 0x0FC0 == 0:
            name = "ldr_reg" if is_load else "str_reg"
            return (name, 4, rt, rn, second & 0xF, (second >> 4) & 3)
        return ("unknown", 4, first, second)
    return ("unknown", 4, first, second)


# Interpreter values are either a Python int (a known 32-bit constant) or a
# tuple: ("word", address, mask, bits) meaning ((word at address) & mask) |
# bits, ("pc", k) meaning the routine's own execution address plus k,
# ("lr",)/("sp",)/("arg", n) for the entry link register, stack pointer and
# argument registers, and ("opaque", why) for anything no longer tracked.


def _word_value(address: int, mask: int, bits: int) -> Any:
    if mask == 0:
        return bits
    return ("word", address, mask, bits)


def _value_add(a: Any, b: Any) -> Any:
    if isinstance(a, int) and isinstance(b, int):
        return (a + b) & MASK32
    if isinstance(a, int):
        a, b = b, a
    if isinstance(b, int) and isinstance(a, tuple):
        if a[0] == "pc":
            return ("pc", (a[1] + b) & MASK32)
        if a[0] == "word" and b & (a[2] | a[3]) == 0:
            # No operand bit can carry into another, so the add is an OR.
            return ("word", a[1], a[2], a[3] | b)
    return ("opaque", "add")


def _value_sub(a: Any, b: Any) -> Any:
    if isinstance(a, int) and isinstance(b, int):
        return (a - b) & MASK32
    if isinstance(a, tuple) and isinstance(b, int) and a[0] == "pc":
        return ("pc", (a[1] - b) & MASK32)
    return ("opaque", "sub")


def _value_and(a: Any, b: Any) -> Any:
    if isinstance(a, int) and isinstance(b, int):
        return a & b
    if isinstance(a, int):
        a, b = b, a
    if isinstance(b, int) and isinstance(a, tuple) and a[0] == "word":
        return _word_value(a[1], a[2] & b, a[3] & b)
    return ("opaque", "and")


def _value_or(a: Any, b: Any) -> Any:
    if isinstance(a, int) and isinstance(b, int):
        return a | b
    if isinstance(a, int):
        a, b = b, a
    if isinstance(b, int) and isinstance(a, tuple) and a[0] == "word":
        return _word_value(a[1], a[2] & ~b & MASK32, a[3] | b)
    return ("opaque", "or")


def _value_eor(a: Any, b: Any) -> Any:
    if isinstance(a, int) and isinstance(b, int):
        return a ^ b
    return ("opaque", "eor")


def _value_bic(a: Any, b: Any) -> Any:
    if isinstance(b, int):
        return _value_and(a, ~b & MASK32)
    return ("opaque", "bic")


def _flags_from_sub(a: int, b: int) -> tuple[int, int, int, int]:
    result = (a - b) & MASK32
    overflow = ((a ^ b) & (a ^ result)) >> 31
    return result >> 31, int(result == 0), int(a >= b), overflow


def _flags_from_add(a: int, b: int) -> tuple[int, int, int, int]:
    total = a + b
    result = total & MASK32
    overflow = (~(a ^ b) & (a ^ result) & MASK32) >> 31
    return result >> 31, int(result == 0), int(total > MASK32), overflow


_CONDITION_FLAGS = (
    "z", "z", "c", "c", "n", "n", "v", "v",
    "cz", "cz", "nv", "nv", "znv", "znv", "",
)


def _condition_holds(condition: int, flags: tuple[Any, ...]) -> bool:
    n, z, c, v = flags
    if condition == 0:
        return z == 1
    if condition == 1:
        return z == 0
    if condition == 2:
        return c == 1
    if condition == 3:
        return c == 0
    if condition == 4:
        return n == 1
    if condition == 5:
        return n == 0
    if condition == 6:
        return v == 1
    if condition == 7:
        return v == 0
    if condition == 8:
        return c == 1 and z == 0
    if condition == 9:
        return c == 0 or z == 1
    if condition == 10:
        return n == v
    if condition == 11:
        return n != v
    if condition == 12:
        return z == 0 and n == v
    if condition == 13:
        return z == 1 or n != v
    return True


@dataclass
class RoutineTrace:
    """What one interpreted execution of the routine did."""

    terminal: str
    steps: int
    executed_offsets: set[int]
    literal_reads: set[int]
    stores: list[tuple[int, int, Any]]
    mask_events: list[tuple[int, str, bool]]
    barriers: list[tuple[int, str]]
    guard_compares: list[tuple[int, int, int, str, bool]]
    ops_after_last_store: list[str]
    return_value: Any


def interpret_thumb_routine(
    routine: bytes,
    *,
    pc_base: int,
    max_steps: int = MAX_INTERPRETED_STEPS,
) -> RoutineTrace:
    """Interpret ``routine`` from offset 0 until it parks or returns.

    ``pc_base`` is the execution address assumed whenever the routine reads
    its own program counter and compares it with a constant; the comparison
    is recorded so the caller can derive the self-location bound.  Memory is
    symbolic: loads of never-written words yield tracked ``word`` values and
    every store is logged.  Any instruction outside the supported subset, any
    non-constant address, any data-dependent branch, any call, any stack use
    or any escape from the routine raises :class:`EvidenceError`.
    """

    decoded: dict[int, tuple[Any, ...]] = {}
    memory: dict[int, Any] = {}
    stores: list[tuple[int, int, Any]] = []
    mask_events: list[tuple[int, str, bool]] = []
    barriers: list[tuple[int, str]] = []
    guard_compares: list[tuple[int, int, int, str, bool]] = []
    ops_after_last_store: list[str] = []
    executed: set[int] = set()
    literal_reads: set[int] = set()
    regs: list[Any] = [("arg", index) for index in range(13)]
    regs.append(("sp",))
    regs.append(("lr",))
    regs.append(None)  # r15 is read through ``read``
    flags: Any = None
    offset = 0
    steps = 0
    terminal = ""
    return_value: Any = None

    def read(register: int) -> Any:
        if register == REG_PC:
            return ("pc", offset + 4)
        return regs[register]

    def write(register: int, value: Any) -> None:
        if register == REG_PC:
            raise EvidenceError(f"computed branch through PC at {hex32(offset)}")
        regs[register] = value

    def constant_address(value: Any, what: str) -> int:
        if not isinstance(value, int):
            raise EvidenceError(f"{what} at {hex32(offset)} uses a non-constant address")
        if value & 3:
            raise EvidenceError(f"unaligned {what} at {hex32(offset)}")
        return value

    def load_word(address: int) -> Any:
        if address in memory:
            return memory[address]
        return ("word", address, MASK32, 0)

    def store_word(address: int, value: Any) -> None:
        memory[address] = value
        stores.append((steps, address, value))
        ops_after_last_store.clear()

    def nz_flags(value: Any) -> Any:
        if not isinstance(value, int):
            return None
        if isinstance(flags, tuple) and flags[0] != "pc_cmp":
            carry, overflow = flags[2], flags[3]
        else:
            carry, overflow = None, None
        return (value >> 31, int(value == 0), carry, overflow)

    def compare_flags(a: Any, b: Any) -> Any:
        if isinstance(a, int) and isinstance(b, int):
            return _flags_from_sub(a, b)
        if isinstance(a, tuple) and a[0] == "pc" and isinstance(b, int):
            return ("pc_cmp", a[1], b, True)
        if isinstance(b, tuple) and b[0] == "pc" and isinstance(a, int):
            return ("pc_cmp", b[1], a, False)
        return None

    def branch_taken(condition: int) -> bool:
        if flags is None:
            raise EvidenceError(
                f"conditional branch at {hex32(offset)} depends on unknown flags"
            )
        if flags[0] == "pc_cmp":
            _, k, constant, pc_left = flags
            pc_value = (pc_base + k) & MASK32
            concrete = (_flags_from_sub(pc_value, constant) if pc_left
                        else _flags_from_sub(constant, pc_value))
            taken = _condition_holds(condition, concrete)
            guard_compares.append(
                (steps, k, constant, CONDITION_NAMES[condition], taken)
            )
            return taken
        for name in _CONDITION_FLAGS[condition]:
            if flags["nzcv".index(name)] is None:
                raise EvidenceError(
                    f"conditional branch at {hex32(offset)} depends on an "
                    f"unknown {name.upper()} flag"
                )
        return _condition_holds(condition, flags)

    while True:
        if steps >= max_steps:
            raise EvidenceError(
                f"routine did not park or return within {max_steps} instructions"
            )
        if offset < 0 or offset + 2 > len(routine):
            raise EvidenceError(f"control flow leaves the routine at {hex32(offset)}")
        instruction = decoded.get(offset)
        if instruction is None:
            instruction = decode_thumb_instruction(routine, offset)
            if offset + instruction[1] > len(routine):
                raise EvidenceError(
                    f"instruction at {hex32(offset)} extends past the routine"
                )
            decoded[offset] = instruction
        executed.add(offset)
        steps += 1
        op = instruction[0]
        next_offset = offset + instruction[1]

        if op == "ldr_lit":
            _, _, rt, literal, value = instruction
            if value is None:
                raise EvidenceError(
                    f"literal load at {hex32(offset)} reads outside the routine"
                )
            literal_reads.add(literal)
            write(rt, value)
            ops_after_last_store.append(op)
        elif op == "ldr_imm" or op == "str_imm":
            _, _, rt, rn, displacement, writeback = instruction
            base_value = read(rn)
            address = constant_address(
                _value_add(base_value, displacement), "word transfer"
            )
            if op == "ldr_imm":
                write(rt, load_word(address))
                ops_after_last_store.append(op)
            else:
                store_word(address, read(rt))
            if writeback is not None:
                write(rn, _value_add(base_value, writeback))
        elif op == "ldr_reg" or op == "str_reg":
            _, _, rt, rn, rm, shift = instruction
            index = read(rm)
            if not isinstance(index, int):
                raise EvidenceError(
                    f"register-offset transfer at {hex32(offset)} has a "
                    "non-constant index"
                )
            address = constant_address(
                _value_add(read(rn), (index << shift) & MASK32), "word transfer"
            )
            if op == "ldr_reg":
                write(rt, load_word(address))
                ops_after_last_store.append(op)
            else:
                store_word(address, read(rt))
        elif op == "ldm" or op == "stm":
            _, _, rn, register_list = instruction
            address = constant_address(read(rn), "multiple word transfer")
            registers = [index for index in range(8) if register_list >> index & 1]
            if not registers:
                raise EvidenceError(f"empty register list at {hex32(offset)}")
            for index, register in enumerate(registers):
                if op == "ldm":
                    write(register, load_word(address + 4 * index))
                else:
                    store_word(address + 4 * index, read(register))
            if op == "stm" or rn not in registers:
                write(rn, address + 4 * len(registers))
            if op == "ldm":
                ops_after_last_store.append(op)
        elif op == "mov_imm":
            _, _, rd, immediate, set_flags = instruction
            write(rd, immediate)
            if set_flags:
                flags = nz_flags(immediate)
            ops_after_last_store.append(op)
        elif op == "movt":
            _, _, rd, immediate = instruction
            current = read(rd)
            if not isinstance(current, int):
                raise EvidenceError(f"MOVT at {hex32(offset)} on a non-constant")
            write(rd, (current & 0xFFFF) | (immediate << 16))
            ops_after_last_store.append(op)
        elif op == "mov_reg":
            _, _, rd, rm = instruction
            write(rd, read(rm))
            ops_after_last_store.append(op)
        elif op == "cmp_imm" or op == "cmp_reg":
            _, _, rn, operand = instruction
            other = operand if op == "cmp_imm" else read(operand)
            flags = compare_flags(read(rn), other)
            ops_after_last_store.append(op)
        elif op == "tst_imm":
            _, _, rn, immediate = instruction
            flags = nz_flags(_value_and(read(rn), immediate))
            ops_after_last_store.append(op)
        elif op in ("add_imm", "sub_imm", "add_reg", "sub_reg"):
            _, _, rd, rn, operand, set_flags = instruction
            left = read(rn)
            right = operand if op.endswith("_imm") else read(operand)
            if op.startswith("add"):
                result = _value_add(left, right)
                if set_flags:
                    flags = (_flags_from_add(left, right)
                             if isinstance(left, int) and isinstance(right, int)
                             else None)
            else:
                result = _value_sub(left, right)
                if set_flags:
                    flags = compare_flags(left, right)
            write(rd, result)
            ops_after_last_store.append(op)
        elif op in ("and_imm", "orr_imm", "eor_imm", "bic_imm",
                    "and_reg", "orr_reg", "eor_reg", "bic_reg"):
            _, _, rd, rn, operand, set_flags = instruction
            left = read(rn)
            right = operand if op.endswith("_imm") else read(operand)
            operation = {
                "and": _value_and, "orr": _value_or,
                "eor": _value_eor, "bic": _value_bic,
            }[op[:3]]
            result = operation(left, right)
            write(rd, result)
            if set_flags:
                flags = nz_flags(result)
            ops_after_last_store.append(op)
        elif op == "msr":
            _, _, rn, sysm = instruction
            name = SPECIAL_REGISTER_NAMES.get(sysm)
            value = read(rn)
            if name not in ("PRIMASK", "FAULTMASK", "BASEPRI", "BASEPRI_MAX"):
                raise EvidenceError(
                    f"unsupported special-register write at {hex32(offset)}"
                )
            if not isinstance(value, int):
                raise EvidenceError(
                    f"special-register write at {hex32(offset)} uses an "
                    "unknown value"
                )
            if name in ("PRIMASK", "FAULTMASK"):
                mask_events.append((steps, name, bool(value & 1)))
            else:
                mask_events.append((steps, "BASEPRI", value != 0))
            ops_after_last_store.append(op)
        elif op == "cps":
            _, _, disable, affects_i, affects_f = instruction
            if affects_i:
                mask_events.append((steps, "PRIMASK", disable))
            if affects_f:
                mask_events.append((steps, "FAULTMASK", disable))
            ops_after_last_store.append(op)
        elif op == "barrier":
            barriers.append((steps, instruction[2]))
            ops_after_last_store.append(op)
        elif op == "hint":
            ops_after_last_store.append(op)
        elif op == "b":
            target = instruction[2]
            ops_after_last_store.append(op)
            if target == offset:
                terminal = "branch_to_self"
                break
            next_offset = target
        elif op == "bcond":
            _, _, condition, target = instruction
            ops_after_last_store.append(op)
            if branch_taken(condition):
                next_offset = target
        elif op == "cbz" or op == "cbnz":
            _, _, rn, target = instruction
            value = read(rn)
            ops_after_last_store.append(op)
            if isinstance(value, int):
                is_zero = value == 0
            elif isinstance(value, tuple) and value[0] == "pc":
                is_zero = ((pc_base + value[1]) & MASK32) == 0
            else:
                raise EvidenceError(
                    f"compare-and-branch at {hex32(offset)} depends on an "
                    "unknown value"
                )
            if is_zero != (op == "cbnz"):
                next_offset = target
        elif op == "bx":
            value = read(instruction[2])
            if value == ("lr",):
                terminal = "returned"
                return_value = regs[0]
                break
            raise EvidenceError(
                f"BX at {hex32(offset)} targets something other than the "
                "entry link register"
            )
        elif op in ("bl", "blx"):
            raise EvidenceError(f"routine calls out at {hex32(offset)}")
        elif op in ("push", "pop"):
            raise EvidenceError(f"routine uses the stack at {hex32(offset)}")
        else:
            raise EvidenceError(
                f"unsupported or undecodable instruction at {hex32(offset)}"
            )
        offset = next_offset

    return RoutineTrace(
        terminal=terminal,
        steps=steps,
        executed_offsets=executed,
        literal_reads=literal_reads,
        stores=stores,
        mask_events=mask_events,
        barriers=barriers,
        guard_compares=guard_compares,
        ops_after_last_store=ops_after_last_store,
        return_value=return_value,
    )


def _in_system_control_space(address: int) -> bool:
    return SYSTEM_CONTROL_START <= address < SYSTEM_CONTROL_END


def derive_relocation_semantics(trace: RoutineTrace) -> dict[str, Any]:
    """Derive copy, mask, reset and termination facts from one trace.

    Every value returned here comes from the interpreted stores, special
    register writes and branches; nothing is assumed from byte positions.
    """

    _require(
        trace.terminal == "branch_to_self",
        f"routine does not park in an endless loop after the reset request "
        f"(it {trace.terminal or 'stopped'})",
    )
    _require(bool(trace.stores), "routine stores nothing")
    reset_stores = [s for s in trace.stores if _in_system_control_space(s[1])]
    copy_stores = [s for s in trace.stores if not _in_system_control_space(s[1])]
    _require(
        len(reset_stores) == 1,
        f"expected exactly one system-control write, found {len(reset_stores)}",
    )
    reset_step, reset_address, reset_value = reset_stores[0]
    _require(reset_stores[0] is trace.stores[-1],
             "the reset request is not the last store")
    _require(
        isinstance(reset_value, tuple) and reset_value[0] == "word"
        and reset_value[1] == reset_address,
        "reset write is not a read-modify-write of the same register",
    )
    _, _, reset_mask, reset_bits = reset_value
    _require(bool(copy_stores), "no copy stores precede the reset request")
    addresses = sorted(store[1] for store in copy_stores)
    destination = addresses[0]
    word_count = len(copy_stores)
    _require(
        addresses == list(range(destination, destination + 4 * word_count, 4)),
        "copy stores do not form one contiguous run of distinct words",
    )
    deltas: set[int] = set()
    for _, address, value in copy_stores:
        _require(
            isinstance(value, tuple) and value[0] == "word"
            and value[2] == MASK32 and value[3] == 0,
            f"word stored at {hex32(address)} is not an unmodified loaded word",
        )
        deltas.add((value[1] - address) & MASK32)
    _require(len(deltas) == 1, "copied words do not come from one contiguous source")
    source = (destination + deltas.pop()) & MASK32
    stored_order = [store[1] for store in copy_stores]
    if stored_order == addresses:
        copy_order = "ascending"
    elif stored_order == addresses[::-1]:
        copy_order = "descending"
    else:
        copy_order = "other"
    disables = [event for event in trace.mask_events
                if event[2] and event[1] in ("PRIMASK", "FAULTMASK")]
    _require(bool(disables), "routine never disables interrupts")
    _require(disables[0][0] < copy_stores[0][0],
             "copying begins before interrupts are disabled")
    _require(not any(not event[2] for event in trace.mask_events),
             "routine re-enables interrupts")
    _require(
        all(op in ("barrier", "hint", "b") for op in trace.ops_after_last_store),
        "instructions other than barriers, hints and the parking branch follow "
        "the reset request",
    )
    constants = {compare[2] for compare in trace.guard_compares}
    _require(
        len(constants) == 1,
        "routine does not compare its own address against exactly one bound",
    )
    return {
        "self_location_guard_bound": constants.pop(),
        "interrupt_mask": disables[0][1],
        "source_start": source,
        "destination_start": destination,
        "copy_bytes": 4 * word_count,
        "word_bytes": 4,
        "copy_order": copy_order,
        "aircr_address": reset_address,
        "aircr_prigroup_mask": reset_mask,
        "aircr_or_bits": reset_bits,
        "reset_step": reset_step,
    }


def _verify_trampoline(core1: bytes, profile: StockProfile) -> dict[str, Any]:
    base = profile.trampoline_offset
    end = base + TRAMPOLINE_BYTES
    _require(end <= len(core1), "trampoline extends outside Core1 input")
    routine = bytes(core1[base:end])
    observed_hash = sha256(routine)
    _require(
        observed_hash == profile.trampoline_sha256,
        f"unexpected 88-byte trampoline hash {observed_hash}",
    )
    # The pinned literal cells stay as an independent check; the semantics
    # below are derived by decoding and interpreting the routine itself.
    source_literal = _u32(routine, 0x4C)
    aircr_literal = _u32(routine, 0x50)
    key_literal = _u32(routine, 0x54)
    _require(source_literal == LOADER_FLASH_SOURCE, "trampoline uses wrong flash source")
    _require(aircr_literal == AIRCR_ADDRESS, "trampoline uses wrong AIRCR address")
    _require(key_literal == AIRCR_KEY_BASE, "trampoline uses wrong AIRCR key base")
    _require(
        CORE1_RUNTIME_BASE + base >= LOADER_COPY_BYTES,
        "stock trampoline is unexpectedly located inside overwritten PRAM",
    )

    outside = interpret_thumb_routine(routine, pc_base=MODELLED_SRAM_EXECUTION_BASE)
    semantics = derive_relocation_semantics(outside)
    _require(
        {0x4C, 0x50, 0x54} <= outside.literal_reads,
        "routine does not read the pinned source, AIRCR and key literals",
    )
    copy_bytes = semantics["copy_bytes"]
    _require(
        semantics["destination_start"] == 0,
        f"routine copies to {hex32(semantics['destination_start'])}, not PRAM zero",
    )
    _require(
        copy_bytes == LOADER_COPY_BYTES,
        f"routine copies {hex32(copy_bytes)} bytes, expected {hex32(LOADER_COPY_BYTES)}",
    )
    _require(
        semantics["source_start"] == source_literal,
        f"routine copies from {hex32(semantics['source_start'])}, not the pinned "
        f"flash source {hex32(source_literal)}",
    )
    _require(
        semantics["aircr_address"] == aircr_literal,
        f"reset write targets {hex32(semantics['aircr_address'])}, not AIRCR",
    )
    _require(
        semantics["aircr_prigroup_mask"] == AIRCR_PRIGROUP_MASK,
        f"reset write preserves AIRCR bits {hex32(semantics['aircr_prigroup_mask'])}, "
        f"expected exactly PRIGROUP {hex32(AIRCR_PRIGROUP_MASK)}",
    )
    _require(
        semantics["aircr_or_bits"] == (AIRCR_KEY_BASE | AIRCR_SYSRESETREQ),
        f"reset write sets AIRCR bits {hex32(semantics['aircr_or_bits'])}, expected "
        f"VECTKEY plus SYSRESETREQ {hex32(AIRCR_KEY_BASE | AIRCR_SYSRESETREQ)}",
    )
    bound = semantics["self_location_guard_bound"]
    _require(
        bound == copy_bytes,
        f"self-location guard bound {hex32(bound)} differs from the copy length",
    )
    inside = interpret_thumb_routine(routine, pc_base=max(4, bound // 2))
    _require(
        inside.terminal == "returned" and not inside.stores
        and not inside.mask_events,
        "routine does not refuse to run from inside its own destination window",
    )
    aircr_write = (
        f"(AIRCR & {hex32(semantics['aircr_prigroup_mask'])}) | "
        f"{hex32(semantics['aircr_or_bits'])}"
    )
    return {
        "offset": hex32(base),
        "bytes": TRAMPOLINE_BYTES,
        "sha256": observed_hash,
        "semantic_basis": (
            "decoded and interpreted Thumb-2 instruction semantics; the pinned "
            "88-byte digest and literal cells are additional checks"
        ),
        "decoded_instruction_count": len(
            outside.executed_offsets | inside.executed_offsets
        ),
        "interpreted_steps": outside.steps,
        "executes_outside_pram": True,
        "self_location_guard_bound": hex32(bound),
        "refuses_to_run_inside_destination_window": True,
        "inside_window_return_value": (
            hex32(inside.return_value) if isinstance(inside.return_value, int)
            else None
        ),
        "interrupts_disabled": True,
        "interrupt_mask": semantics["interrupt_mask"],
        "source_start": hex32(semantics["source_start"]),
        "destination_start": hex32(semantics["destination_start"]),
        "copy_bytes": copy_bytes,
        "word_bytes": semantics["word_bytes"],
        "copy_order": semantics["copy_order"],
        "aircr_address": hex32(semantics["aircr_address"]),
        "aircr_prigroup_mask": hex32(semantics["aircr_prigroup_mask"]),
        "aircr_write": aircr_write,
        "reset_write_is_last_store": True,
        "non_returning": True,
        "terminal_behaviour": outside.terminal,
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
