#!/bin/bash
# Compare two caller-supplied KB7 flash dumps and characterize any mismatches.
# READ ONLY — analyzes files and never touches hardware.
#
# Usage:
#   ./kb7-compare.sh <dumpA> <dumpB>

set -u
A="${1:?usage: kb7-compare.sh <dumpA> <dumpB>}"
B="${2:?usage: kb7-compare.sh <dumpA> <dumpB>}"

python3 - "$A" "$B" <<'PY'
import sys, zlib, struct, hashlib, collections

pa, pb = sys.argv[1], sys.argv[2]
a = open(pa, "rb").read()
b = open(pb, "rb").read()
print(f"A = {pa}  ({len(a):,} B, sha256 {hashlib.sha256(a).hexdigest()[:16]})")
print(f"B = {pb}  ({len(b):,} B, sha256 {hashlib.sha256(b).hexdigest()[:16]})")

if len(a) != len(b):
    print(f"\n!! size mismatch ({len(a)} vs {len(b)}) — comparing common prefix")
n = min(len(a), len(b))
diff = [i for i in range(n) if a[i] != b[i]]

if not diff:
    print("\nIDENTICAL over the compared range — this read is clean.")
    sys.exit(0)

print(f"\n*** {len(diff)} differing bytes ***")

# --- cluster the differences ---
clusters, start, prev = [], diff[0], diff[0]
for x in diff[1:]:
    if x - prev > 4096:
        clusters.append((start, prev)); start = x
    prev = x
clusters.append((start, prev))
print(f"\n{len(clusters)} cluster(s):")
for lo, hi in clusters[:25]:
    cnt = sum(1 for d in diff if lo <= d <= hi)
    print(f"   0x{lo:08x}-0x{hi:08x}  ({cnt} bytes)")
if len(clusters) > 25:
    print(f"   ... and {len(clusters)-25} more")

# --- bit direction ---
only_clear = all((b[i] & a[i]) == a[i] for i in diff)   # A lost bits vs B
only_set   = all((a[i] & b[i]) == b[i] for i in diff)   # A gained bits vs B
print(f"\nbit direction: A-only-lost-bits={only_clear}  A-only-gained-bits={only_set}")
if not (only_clear or only_set):
    print("   mixed directions -> looks like READ GLITCHES, not cell decay")

# --- which regions are affected, and do CRCs still pass? ---
def fwin(d):
    return sum(zlib.crc32(d[o:o+0x10000]) & 0xffffffff
               for o in range(0, len(d), 0x10000)) & 0xffffffff

print("\nregion CRCs in A (vs A's own manifest):")
man = a[0x10000:0x11000]
if man[:8] == b"SN_FWIN\x00":
    for i, ent in ((0, 0x20), (1, 0x30), (2, 0x40)):
        load, store, length, crc = struct.unpack_from("<IIII", man, ent)
        off = store - 0x60000000
        calc = fwin(a[off:off+length])
        hit = sum(1 for d in diff if off <= d < off + length)
        ok = "PASS" if calc == crc else "*** FAIL ***"
        print(f"   region{i}: declared=0x{crc:08x} computed=0x{calc:08x} {ok}"
              f"   ({hit} differing bytes in this region)")
else:
    print("   manifest magic not found in A — dump may be badly corrupted")

print("\n--- interpretation ---")
if not (only_clear or only_set):
    print("Mixed bit directions are consistent with read instability, but are not proof.")
else:
    print("One-way bit changes may reflect programming/erase state; correlate them")
    print("with independently known mutable ranges before drawing a conclusion.")
PY
