#!/usr/bin/env python3
"""
KB7 ISP read-reliability test -- STRICTLY READ-ONLY.

Reads the SAME small region of flash many times via F6 05 and reports whether
the device returns identical data every time.

WHY: kb7-isp-verify.py showed non-deterministic corruption over a 22MB read, but
that can't distinguish "the SoC's flash interface is failing" from "the ISP
mode's bulk-read implementation is buggy". Re-reading one fixed region isolates
the read path's own repeatability from everything else.

Also sweeps chunk size: if 512B reads are stable but 4KB reads are not, the fault
is in the bootloader's buffering, not in the flash hardware.

Usage:
    sudo python3 kb7-isp-repeat.py                      # 20 passes at 4KB
    sudo python3 kb7-isp-repeat.py -n 50 --offset 0x56f000
    sudo python3 kb7-isp-repeat.py --sweep              # try several chunk sizes
"""

import argparse
import collections
import hashlib
import sys

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "kb7isp", __file__.rsplit("/", 1)[0] + "/kb7-isp-verify.py")
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
Device, cdb_read, cdb_simple, SUB_EN4B = _m.Device, _m.cdb_read, _m.cdb_simple, _m.SUB_EN4B


def one_pass(dev, offset, length, chunk):
    """Read [offset, offset+length) in `chunk`-sized F6 05 commands."""
    buf = b""
    while len(buf) < length:
        n = min(chunk, length - len(buf))
        d, st, _ = dev.cmd(cdb_read(offset + len(buf), n), n)
        if st != 0 or len(d) != n:
            raise RuntimeError(f"read failed at 0x{offset+len(buf):x} "
                               f"(status {st}, got {len(d)}/{n})")
        buf += d
    return buf


def run(dev, offset, length, chunk, passes, label):
    seen = collections.Counter()
    first = None
    fails = 0
    for i in range(passes):
        try:
            b = one_pass(dev, offset, length, chunk)
        except RuntimeError as e:
            fails += 1
            print(f"    pass {i+1:2}: TRANSFER ERROR ({e})")
            continue
        h = hashlib.sha256(b).hexdigest()
        if first is None:
            first = h
        seen[h] += 1
    uniq = len(seen)
    tag = "STABLE" if uniq == 1 and not fails else "*** UNSTABLE ***"
    print(f"  {label}: {uniq} distinct result(s) over {passes} passes, "
          f"{fails} transfer error(s)  -> {tag}")
    for h, c in seen.most_common():
        print(f"      {c:3}x  {h[:32]}")
    return uniq == 1 and not fails


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offset", type=lambda s: int(s, 0), default=0x56f000,
                    help="flash offset to re-read (default 0x56f000 — a chunk "
                         "that came back wrong in the full dump)")
    ap.add_argument("--length", type=lambda s: int(s, 0), default=0x4000,
                    help="bytes per pass (default 0x4000 = 16KB)")
    ap.add_argument("-n", "--passes", type=int, default=20)
    ap.add_argument("--chunk", type=lambda s: int(s, 0), default=0x1000)
    ap.add_argument("--sweep", action="store_true",
                    help="test 512B / 1KB / 2KB / 4KB chunk sizes")
    args = ap.parse_args()

    dev = Device()
    try:
        print(f"connected: iface {dev.iface} ep_in 0x{dev.ep_in:02x} "
              f"ep_out 0x{dev.ep_out:02x}")
        _, st, _ = dev.cmd(cdb_simple(SUB_EN4B))
        print(f"F6 17 enter 4-byte addressing: status {st}")
        print(f"\nre-reading 0x{args.offset:x} .. 0x{args.offset+args.length:x} "
              f"({args.length} bytes), {args.passes} passes\n")

        results = {}
        chunks = [0x200, 0x400, 0x800, 0x1000] if args.sweep else [args.chunk]
        for c in chunks:
            results[c] = run(dev, args.offset, args.length, c,
                             args.passes, f"chunk 0x{c:04x}")

        print("\n--- interpretation ---")
        stable = [c for c, ok in results.items() if ok]
        unstable = [c for c, ok in results.items() if not ok]
        if not unstable:
            print("Every chunk size returned identical data on every pass.")
            print("=> The ISP read path is repeatable here. The corruption seen over")
            print("   the full 22MB dump is NOT simple per-read flakiness — suspect")
            print("   something that only shows up over long transfers.")
        elif stable and unstable:
            print(f"STABLE at chunk size(s): {[hex(c) for c in stable]}")
            print(f"UNSTABLE at chunk size(s): {[hex(c) for c in unstable]}")
            print("=> Reliability depends on TRANSFER SIZE, not on the flash cells.")
            print("   That is a bootloader/USB buffering bug, not failing hardware.")
            print("   The keyboard's own boot-time read path may be unaffected.")
        else:
            print("Unstable at every chunk size tested — the same address returns")
            print("different data on repeated reads.")
            print("=> The SoC's flash read path itself is unreliable. This is")
            print("   consistent with the intermittent boot failures.")
    finally:
        dev.close()


if __name__ == "__main__":
    sys.exit(main())
