#!/usr/bin/env python3
"""Derive the reachable-code closure of a Thumb-2 boot path (offline aid).

This is the derivation tool behind the hash-pinned closure ranges in
``verify_region1_contract.py``.  It performs recursive descent over the raw
image with capstone, decoding on demand at every branch target rather than
trusting a linear sweep, and follows:

* every ``BL``, unconditional ``B``/``B.W``, conditional branch, ``CBZ``/``CBNZ``;
* ``BX``/``BLX`` through a register whose value came from a literal pool or a
  ``MOVW``/``MOVT`` pair earlier in the same linear block;
* ``TBB``/``TBH`` cases enumerated from the preceding ``CMP``/``SUBS`` guard
  (``BHS`` after ``CMP #n`` gives ``n`` cases, ``BHI`` gives ``n + 1``);
* conditional returns (``POPcc {..., pc}``) as fall-through; and
* extra seeds supplied on the command line (for example scatter-table
  handlers whose dispatch is a data-driven ``BX``).

It stops at the addresses given with ``--stop`` (the region-1 veneer) and
reports every indirect branch it could not resolve so that they can be
resolved by reading.  It never opens a device and writes no file; the output
is the range table, its SHA-256 and the constants materialized inside it, in
the form the verifier profile pins.  capstone is an optional dependency of
this tool only; the verifier itself does not need it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import struct
import sys

try:
    import capstone  # type: ignore
except ImportError:  # pragma: no cover - derivation aid only
    capstone = None

COND = ("eq", "ne", "cs", "hs", "cc", "lo", "mi", "pl", "vs", "vc", "hi",
        "ls", "ge", "lt", "gt", "le", "al")
BASES = ("b", "bl", "blx", "bx", "pop", "ldr", "cbz", "cbnz", "cmp", "subs")


def split_mnemonic(mnemonic: str) -> tuple[str, bool]:
    """Return (base mnemonic, conditional) stripping ``.w`` and IT suffixes."""

    core = mnemonic[:-2] if mnemonic.endswith(".w") else mnemonic
    for base in sorted(BASES, key=len, reverse=True):
        if core == base:
            return base, False
        if core.startswith(base) and core[len(base):] in COND:
            return base, True
    return core, False


class Closure:
    def __init__(self, data: bytes, base: int, stops: set[int]) -> None:
        if capstone is None:
            raise SystemExit("capstone is required for the closure derivation")
        self.data = data
        self.base = base
        self.stops = stops
        self.md = capstone.Cs(capstone.CS_ARCH_ARM,
                              capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
        self.cache: dict[int, tuple[int, str, str]] = {}
        self.seen: dict[int, int] = {}
        self.unresolved: list[tuple[int, str, str, str | None]] = []
        self.edges: dict[int, set[int]] = {}
        # Instructions preceding a conditional branch, carried to its target so
        # that a table switch whose guard sits before the branch can be sized.
        self.context: dict[int, list[tuple[int, str, str]]] = {}

    def decode(self, address: int) -> tuple[int, str, str] | None:
        if address in self.cache:
            return self.cache[address]
        offset = address - self.base
        if not 0 <= offset < len(self.data) - 1:
            return None
        chunk = self.data[offset:offset + 4]
        for instruction in self.md.disasm(chunk, address, count=1):
            item = (instruction.size, instruction.mnemonic, instruction.op_str)
            self.cache[address] = item
            return item
        # Undecodable halfword: keep the Thumb-2 size rule so ranges stay aligned.
        first = struct.unpack_from("<H", self.data, offset)[0]
        size = 4 if (first >> 11) in (0b11101, 0b11110, 0b11111) else 2
        item = (size, ".undecoded", "")
        self.cache[address] = item
        return item

    def word(self, address: int) -> int | None:
        offset = address - self.base
        if 0 <= offset <= len(self.data) - 4:
            return struct.unpack_from("<I", self.data, offset)[0]
        return None

    def add_edge(self, source: int, target: int, work: list[int],
                 recent: list[tuple[int, str, str]] | None = None) -> None:
        self.edges.setdefault(target, set()).add(source)
        if recent is not None and target not in self.context:
            self.context[target] = list(recent)
        work.append(target)

    def run(self, seeds: list[int]) -> None:
        work = list(seeds)
        while work:
            start = work.pop()
            if start in self.seen or start in self.stops:
                continue
            self.walk(start, work)

    def walk(self, start: int, work: list[int]) -> None:
        pc = start
        registers: dict[str, int] = {}
        recent: list[tuple[int, str, str]] = list(self.context.get(start, []))
        while pc not in self.seen and pc not in self.stops:
            decoded = self.decode(pc)
            if decoded is None:
                return
            size, mnemonic, operands = decoded
            self.seen[pc] = size
            base, conditional = split_mnemonic(mnemonic)
            recent = (recent + [(pc, mnemonic, operands)])[-8:]
            literal = re.search(r"\[pc, #(0x[0-9a-f]+)\]", operands)
            if literal and mnemonic.startswith("ldr") and \
                    not mnemonic.startswith(("ldrb", "ldrh", "ldrsb", "ldrsh")):
                value = self.word((pc & ~3) + 4 + int(literal.group(1), 16))
                if value is not None:
                    registers[operands.split(",")[0].strip()] = value
            moved = re.match(r"mov[wt] (\w+), #(0x[0-9a-f]+|\d+)",
                             f"{mnemonic} {operands}")
            if moved:
                register, value = moved.group(1), int(moved.group(2), 0)
                registers[register] = value if mnemonic == "movw" else (
                    (registers.get(register, 0) & 0xFFFF) | (value << 16))
            if base == "bl" and operands.startswith("#"):
                self.add_edge(pc, int(operands[1:], 16), work)
            elif base in ("blx", "bx") and not operands.startswith("#"):
                register = operands.strip()
                if register != "lr":
                    value = registers.get(register)
                    inside = value is not None and value & 1 and \
                        0 <= (value & ~1) - self.base < len(self.data)
                    if inside:
                        self.add_edge(pc, (value or 0) & ~1, work)
                    else:
                        self.unresolved.append(
                            (pc, mnemonic, operands,
                             f"0x{value:08x}" if value is not None else None))
                if base == "bx" and not conditional:
                    return
            elif base == "b" and operands.startswith("#"):
                target = int(operands[1:], 16)
                if target != pc:
                    self.add_edge(pc, target, work,
                                  recent if conditional else None)
                if not conditional:
                    return
            elif base in ("cbz", "cbnz"):
                self.add_edge(pc, int(operands.split("#")[1], 16), work)
            elif base == "pop" and "pc" in operands:
                if not conditional:
                    return
            elif base == "ldr" and operands.startswith("pc"):
                if not conditional:
                    return
            elif mnemonic in ("tbb", "tbh"):
                self.table(pc, mnemonic, operands, recent, work)
                return
            pc += size

    def table(self, pc: int, mnemonic: str, operands: str,
              recent: list[tuple[int, str, str]], work: list[int]) -> None:
        index = re.search(r"\[pc, (\w+)", operands).group(1)
        cases = None
        guard_hi = any(m.startswith("bhi") for _, m, _ in recent)
        for _address, m, o in reversed(recent[:-1]):
            match = re.match(r"(?:cmp|subs)(?:\.w)? (\w+), (?:\w+, )?#(\S+)", f"{m} {o}")
            if match and match.group(1) == index:
                bound = int(match.group(2), 0)
                cases = bound + 1 if guard_hi else bound
                break
        if cases is None:
            self.unresolved.append((pc, mnemonic, operands, "no guard"))
            return
        table = pc + 4
        for case in range(cases):
            if mnemonic == "tbb":
                displacement = self.data[table + case - self.base]
            else:
                displacement = struct.unpack_from(
                    "<H", self.data, table + 2 * case - self.base)[0]
            self.add_edge(pc, table + 2 * displacement, work)

    def ranges(self) -> list[tuple[int, int]]:
        result: list[list[int]] = []
        for address in sorted(self.seen):
            if result and result[-1][1] == address:
                result[-1][1] = address + self.seen[address]
            else:
                result.append([address, address + self.seen[address]])
        return [(start, end) for start, end in result]

    def blob(self) -> bytes:
        return b"".join(self.data[start - self.base:end - self.base]
                        for start, end in self.ranges())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="raw image slice (region 0 or loader)")
    parser.add_argument("--base", default="0x0", help="runtime address of byte 0")
    parser.add_argument("--seed", action="append", required=True,
                        help="entry address (hex); repeatable")
    parser.add_argument("--stop", action="append", default=[],
                        help="address not to enter (hex); repeatable")
    args = parser.parse_args(argv)
    with open(args.image, "rb") as stream:
        data = stream.read()
    closure = Closure(data, int(args.base, 16),
                      {int(value, 16) for value in args.stop})
    closure.run([int(value, 16) for value in args.seed])
    ranges = closure.ranges()
    blob = closure.blob()
    print(f"# reached {len(closure.seen)} instructions in {len(ranges)} ranges, "
          f"{len(blob)} bytes")
    print(f"# sha256 {hashlib.sha256(blob).hexdigest()}")
    line = "    "
    for start, end in ranges:
        item = f"(0x{start:X}, 0x{end:X}), "
        if len(line) + len(item) > 78:
            print(line.rstrip())
            line = "    "
        line += item
    print(line.rstrip())
    print("# unresolved indirect branches (resolve by reading):")
    for address, mnemonic, operands, value in closure.unresolved:
        print(f"#   0x{address:x}: {mnemonic} {operands} value={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
