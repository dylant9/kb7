# KB7 custom flash storage map

## Immutable/prohibited ranges

| Flash offsets | Size | Rule |
|---|---:|---|
| `0x0000000..0x000ffff` | 64 KiB | header + loader; never erase/write |
| `0x00100000..0x0156af8b` | `0x146af8c` | vendor region 2; never erase/write |

The in-image gap's first fully free sector is `0x0008d000`. The confirmed
MX25L25645G tail begins at sector `0x0156b000`; all tail commands require 4-byte
address mode because they are above 16 MiB.

## In-image gap (`0x8d000..0xfffff`)

| Range | Purpose |
|---|---|
| `0x8d000..0x8dfff` | engineering boot/crash marker, future; initially erased |
| `0x8e000..0x8ffff` | two rotating 4-KiB diagnostic records, future |
| `0x90000..0xfffff` | reserved; no v1 dependency |

The first release plan does not program this gap. Keeping it unused minimizes
interaction with loader region boundaries.

## Tail (`0x156b000..0x1ffffff`)

| Start | End exclusive | Length | Purpose |
|---:|---:|---:|---|
| `0x156b000` | `0x156c000` | 4 KiB | superblock A / future asset generation index |
| `0x156c000` | `0x156d000` | 4 KiB | superblock B |
| `0x156d000` | `0x1570000` | 12 KiB | alignment/reserved |
| `0x1570000` | `0x1770000` | 2 MiB | screen slot A |
| `0x1770000` | `0x1970000` | 2 MiB | screen slot B |
| `0x1970000` | `0x1c70000` | 3 MiB | custom asset/font slot A |
| `0x1c70000` | `0x1f70000` | 3 MiB | custom asset/font slot B |
| `0x1f70000` | `0x1fe0000` | 448 KiB | wear-levelled profiles/per-key config |
| `0x1fe0000` | `0x2000000` | 128 KiB | crash/diagnostic ring |

All boundaries are 4-KiB sector aligned and slots are multiples of the 256-byte
page size.

## Screen slot header

Each 2-MiB slot begins with 64 bytes: magic `KSL1`, version/header length, state,
generation, payload length, payload CRC-32, header CRC-32, and 36 reserved bytes.
The header CRC is calculated with `state=VALID` and the CRC field zero. This lets
finalization change only state from `WRITING=0x7fffffff` to
`VALID=0x3fffffff`, a legal NOR 1→0 bit transition. `ERASED=0xffffffff`.

Commit:

1. Select the non-active/older slot; never erase the active slot.
2. Erase the inactive slot sectors needed.
3. Write WRITING header with generation `max+1` and final-state header CRC.
4. Program payload in 256-byte pages; read back and CRC it.
5. Clear the state word to VALID and read back the header.
6. At boot, validate both slots and choose the newest valid generation using
   wrap-safe signed subtraction. If neither validates, use built-in UI.

The C implementation validates the complete payload before choosing a slot; a
newer header with a corrupt payload cannot hide the older valid generation. The
simulated-NOR host test covers corruption fallback, wrap-safe selection, staged
write failures, and preservation of the active slot when BEGIN erases its
target.

The two superblocks are not needed for screen selection—generation headers avoid
a fragile active pointer. They are reserved for the larger asset-store manifest,
which will need a compact index.

Wear policy: ordinary UI boot is read-only. Writes occur only on explicit host
commit. Profiles use append-only 4-KiB records and compact only after 75% usage.
Crash records rotate sectors. Factory reset erases custom slot headers only and
can never affect firmware or region 2.
