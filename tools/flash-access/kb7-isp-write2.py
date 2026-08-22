#!/usr/bin/env python3
"""
KB7 USB-ISP write-path validation, v2 -- DRY-RUN BY DEFAULT.

Goal: prove the F6 write path on hardware so firmware can be flashed over USB
without opening the case. This is the intended long-term flashing route (much
faster than SPI, and non-invasive for end users).

=============================================================================
ENCODINGS USED HERE, AND WHERE THEY COME FROM
=============================================================================

F6 06 PROGRAM  -- CONFIRMED ON HARDWARE (destructively, 2026-08-23)
    CDB[3:7] = BE32 raw byte address
    CDB[7:9] = BE16 count in 512-BYTE BLOCKS
  Evidence: sent address 0x470 / count 0x0100; device wrote 128 KiB starting at
  byte 0x470. Last damaged byte 0x2046f = 0x470 + 0x100*512 - 1. Both fields
  are therefore known, not inferred.

F6 15 ERASE    -- STATIC ANALYSIS ONLY, NOT YET HARDWARE-CONFIRMED
    CDB[3:5] = BE16 (aligned_address >> 9)   i.e. a 512-BYTE-BLOCK INDEX
    no count field; one CDB erases one 4 KiB sector
  Source: tools/flash-access/F6-ERASE-ENCODING.md (radare2 data-flow analysis,
  independently calibrated by re-deriving the F6 06 answer above from the
  binary alone). A second, independent objdump reading of the same routine also
  showed `shr $0x9` applied to the sector-aligned ADDRESS, agreeing.

  *** THIS IS THE ONE UNPROVEN THING THIS SCRIPT TESTS. ***

  Failure mode if wrong: F6 15's field is only 16 bits, so under a raw-byte-
  address misreading the maximum reachable address is 0xFFFF -- entirely within
  header (0x0-0x1000) and bootloader (0x1000-0x10000). There is NO partial
  failure: it either lands correctly, or it damages the boot chain. Recovery is
  a full-chip SPI rewrite from your own known-good backup image (~30 min).

ADDRESS BASE -- reviewer please sanity-check this choice.
  Reads use an absolute 0x60000000-based address and work. The one confirmed
  program used a BARE offset (0x470) and wrote to offset 0x470. Both are
  consistent with the device masking to chip size, in which case the two forms
  are equivalent. We send ABSOLUTE (0x60000000 + offset) to match both the read
  path and the vendor tool's own behaviour. Set ABS_BASE = 0 to send bare
  offsets instead.

=============================================================================
SAFETY MODEL
=============================================================================
  * Target is hard-limited to the scratch gap [0x8d000, 0x100000): 474,776
    bytes of 0xFF lying between the end of region 1 (0x8c168) and the start of
    region 2 (0x100000). It is covered by NO manifest region, so it contributes
    to no CRC, and the firmware demonstrably never writes there.
  * Default target 0x8e000 has erased sectors on both sides.
  * Stage 2 (erase) REFUSES to run unless stage 1 (program) has verifiably
    succeeded -- otherwise an erase proves nothing, because the sector is
    already 0xFF and a no-op is indistinguishable from a miss.
  * After every write the ENTIRE image range is re-read and diffed against a
    baseline. Host-side guards cannot prevent device-side misaddressing; a full
    diff DETECTS it and reports where it landed.
  * Nothing is sent without --commit.

Usage:
  sudo python3 kb7-isp-write2.py --stage program --baseline spd-4M.bin
  sudo python3 kb7-isp-write2.py --stage program --baseline spd-4M.bin --commit
  sudo python3 kb7-isp-write2.py --stage erase   --baseline spd-4M.bin --commit
"""

import argparse
import ctypes as ct
import importlib.util
import json
import os
import struct
import sys

_spec = importlib.util.spec_from_file_location(
    "kb7isp", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "kb7-isp-verify.py"))
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
Device, cdb_read, cdb_simple = _m.Device, _m.cdb_read, _m.cdb_simple
SUB_EN4B, SUB_STATUS, BLOCK = _m.SUB_EN4B, _m.SUB_STATUS, _m.BLOCK

SCRATCH_LO, SCRATCH_HI = 0x8D000, 0x100000
SECTOR = 0x1000
IMAGE_END = 0x156AF8C
SUB_PROGRAM, SUB_ERASE = 0x06, 0x15
ABS_BASE = 0x60000000          # see ADDRESS BASE note above; set 0 for bare
STATE = os.path.expanduser("~/.kb7-isp-write2-state.json")

# The verify module is deliberately read-only; declare the mutating opcodes here.
_m._ALLOWED = _m._ALLOWED | {SUB_PROGRAM, SUB_ERASE}

# 512-byte marker. Mostly 0xFF, clearing at most 2 bits per byte: if a program
# ever lands somewhere unintended it damages a few bits rather than a page,
# while staying trivially detectable in a diff.
MARKER = bytes((0xFF ^ ((i * 7 + 1) & 0x03)) for i in range(BLOCK))


def guard(offset, length, what):
    if not (SCRATCH_LO <= offset and offset + length <= SCRATCH_HI):
        raise ValueError(f"REFUSED: {what} 0x{offset:x}..0x{offset+length:x} "
                         f"outside scratch [0x{SCRATCH_LO:x},0x{SCRATCH_HI:x})")
    if what == "erase" and offset % SECTOR:
        raise ValueError(f"REFUSED: erase 0x{offset:x} not sector-aligned")
    if what == "program" and offset % BLOCK:
        raise ValueError(f"REFUSED: program 0x{offset:x} not block-aligned")


def cdb_program(offset, nbytes):
    """F6 06: BE32 raw byte address, BE16 count in 512-byte blocks."""
    guard(offset, nbytes, "program")
    if nbytes % BLOCK:
        raise ValueError("program length must be a multiple of 512")
    return (bytes([0xF6, SUB_PROGRAM, 0x00])
            + struct.pack(">I", ABS_BASE + offset)
            + struct.pack(">H", nbytes // BLOCK) + bytes(7))


def cdb_erase(offset):
    """F6 15: BE16 512-byte-block index of the sector-aligned address. No count."""
    guard(offset, SECTOR, "erase")
    idx = ((ABS_BASE + offset) >> 9) & 0xFFFF
    return bytes([0xF6, SUB_ERASE, 0x00]) + struct.pack(">H", idx) + bytes(11)


def cmd_out(dev, cdb, data):
    """BOT with a data-OUT phase. The only writing primitive in this file."""
    if cdb[1] != SUB_PROGRAM:
        raise ValueError("cmd_out is only for F6 06")
    dev.tag = (dev.tag + 1) & 0xFFFFFFFF
    cbw = struct.pack("<IIIBBB", 0x43425355, dev.tag, len(data), 0x00, 0, 16) + cdb
    dev._xfer(dev.ep_out, ct.create_string_buffer(cbw, 31), 31)
    dev._xfer(dev.ep_out, ct.create_string_buffer(bytes(data), len(data)), len(data))
    csw = ct.create_string_buffer(13)
    dev._xfer(dev.ep_in, csw, 13)
    sig, tag, residue, status = struct.unpack("<IIIB", bytes(csw.raw[:13]))
    if sig != 0x53425355 or tag != dev.tag:
        raise RuntimeError(f"CSW desync (sig 0x{sig:08x} tag {tag} != {dev.tag})")
    return status


def read_range(dev, offset, length, chunk=0x1000):
    out = b""
    while len(out) < length:
        n = min(chunk, length - len(out))
        d, st, _ = dev.cmd(cdb_read(offset + len(out), n), n)
        if st != 0 or len(d) != n:
            raise RuntimeError(f"read failed at 0x{offset+len(out):x}")
        out += d
    return out


def poll_ready(dev, tries=200):
    for _ in range(tries):
        s, _st, _ = dev.cmd(cdb_simple(SUB_STATUS), 1)
        if s and not (s[0] & 0x01):
            return True
    return False


def full_diff(dev, baseline_path, intended_lo, intended_hi, chunk=0x1000):
    """Re-read the image range and report every byte differing from baseline."""
    base = open(baseline_path, "rb").read()
    end = min(len(base), IMAGE_END)
    print(f"  full-image verification: re-reading 0x{end:x} bytes ...")
    cur = bytearray()
    while len(cur) < end:
        n = min(chunk, end - len(cur))
        n = ((n + BLOCK - 1) // BLOCK) * BLOCK
        d, st, _ = dev.cmd(cdb_read(len(cur), n), n)
        if st != 0:
            raise RuntimeError(f"verify read failed at 0x{len(cur):x}")
        cur += d
        if len(cur) % 0x200000 < chunk:
            print(f"\r    {100.0*len(cur)/end:5.1f}%", end="", flush=True)
    print("\r    100.0%")
    diff = [i for i in range(end) if cur[i] != base[i]]
    stray = [d for d in diff if not (intended_lo <= d < intended_hi)]
    print(f"  bytes differing from baseline: {len(diff)}")
    if stray:
        print(f"  *** {len(stray)} STRAY CHANGES OUTSIDE THE TARGET ***")
        cl, s, p = [], stray[0], stray[0]
        for x in stray[1:]:
            if x - p > 256:
                cl.append((s, p)); s = x
            p = x
        cl.append((s, p))
        for a, b in cl[:10]:
            print(f"      0x{a:08x}-0x{b:08x}")
        return False, bytes(cur)
    print("  no stray changes anywhere in the image range.")
    return True, bytes(cur)


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=("program", "erase"), required=True)
    ap.add_argument("--offset", type=lambda s: int(s, 0), default=0x8E000)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    off = args.offset

    if args.stage == "program":
        cdb = cdb_program(off, len(MARKER))
        what = f"program {len(MARKER)} B ({len(MARKER)//BLOCK} block) at 0x{off:x}"
        lo, hi = off, off + len(MARKER)
    else:
        cdb = cdb_erase(off)
        what = f"erase {SECTOR} B sector at 0x{off:x}"
        lo, hi = off & ~(SECTOR - 1), (off & ~(SECTOR - 1)) + SECTOR

    print(f"stage     : {args.stage}")
    print(f"target    : 0x{off:08x}   scratch [0x{SCRATCH_LO:x},0x{SCRATCH_HI:x})")
    print(f"CDB       : {cdb.hex(' ')}")
    print(f"action    : {what}")
    print(f"encoded   : addr field 0x{int.from_bytes(cdb[3:7] if args.stage=='program' else cdb[3:5],'big'):x}"
          f"   (ABS_BASE=0x{ABS_BASE:x})")
    if args.stage == "erase":
        print("  NOTE: erase encoding is static-analysis only. If wrong, the")
        print("        16-bit field can only reach 0x0000-0xffff = header+loader.")
        print("        Recovery: full-chip SPI rewrite from your known-good backup image.")

    if not args.commit:
        print("\nDRY RUN — nothing sent. Re-run with --commit.")
        return 0

    st_ = load_state()
    if args.stage == "erase" and st_.get("programmed_at") != off:
        print(f"\nABORT: no verified marker at 0x{off:x}. Run --stage program first.")
        print("       Erasing an already-0xFF sector proves nothing: a correct")
        print("       erase and a total miss look identical.")
        return 1

    dev = Device()
    try:
        _, s, _ = dev.cmd(cdb_simple(SUB_EN4B))
        print(f"\nF6 17 enter 4-byte addressing: status {s}")
        sec = off & ~(SECTOR - 1)
        before = read_range(dev, sec, SECTOR)

        if args.stage == "program":
            page = before[off - sec:off - sec + len(MARKER)]
            if page != b"\xff" * len(MARKER):
                print(f"ABORT: target not erased ({page[:8].hex(' ')})")
                return 1
            print("  precondition OK: target is fully erased")
            s = cmd_out(dev, cdb, MARKER)
            print(f"  F6 06 program: CSW status {s}")
        else:
            if before[off - sec:off - sec + len(MARKER)] != MARKER:
                print("ABORT: expected marker not present; refusing to erase.")
                return 1
            print("  precondition OK: marker present, so erase is observable")
            _, s, _ = dev.cmd(cdb)
            print(f"  F6 15 erase: CSW status {s}")
        poll_ready(dev)

        after = read_range(dev, sec, SECTOR)
        if args.stage == "program":
            got = after[off - sec:off - sec + len(MARKER)]
            ok = got == MARKER
            print(f"  read-back: {'MARKER PRESENT' if ok else 'MISMATCH'}")
        else:
            ok = after == b"\xff" * SECTOR
            print(f"  sector now: {'ALL 0xFF (erased)' if ok else 'NOT erased'}")

        clean, _ = full_diff(dev, args.baseline, lo, hi)
        print("\n--- verdict ---")
        if ok and clean:
            print(f"PASS: {args.stage} landed exactly where computed; nothing else")
            print("      in the image range changed.")
            if args.stage == "program":
                json.dump({"programmed_at": off}, open(STATE, "w"))
                print("      Stage 2 (erase) is now unlocked.")
            else:
                json.dump({}, open(STATE, "w"))
                print("      *** F6 15 ERASE ENCODING IS NOW HARDWARE-CONFIRMED. ***")
        elif not clean:
            print("FAIL: wrote somewhere unintended (stray list above).")
            print("      Recover: full-chip SPI write from your known-good backup image.")
        else:
            print(f"INCONCLUSIVE: nothing strayed, but the {args.stage} did not")
            print("      take effect. Device may have rejected the command.")
        return 0 if (ok and clean) else 2
    finally:
        dev.close()


if __name__ == "__main__":
    sys.exit(main())
