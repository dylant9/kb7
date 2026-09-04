#!/usr/bin/env python3
"""Read-only verification of the stock Core 0 to region-1 boot contract.

This tool re-derives, from the owner-local stock V1.22 region-0 ("core0"),
region-1 ("core1") and loader images, the facts that a replacement region-1
image relies on when the stock region 0 is kept unchanged:

* the reset path of stock region 0 (vector table, hardware initialization,
  scatter loading, C runtime entry) and the single call into region 1;
* what region 0 has set up when that call happens (stack, region-1 copy into
  OPI DRAM behind the instruction-cache aperture, watchdogs, interrupts);
* that nothing on that path depends on region-1 content beyond copying it and
  calling its fixed entry; and
* the fixed surfaces in both directions (vectors and veneers into region 1,
  the region-1 import thunk table into region 0).

It decodes public Arm Thumb instruction forms at pinned offsets and reads the
literal words they address.  The reachable-code ranges of the reset path were
derived offline with a disassembler; this tool pins those ranges by hash and
checks, inside them, the absence of every constant that would contradict the
contract.  It never opens a device and never writes a file.  Raw stock bytes
stay outside the repository; the report contains offsets, decoded values and
hashes only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


TOOL_DIRECTORY = Path(__file__).resolve().parent


def _load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load required module: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


_reentry = _load_module(
    "verify_loader_reentry_for_region1_contract",
    TOOL_DIRECTORY / "verify_loader_reentry.py")

EvidenceError = _reentry.EvidenceError
decode = _reentry.decode_thumb_instruction

REGION0_RUNTIME_BASE = 0x00000000
REGION1_RUNTIME_BASE = 0x10000000
REGION1_APERTURE_END = 0x10100000
REGION1_FLASH_SOURCE = 0x60021000
REGION1_OPI_COPY = 0x30722000
REGION1_COPY_BYTES = 0x000DE000
ICACHE_BASE = 0x4002F000
SFC_BASE = 0x40022000
SYS1_CLOCK_RESET = 0x4500010C
VTOR = 0xE000ED08
NVIC_ISER_START = 0xE000E100
NVIC_ISER_END = 0xE000E140
SYSTICK_CSR = 0xE000E010
USB_BASE = 0x40100000
USB_END = 0x40200000
USB_PHY_ENABLE = 0x45000110
VECTOR_COUNT = 79
THUNK_BYTES = 10
REG_SP = 13
REG_IP = 12


@dataclass(frozen=True)
class Region0Profile:
    """Pinned facts for one stock region-0/region-1/loader triple."""

    version: str
    core0_size: int
    core0_sha256: str
    core1_size: int
    core1_sha256: str
    loader_size: int
    loader_sha256: str
    stack_top: int
    reset_offset: int
    hardware_init_offset: int
    scatter_entry_offset: int
    runtime_entry_offset: int
    runtime_library_init_offset: int
    stack_setup_offset: int
    stack_descriptor_offset: int
    handoff_veneer_offset: int
    region1_entry: int
    region1_main_length: int
    hardware_init_calls: tuple[int, ...]
    region1_copy_offset: int
    memcpy_offset: int
    primask_release_offset: int
    scatter_table_offset: int
    scatter_table_end: int
    scatter_entries: tuple[tuple[int, int, int, int], ...]
    decompress_handler: int
    copy_handler: int
    zero_handler: int
    heap_base: int
    heap_limit: int
    stack_limit: int
    region1_vectors: tuple[tuple[int, int], ...]
    zero_vectors: frozenset[int]
    usb_irq_vector: tuple[int, int]
    reset_closure_ranges: tuple[tuple[int, int], ...]
    reset_closure_sha256: str
    reset_closure_sram_constants: tuple[int, ...]
    reset_closure_rom_calls: tuple[int, ...]
    loader_closure_ranges: tuple[tuple[int, int], ...]
    loader_closure_sha256: str
    loader_closure_aperture_bit_immediates: tuple[int, ...]
    thunk_count: int
    thunk_targets: tuple[int, ...]
    veneer_count: int
    region1_main_sha256: str


V122_RESET_CLOSURE = (
    (0x140, 0x174), (0x2A8, 0x30A), (0x32C, 0x336), (0x846, 0x934),
    (0x9C8, 0xA48), (0xA50, 0xA54), (0xA88, 0xAD8), (0xAE6, 0xAF0),
    (0xF1C, 0xF20), (0x1794, 0x17EC), (0x17FC, 0x1800), (0x1968, 0x199A),
    (0x19D4, 0x1A06), (0x60B8, 0x60E2), (0x614C, 0x6162), (0x617E, 0x61D8),
    (0x6AB8, 0x6AF0), (0x6B8E, 0x6BBA), (0x6E68, 0x6EAE), (0x6EBC, 0x6F62),
    (0x6F70, 0x6FF4), (0x7008, 0x7090), (0x70B0, 0x7128), (0x7138, 0x72D2),
    (0x731C, 0x73BA), (0x73C4, 0x73F4), (0x7444, 0x7468), (0x8A8C, 0x8ABE),
    (0x8AD8, 0x8EDC), (0x90AA, 0x90AC), (0x9106, 0x910A), (0x9A74, 0x9A90),
    (0x9B38, 0x9B70), (0xB48C, 0xB4DE), (0xB502, 0xB504), (0xCFA4, 0xCFC6),
    (0xCFD0, 0xCFF2), (0xD00A, 0xD188), (0xD1CC, 0xD218), (0xD222, 0xD27C),
    (0xD284, 0xD384), (0xD392, 0xD39A), (0xD3AE, 0xD41A), (0xD43A, 0xD458),
    (0xD466, 0xD542),
)

V122_LOADER_CLOSURE = (
    (0x1F4, 0x284), (0x324, 0x37C), (0x3B8, 0x680), (0x748, 0x83E),
    (0x8C6, 0x954), (0x964, 0x98C), (0x996, 0x9B6), (0x9D6, 0xA02),
    (0xAC0, 0xB2C), (0xB3C, 0xBA2), (0xBAC, 0x1490), (0x14AC, 0x14C4),
    (0x1560, 0x15D8), (0x15E8, 0x16C8), (0x16F6, 0x1A92), (0x1B12, 0x1EEC),
    (0x1EF8, 0x200E), (0x201E, 0x2042), (0x2048, 0x2128), (0x2134, 0x2210),
    (0x22C0, 0x22D0), (0x2508, 0x2640), (0x27B8, 0x27EA), (0x27F4, 0x28EE),
    (0x28FC, 0x2962), (0x296C, 0x2A2E), (0x2A3C, 0x2A88), (0x2A90, 0x2B9E),
    (0x2BA4, 0x2C6A), (0x2C74, 0x2D3E), (0x2D48, 0x2D78), (0x2D80, 0x2E4C),
    (0x2E58, 0x2E8A), (0x307C, 0x30F0), (0x30F8, 0x3194), (0x319C, 0x31A8),
    (0x31CC, 0x31E6), (0x34CC, 0x355E), (0x3718, 0x3734), (0x38D4, 0x3924),
    (0x3984, 0x3994), (0x3B5C, 0x3BA2), (0x3E2C, 0x3F26), (0x3F7A, 0x4008),
    (0x402C, 0x404C), (0x4080, 0x4124), (0x41A4, 0x41C8), (0x41D0, 0x41D6),
    (0x426C, 0x428E), (0x42D0, 0x42DE), (0x4634, 0x4656), (0x4888, 0x4936),
    (0x4A8C, 0x4A98), (0x5068, 0x5074), (0x5086, 0x5088), (0x50C4, 0x50CC),
    (0x511C, 0x5120), (0x52C4, 0x52EE), (0x5304, 0x5480), (0x5498, 0x54AE),
    (0x54BC, 0x54D6), (0x54E8, 0x5516), (0x551C, 0x55D2), (0x55F4, 0x57EC),
    (0x5828, 0x584A), (0x5850, 0x5866), (0x5878, 0x58CA), (0x5934, 0x59A4),
    (0x5A68, 0x5A92), (0x6FB4, 0x702E), (0x7444, 0x7498), (0x7714, 0x7720),
    (0x773A, 0x775C), (0x7780, 0x77A6), (0x77BC, 0x77F8), (0x78B0, 0x78D4),
    (0x79B0, 0x79C4), (0x79E8, 0x7A0A), (0x7A10, 0x7A20), (0x7A4C, 0x7A5A),
    (0x7AE4, 0x7AF4), (0x7C1C, 0x7C8C), (0x8720, 0x8740), (0x8898, 0x88B2),
    (0x88FA, 0x88FE), (0x8906, 0x890C), (0x8914, 0x893A), (0x8FEC, 0x9012),
    (0x927C, 0x9324), (0x9344, 0x94D2), (0x953C, 0x95A2), (0x95AC, 0x963C),
    (0x9700, 0x9716), (0x9720, 0x972A), (0x97C4, 0x9802), (0x9904, 0x9928),
    (0x9934, 0x9958), (0x9960, 0x9966), (0x996C, 0x9972), (0x9978, 0x997E),
    (0x9984, 0x99CE), (0x99D4, 0x99E2), (0x99E8, 0x99F6), (0x99FC, 0x9A0A),
    (0x9A10, 0x9A3A), (0x9A40, 0x9A46), (0x9A4C, 0x9A52), (0x9B80, 0x9BE8),
    (0x9C2C, 0x9C86), (0x9C94, 0x9CA4), (0x9F74, 0x9F7E), (0x9F84, 0xA0EE),
    (0xA208, 0xA316), (0xA4D4, 0xA50C), (0xA53A, 0xA58C), (0xA59C, 0xA5BA),
    (0xA5C0, 0xA5E2), (0xA5E8, 0xA5F2), (0xA5F8, 0xA602), (0xA608, 0xA610),
    (0xAA10, 0xAA12), (0xB14E, 0xB156),
)

V122_THUNK_TARGETS = (
    0x00000979, 0x00000847, 0x0000B77D, 0x0000BEF9, 0x0000BE01, 0x000008D1,
    0x00005AED, 0x00003CC1, 0x0000BCFD, 0x00002899, 0x00005F09, 0x00005E0D,
    0x00005D4D, 0x30100655, 0x000058B9, 0x30100029, 0x0000BCD5, 0x000060B9,
    0x000042D9, 0x00004029, 0x00004175, 0x00003F35, 0x000041F9, 0x00003FB9,
    0x00004105, 0x00003EC5, 0x0000443D, 0x00003E41, 0x00004349, 0x00004269,
    0x000043B9, 0x000040AD, 0x000073F5, 0x00002371, 0x301006F5, 0x000064C1,
    0x000066D5, 0x00006A55, 0x000068D1, 0x00006669, 0x00006791, 0x00006595,
    0x000067FD, 0x00006601, 0x00006A0D, 0x000069A1, 0x00006729, 0x0000652D,
    0x00006939, 0x00006865, 0x00000935, 0x0000CB49, 0x0000B7A9, 0x000003FF,
    0x000009C9, 0x000003B1, 0x000026F1, 0x00000353, 0x00005A29, 0x00005965,
    0x000076ED, 0x000004ED, 0x0000608D, 0x0000B3E9, 0x0000372D, 0x000044AD,
    0x00004885, 0x0000B79D, 0x00006265, 0x00000535, 0x000061E9, 0x000096F5,
    0x0000986D, 0x0000BC35, 0x00000809, 0x00000769, 0x0000BEED, 0x0000BEE1,
    0x0000CBE1,
)

PROFILES: dict[str, Region0Profile] = {
    "V1.22": Region0Profile(
        version="V1.22",
        core0_size=0xF35C,
        core0_sha256=(
            "d779faf9f591e71602e5f17e966ac366602699a83fb5e612534d694d3dafd153"
        ),
        core1_size=438632,
        core1_sha256=(
            "b2869bc657ba896474e760f513e4514fac678a951364efc29cbf9b6bb5e2ba72"
        ),
        loader_size=61440,
        loader_sha256=(
            "9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56"
        ),
        stack_top=0x1803F5C0,
        reset_offset=0x2F4,
        hardware_init_offset=0x6190,
        scatter_entry_offset=0x140,
        runtime_entry_offset=0x2D4,
        runtime_library_init_offset=0x2A8,
        stack_setup_offset=0x17A2,
        stack_descriptor_offset=0x32C,
        handoff_veneer_offset=0x2196,
        region1_entry=0x1004A525,
        region1_main_length=0x2D4,
        hardware_init_calls=(0x7008, 0x6EBC, 0x7024, 0x6F70, 0x6F80, 0x7018,
                             0x6E68),
        region1_copy_offset=0x6F80,
        memcpy_offset=0x8D0,
        primask_release_offset=0x6EA6,
        scatter_table_offset=0xD75C,
        scatter_table_end=0xD79C,
        scatter_entries=(
            (0xD8C8, 0x18014000, 0x3804, 0x17C),
            (0xE210, 0x30100000, 0x114C, 0x1E0),
            (0xE210, 0x18017804, 0x27DBC, 0x1FC),
            (0xF35C, 0x3010114C, 0x5DEA64, 0x1FC),
        ),
        decompress_handler=0x17C,
        copy_handler=0x1E0,
        zero_handler=0x1FC,
        heap_base=0x180249B0,
        heap_limit=0x1802A9B0,
        stack_limit=0x1803D5C0,
        region1_vectors=(
            (15, 0x10012F89), (20, 0x10008ADD), (21, 0x10008AC5),
            (31, 0x1000BD49), (42, 0x10000DB1),
        ),
        zero_vectors=frozenset((7, 8, 9, 10, 13, 73, 74, 75, 76, 77, 78)),
        usb_irq_vector=(22, 0x000062C9),
        reset_closure_ranges=V122_RESET_CLOSURE,
        reset_closure_sha256=(
            "cf3628a2305c44005c808b5c297debf840351db956dd8311572b26d9161e0762"
        ),
        reset_closure_sram_constants=(
            0x1801656C, 0x18023808, 0x18024950, 0x18024958, 0x18024970,
            0x180249B0, 0x1802A9B0, 0x1803D5C0, 0x1803F5C0,
        ),
        reset_closure_rom_calls=(0x08001491, 0x0800603D),
        loader_closure_ranges=V122_LOADER_CLOSURE,
        loader_closure_sha256=(
            "e48c4456dcb469f09d60e9556e19eae65fe523b525862948032e033874b9f7df"
        ),
        # Two MOV.W modified immediates equal to the single bit 0x10000000:
        # a shift operand in an arithmetic helper and a register value passed
        # to a peripheral-setup helper.  Neither is loaded as a pointer.
        loader_closure_aperture_bit_immediates=(0x1246, 0x7C6A),
        thunk_count=79,
        thunk_targets=V122_THUNK_TARGETS,
        veneer_count=36,
        region1_main_sha256=(
            "68ee43c069fe04a0f2079a47f493d1456d1952ab358ac97dc81ed4a5cdbfe53b"
        ),
    ),
}


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


def _expect(data: bytes, offset: int, operation: str, *operands: Any) -> tuple[Any, ...]:
    decoded = decode(data, offset)
    _require(decoded[0] == operation,
             f"expected {operation} at {hex32(offset)}, decoded {decoded[0]}")
    for index, operand in enumerate(operands):
        if operand is None:
            continue
        actual = decoded[2 + index]
        _require(actual == operand,
                 f"{operation} at {hex32(offset)} operand {index} is "
                 f"{actual!r}, expected {operand!r}")
    return decoded


def _bl_target(data: bytes, offset: int) -> int:
    return _reentry.decode_thumb_bl(data, offset, REGION0_RUNTIME_BASE)


def _literal(data: bytes, offset: int, register: int) -> tuple[int, int]:
    decoded = _expect(data, offset, "ldr_lit", register)
    literal_offset = decoded[3]
    return literal_offset, _u32(data, literal_offset)


def _movw_movt(data: bytes, offset: int, register: int) -> int:
    """Decode a MOVW/MOVT pair building one 32-bit constant."""

    low = _expect(data, offset, "mov_imm", register, None, False)
    _require(low[1] == 4, f"MOVW at {hex32(offset)} is not the wide form")
    high = _expect(data, offset + 4, "movt", register)
    return ((high[3] & 0xFFFF) << 16) | (low[3] & 0xFFFF)


def _verify_identity(name: str, data: bytes, size: int, digest: str) -> dict[str, Any]:
    _require(len(data) == size and sha256(data) == digest,
             f"{name} is not the pinned stock image")
    return {"size": size, "sha256": digest}


def _verify_vectors(core0: bytes, profile: Region0Profile) -> dict[str, Any]:
    """Region 0 owns the only vector table; five entries point into region 1."""

    _require(_u32(core0, 0) == profile.stack_top,
             "vector table initial stack is not the pinned top of SRAM")
    reset = _u32(core0, 4)
    _require(reset == profile.reset_offset + 1,
             "reset vector does not select the pinned reset handler")
    region1_vectors = []
    for index in range(1, VECTOR_COUNT):
        value = _u32(core0, index * 4)
        if REGION1_RUNTIME_BASE <= value < REGION1_APERTURE_END:
            region1_vectors.append((index, value))
        elif index in profile.zero_vectors:
            _require(value == 0, f"reserved vector {index} is not zero")
        else:
            _require(value & 1 == 1 and value < len(core0),
                     f"vector {index} is not a Thumb address inside region 0")
    _require(tuple(region1_vectors) == profile.region1_vectors,
             "the set of vectors that dispatch into region 1 changed")
    usb_index, usb_handler = profile.usb_irq_vector
    _require(_u32(core0, usb_index * 4) == usb_handler,
             "USB IRQ vector is not the pinned region-0 handler")
    return {
        "initial_stack": hex32(profile.stack_top),
        "reset_handler": hex32(reset),
        "region1_vectors": [
            {"index": index, "exception": index - 16 if index >= 16 else index,
             "handler": hex32(value)}
            for index, value in region1_vectors
        ],
        "usb_irq6_handler": hex32(usb_handler),
    }


def _verify_reset(core0: bytes, profile: Region0Profile) -> dict[str, Any]:
    """Reset loads SP through VTOR, runs hardware init, enters the scatter loader."""

    base = profile.reset_offset
    _require(_movw_movt(core0, base, 0) == VTOR,
             "reset handler does not address VTOR")
    _expect(core0, base + 8, "ldr_imm", 0, 0, 0)
    _expect(core0, base + 10, "ldr_imm", REG_SP, 0, 0)
    _, init = _literal(core0, base + 14, 0)
    _expect(core0, base + 16, "blx", 0)
    _, scatter = _literal(core0, base + 18, 0)
    _expect(core0, base + 20, "bx", 0)
    _require(init == profile.hardware_init_offset + 1,
             "reset handler does not call the pinned hardware initialization")
    _require(scatter == profile.scatter_entry_offset + 1,
             "reset handler does not continue into the pinned scatter loader")
    return {
        "vtor_read": hex32(VTOR),
        "hardware_init": hex32(profile.hardware_init_offset),
        "scatter_loader": hex32(profile.scatter_entry_offset),
    }


def _verify_hardware_init(core0: bytes, profile: Region0Profile) -> dict[str, Any]:
    base = profile.hardware_init_offset
    _expect(core0, base, "push")
    calls: list[int] = []
    offset = base + 0x2A
    for _ in profile.hardware_init_calls:
        calls.append(_bl_target(core0, offset))
        offset += 4
    _expect(core0, offset, "pop")
    _require(tuple(calls) == profile.hardware_init_calls,
             "hardware initialization call sequence changed")
    return {"calls": [hex32(target) for target in calls]}


def _verify_region1_copy(core0: bytes, profile: Region0Profile) -> dict[str, Any]:
    """Region 1 is copied whole into OPI DRAM and mapped by the cache aperture."""

    base = profile.region1_copy_offset
    _expect(core0, base, "push")
    _, sfc = _literal(core0, base + 2, 1)
    _require(sfc == SFC_BASE, "region-1 copy does not start at the SFC control word")
    length = _expect(core0, base + 0x10, "mov_imm", 2, REGION1_COPY_BYTES, False)
    _require(length[1] == 4, "copy length is not a wide immediate")
    _, source = _literal(core0, base + 0x14, 1)
    _, destination = _literal(core0, base + 0x16, 0)
    _require(_bl_target(core0, base + 0x18) == profile.memcpy_offset,
             "region-1 copy does not call the pinned memcpy")
    _require(source == REGION1_FLASH_SOURCE and destination == REGION1_OPI_COPY,
             "region-1 copy source/destination are not the pinned addresses")
    _, clock = _literal(core0, base + 0x3C, 0)
    _require(clock == SYS1_CLOCK_RESET,
             "cache clock/reset word is not the pinned system-control register")
    _expect(core0, base + 0x40, "bic_imm", 0, 0, 0x800, False)
    _expect(core0, base + 0x44, "add_imm", 0, 0, 0x800, False)
    _, mapped = _literal(core0, base + 0x50, 0)
    _, cache = _literal(core0, base + 0x52, 1)
    _require(mapped == REGION1_OPI_COPY and cache == ICACHE_BASE,
             "cache aperture is not programmed with the DRAM copy address")
    _expect(core0, base + 0x54, "str_imm", 0, 1, 4)
    _expect(core0, base + 0x56, "str_imm", 0, 1, 4)
    _expect(core0, base + 0x58, "mov_imm", 0, 2, True)
    _expect(core0, base + 0x5A, "str_imm", 0, 1, 0)
    # lsls r0, r0, #27 turns the enable value 2 into 0x10000000 and the copy
    # is accepted only if the first aperture word equals the first flash word.
    _require(_u16(core0, base + 0x5E) == 0x06C0,
             "aperture check does not derive 0x10000000 from the enable value")
    _expect(core0, base + 0x60, "ldr_imm", 0, 0, 0)
    _, flash = _literal(core0, base + 0x62, 1)
    _require(flash == REGION1_FLASH_SOURCE,
             "aperture check does not compare against the flash source")
    _expect(core0, base + 0x64, "ldr_imm", 1, 1, 0)
    _expect(core0, base + 0x66, "cmp_reg", 0, 1)
    return {
        "sfc_control": hex32(SFC_BASE),
        "copy_source": hex32(REGION1_FLASH_SOURCE),
        "copy_destination": hex32(REGION1_OPI_COPY),
        "copy_bytes": hex32(REGION1_COPY_BYTES),
        "cache_clock_reset_bit": 11,
        "cache_controller": hex32(ICACHE_BASE),
        "cache_offset_word": hex32(REGION1_OPI_COPY),
        "cache_control_value": 2,
        "first_word_check": True,
    }


def _verify_primask_release(core0: bytes, profile: Region0Profile) -> dict[str, Any]:
    """Priority setup ends with MSR PRIMASK, r0 where r0 is provably zero."""

    base = profile.primask_release_offset
    # adds r0, r0, #1 ; cmp r0, #0 ; bne loop ; nop ; msr primask, r0
    _expect(core0, base - 8, "add_imm", 0, 0, 1, True)
    _expect(core0, base - 6, "cmp_imm", 0, 0)
    branch = _expect(core0, base - 4, "bcond", 0x1)
    _require(branch[3] < base, "priority loop does not branch backwards")
    _expect(core0, base - 2, "hint", 0)
    _expect(core0, base, "msr", 0, 0x10)
    _expect(core0, base + 4, "hint", 0)
    _expect(core0, base + 6, "pop")
    return {"primask_written": 0, "interrupts_enabled_at_handoff": True}


def _verify_scatter(core0: bytes, profile: Region0Profile) -> dict[str, Any]:
    base = profile.scatter_entry_offset
    _require(_bl_target(core0, base) == base + 8,
             "scatter entry does not call its region walker")
    _require(_bl_target(core0, base + 4) == profile.runtime_entry_offset,
             "scatter entry does not continue into the runtime entry")
    # adr r0, table-pointer pair; ldm r0, {sl, fp}; add sl, r0; add fp, r0
    pointer_pair = base + 0x34
    table_start = _u32(core0, pointer_pair) + pointer_pair
    table_end = _u32(core0, pointer_pair + 4) + pointer_pair
    _require(table_start == profile.scatter_table_offset and
             table_end == profile.scatter_table_end,
             "scatter table bounds are not the pinned values")
    entries = []
    for index in range(len(profile.scatter_entries)):
        offset = table_start + index * 16
        entries.append(struct.unpack_from("<IIII", core0, offset))
    _require(tuple(entries) == profile.scatter_entries,
             "scatter table entries changed")
    handlers = {entry[3] for entry in entries}
    _require(handlers == {profile.decompress_handler, profile.copy_handler,
                          profile.zero_handler},
             "scatter table uses an unexpected handler")
    # Handler identity by their opening instructions: the decompressor starts
    # with LDRB.W r3, [r0], #1 / ADD r2, r1; the copy handler with SUBS r2,
    # #16 / ITT HS / LDMHS r0!, {r3-r6} / STMHS r1!, {r3-r6}; the zero-fill
    # handler seeds r3-r6 with zero and then uses the same SUBS/STM shape.
    _require(core0[profile.decompress_handler:profile.decompress_handler + 6] ==
             bytes.fromhex("10f8013b0a44"),
             "decompression handler does not open with LDRB.W/ADD")
    _require(core0[profile.copy_handler:profile.copy_handler + 8] ==
             bytes.fromhex("103a24bf78c878c1"),
             "copy handler does not open with SUBS/ITT/LDM/STM")
    _require(core0[profile.zero_handler:profile.zero_handler + 10] ==
             bytes.fromhex("0023002400250026103a"),
             "zero-fill handler does not seed four zero registers")
    return {
        "table": {"start": hex32(table_start), "end": hex32(table_end)},
        "entries": [
            {"source": hex32(source), "destination": hex32(destination),
             "length": hex32(length),
             "handler": ("decompress" if handler == profile.decompress_handler
                         else "copy" if handler == profile.copy_handler
                         else "zero")}
            for source, destination, length, handler in entries
        ],
    }


def _verify_runtime_entry(core0: bytes, profile: Region0Profile) -> dict[str, Any]:
    """The C runtime entry calls region 1 exactly once and never expects a return."""

    base = profile.runtime_entry_offset
    _require(_bl_target(core0, base) == profile.stack_setup_offset,
             "runtime entry does not set up the stack first")
    _expect(core0, base + 4, "mov_reg", 1, 2)
    _require(_bl_target(core0, base + 6) == profile.runtime_library_init_offset,
             "runtime entry does not initialize the C library")
    _require(_bl_target(core0, base + 10) == profile.handoff_veneer_offset,
             "runtime entry does not call the region-1 veneer")
    veneer = profile.handoff_veneer_offset
    target = _movw_movt(core0, veneer, REG_IP)
    _expect(core0, veneer + 8, "bx", REG_IP)
    _require(target == profile.region1_entry,
             "handoff veneer does not target the pinned region-1 entry")
    sites = []
    for offset in range(0, len(core0) - 3, 2):
        first = _u16(core0, offset)
        second = _u16(core0, offset + 2)
        if first & 0xF800 == 0xF000 and second & 0xD000 == 0xD000:
            if _bl_target(core0, offset) == veneer:
                sites.append(offset)
    _require(sites == [base + 10], "the handoff veneer has more than one caller")
    # Stack descriptor: r0 heap base, r1 stack top, r2 heap limit, r3 stack limit.
    descriptor = profile.stack_descriptor_offset
    values = []
    for register in range(4):
        _, value = _literal(core0, descriptor + register * 2, register)
        values.append(value)
    _expect(core0, descriptor + 8, "bx", 14)
    _require(values == [profile.heap_base, profile.stack_top,
                        profile.heap_limit, profile.stack_limit],
             "stack/heap descriptor changed")
    setup = profile.stack_setup_offset
    _require(_bl_target(core0, setup + 0x18) == descriptor,
             "stack setup does not read the pinned descriptor")
    _expect(core0, setup + 0x46, "mov_reg", REG_SP, 1)
    _expect(core0, setup + 0x48, "bx", 14)
    return {
        "handoff_call_site": hex32(base + 10),
        "veneer": hex32(veneer),
        "region1_entry": hex32(profile.region1_entry),
        "stack_top_at_entry": hex32(profile.stack_top),
        "stack_window": [hex32(profile.stack_limit), hex32(profile.stack_top)],
        "heap_window": [hex32(profile.heap_base), hex32(profile.heap_limit)],
        "return_from_region1": "falls into the reset handler again",
    }


def _closure_blob(data: bytes, ranges: tuple[tuple[int, int], ...]) -> bytes:
    previous_end = 0
    for start, end in ranges:
        _require(0 <= previous_end <= start < end <= len(data),
                 "closure ranges are not ordered and inside the image")
        previous_end = end
    return b"".join(data[start:end] for start, end in ranges)


def _constants_in_ranges(
        data: bytes, ranges: tuple[tuple[int, int], ...]
) -> tuple[set[int], dict[int, int]]:
    """Constants materialized by the instruction streams inside the ranges.

    Every range is a reached instruction stream, so it is decoded linearly.
    Returns the pointer-shaped constants (words addressed by LDR literals and
    values built by MOVW/MOVT pairs) and, separately, the MOV.W modified
    immediates keyed by instruction offset; the latter are bit patterns and
    small values rather than addresses, but they are still reported.
    """

    pointers: set[int] = set()
    immediates: dict[int, int] = {}
    for start, end in ranges:
        offset = start
        pending: dict[int, int] = {}
        while offset < end:
            decoded = decode(data, offset)
            size = decoded[1]
            if decoded[0] == "ldr_lit" and decoded[4] is not None:
                pointers.add(decoded[4])
            if decoded[0] == "mov_imm" and size == 4:
                if _u16(data, offset) & 0xFBF0 == 0xF240:
                    pending[decoded[2]] = decoded[3] & 0xFFFF  # MOVW
                else:
                    immediates[offset] = decoded[3]  # MOV.W modified immediate
            elif decoded[0] == "movt" and decoded[2] in pending:
                pointers.add((decoded[3] << 16) | pending.pop(decoded[2]))
            offset += size
        _require(offset == end, f"range ending at {hex32(end)} splits an instruction")
    return pointers, immediates


def _forbidden(constant: int) -> str | None:
    if REGION1_RUNTIME_BASE <= constant < REGION1_APERTURE_END:
        return "region-1 address"
    if NVIC_ISER_START <= constant < NVIC_ISER_END:
        return "NVIC set-enable register"
    if constant == SYSTICK_CSR:
        return "SysTick control register"
    if USB_BASE <= constant < USB_END or constant == USB_PHY_ENABLE:
        return "USB controller register"
    return None


def _verify_reset_closure(core0: bytes, profile: Region0Profile) -> dict[str, Any]:
    """Nothing reachable before the handoff reads region 1 or enables an IRQ."""

    blob = _closure_blob(core0, profile.reset_closure_ranges)
    _require(sha256(blob) == profile.reset_closure_sha256,
             "reset-path closure bytes are not the reviewed derivation")
    pointers, immediates = _constants_in_ranges(core0, profile.reset_closure_ranges)
    constants = pointers | set(immediates.values())
    offenders = sorted(value for value in constants if _forbidden(value))
    _require(not offenders,
             "reset-path closure contains a forbidden constant: " +
             ", ".join(hex32(value) for value in offenders))
    sram = tuple(sorted(value for value in constants
                        if 0x18000000 <= value < 0x18040000))
    _require(sram == profile.reset_closure_sram_constants,
             "reset-path closure SRAM constants changed")
    rom = tuple(sorted(value for value in constants
                       if 0x08000000 <= value < 0x08100000))
    _require(rom == profile.reset_closure_rom_calls,
             "reset-path closure ROM entry constants changed")
    _require(REGION1_FLASH_SOURCE in constants and REGION1_OPI_COPY in constants,
             "reset-path closure lost the region-1 copy constants")
    return {
        "ranges": len(profile.reset_closure_ranges),
        "bytes": len(blob),
        "sha256": profile.reset_closure_sha256,
        "region1_constants": 0,
        "nvic_enable_constants": 0,
        "systick_constants": 0,
        "usb_constants": 0,
        "sram_constants": [hex32(value) for value in sram],
        "rom_calls": [hex32(value) for value in rom],
    }


def _verify_loader_closure(loader: bytes, profile: Region0Profile) -> dict[str, Any]:
    """The loader's application launch path carries no region-1 address."""

    blob = _closure_blob(loader, profile.loader_closure_ranges)
    _require(sha256(blob) == profile.loader_closure_sha256,
             "loader launch closure bytes are not the reviewed derivation")
    pointers, immediates = _constants_in_ranges(loader, profile.loader_closure_ranges)
    region1 = sorted(value for value in pointers
                     if REGION1_RUNTIME_BASE <= value < REGION1_APERTURE_END)
    _require(not region1,
             "loader launch closure loads a region-1 address")
    bit_sites = tuple(sorted(
        offset for offset, value in immediates.items()
        if REGION1_RUNTIME_BASE <= value < REGION1_APERTURE_END))
    _require(all(immediates[offset] == REGION1_RUNTIME_BASE for offset in bit_sites),
             "loader launch closure materializes an address inside region 1")
    _require(bit_sites == profile.loader_closure_aperture_bit_immediates,
             "loader launch closure single-bit 0x10000000 immediates changed")
    return {
        "ranges": len(profile.loader_closure_ranges),
        "bytes": len(blob),
        "sha256": profile.loader_closure_sha256,
        "region1_constants": 0,
        "aperture_bit_immediate_sites": [hex32(offset) for offset in bit_sites],
    }


def _verify_veneers(core0: bytes, profile: Region0Profile) -> dict[str, Any]:
    veneers = []
    offset = 0
    while offset + THUNK_BYTES <= len(core0):
        first = _u16(core0, offset)
        third = _u16(core0, offset + 4)
        fifth = _u16(core0, offset + 8)
        if (first & 0xFBF0 == 0xF240 and third & 0xFBF0 == 0xF2C0 and
                fifth == 0x4760 and
                (_u16(core0, offset + 2) >> 8) & 0xF == REG_IP and
                (_u16(core0, offset + 6) >> 8) & 0xF == REG_IP):
            veneers.append((offset, _movw_movt(core0, offset, REG_IP)))
            offset += THUNK_BYTES
            continue
        offset += 2
    _require(len(veneers) == profile.veneer_count,
             "the number of region-0 veneers changed")
    _require(any(offset == profile.handoff_veneer_offset and
                 target == profile.region1_entry for offset, target in veneers),
             "handoff veneer is not among the decoded veneers")
    return {
        "count": len(veneers),
        "targets": [{"veneer": hex32(offset), "target": hex32(target)}
                    for offset, target in veneers],
    }


def _verify_thunks(core1: bytes, profile: Region0Profile) -> dict[str, Any]:
    """Region 1 imports region-0 services through a MOVW/MOVT/BX table."""

    targets = []
    offset = 0
    while offset + THUNK_BYTES <= len(core1):
        first = _u16(core1, offset)
        third = _u16(core1, offset + 4)
        fifth = _u16(core1, offset + 8)
        if not (first & 0xFBF0 == 0xF240 and third & 0xFBF0 == 0xF2C0 and
                fifth == 0x4760):
            break
        targets.append(_movw_movt(core1, offset, REG_IP))
        offset += THUNK_BYTES
    _require(len(targets) == profile.thunk_count and
             tuple(targets) == profile.thunk_targets,
             "region-1 import thunk table changed")
    return {
        "count": len(targets),
        "table_end": hex32(REGION1_RUNTIME_BASE + offset),
        "targets": [hex32(target) for target in targets],
    }


def _verify_region1_entry(core1: bytes, profile: Region0Profile) -> dict[str, Any]:
    entry = profile.region1_entry - REGION1_RUNTIME_BASE - 1
    main = core1[entry:entry + profile.region1_main_length]
    _require(len(main) == profile.region1_main_length,
             "region-1 main is truncated")
    _expect(core1, entry, "mov_imm", 1, 3, True)
    _require(sha256(main) == profile.region1_main_sha256,
             "region-1 main bytes are not the pinned stock routine")
    return {
        "entry": hex32(profile.region1_entry),
        "file_offset": hex32(entry),
        "main_length": hex32(profile.region1_main_length),
        "main_sha256": profile.region1_main_sha256,
    }


def verify_images(profile: Region0Profile, core0: bytes, core1: bytes,
                  loader: bytes, *, labels: dict[str, str] | None = None
                  ) -> dict[str, Any]:
    labels = labels or {}
    checks: list[dict[str, Any]] = []
    facts: dict[str, Any] = {}
    steps: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
        ("core0_exact_identity", lambda: _verify_identity(
            "core0", core0, profile.core0_size, profile.core0_sha256)),
        ("core1_exact_identity", lambda: _verify_identity(
            "core1", core1, profile.core1_size, profile.core1_sha256)),
        ("loader_exact_identity", lambda: _verify_identity(
            "loader", loader, profile.loader_size, profile.loader_sha256)),
        ("vectors", lambda: _verify_vectors(core0, profile)),
        ("reset", lambda: _verify_reset(core0, profile)),
        ("hardware_init", lambda: _verify_hardware_init(core0, profile)),
        ("region1_copy", lambda: _verify_region1_copy(core0, profile)),
        ("primask_release", lambda: _verify_primask_release(core0, profile)),
        ("scatter", lambda: _verify_scatter(core0, profile)),
        ("runtime_entry", lambda: _verify_runtime_entry(core0, profile)),
        ("reset_closure", lambda: _verify_reset_closure(core0, profile)),
        ("loader_closure", lambda: _verify_loader_closure(loader, profile)),
        ("veneers", lambda: _verify_veneers(core0, profile)),
        ("thunks", lambda: _verify_thunks(core1, profile)),
        ("region1_entry", lambda: _verify_region1_entry(core1, profile)),
    )
    for name, operation in steps:
        try:
            facts[name] = operation()
        except (EvidenceError, struct.error) as error:
            checks.append({"name": name, "passed": False, "error": str(error)})
        else:
            checks.append({"name": name, "passed": True})
    passed = all(check["passed"] for check in checks)
    return {
        "format": "KB7 stock Core0/region-1 boot contract evidence v1",
        "profile": profile.version,
        "passed": passed,
        "inputs": {
            "core0": {"name": labels.get("core0", "<memory>"),
                      "size": len(core0), "sha256": sha256(core0)},
            "core1": {"name": labels.get("core1", "<memory>"),
                      "size": len(core1), "sha256": sha256(core1)},
            "loader": {"name": labels.get("loader", "<memory>"),
                       "size": len(loader), "sha256": sha256(loader)},
        },
        "checks": checks,
        "facts": facts,
        "proof_boundary": (
            "Static identity and instruction semantics of the stock reset path "
            "only.  The reachable-code ranges were derived offline and are "
            "pinned by hash; indirect branches inside them were resolved by "
            "hand and are listed in the contract document.  This proves what "
            "stock region 0 does before it calls region 1; it does not prove "
            "that custom region-1 code runs on hardware."
        ),
        "device_accessed": False,
        "files_written": False,
    }


def verify_paths(profile: Region0Profile, core0_path: Path, core1_path: Path,
                 loader_path: Path) -> dict[str, Any]:
    images = {}
    labels = {}
    for name, path in (("core0", core0_path), ("core1", core1_path),
                       ("loader", loader_path)):
        expanded = path.expanduser()
        images[name] = expanded.read_bytes()
        labels[name] = expanded.name
    return verify_images(profile, images["core0"], images["core1"],
                         images["loader"], labels=labels)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only verification of the stock Core0/region-1 contract")
    parser.add_argument("--version", required=True, choices=tuple(PROFILES))
    parser.add_argument("--core0", required=True, type=Path)
    parser.add_argument("--core1", required=True, type=Path)
    parser.add_argument("--loader", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = verify_paths(PROFILES[args.version], args.core0, args.core1,
                              args.loader)
    except OSError as error:
        report = {
            "format": "KB7 stock Core0/region-1 boot contract evidence v1",
            "profile": args.version,
            "passed": False,
            "error": {
                "type": type(error).__name__,
                "message": error.strerror or "input read failed",
                "input_name": Path(error.filename).name if error.filename else None,
            },
            "device_accessed": False,
            "files_written": False,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
