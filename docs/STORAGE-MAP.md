# KB7 custom flash storage map

## Evidence and rule

Two independent 32-MiB CH341/flashrom reads made on 2026-08-22 were
bit-identical. They prove that the tail is **not** generally free space: stock
configuration banks occupy `0x1800000` and `0x1a00000`, and recovered stock code
addresses a separate 1-MiB store beginning at `0x1f00000`. The earlier custom
map overlapped all three. It must not be used.

The replacement firmware may mutate only the four A/B slots in the table below.
Every vendor range and every merely-erased/unallocated range remains denied by
`kb7_flash_range_mutable()`. An erased sector is evidence of current contents,
not proof that no stock version or recovery path owns it.

## Immutable/prohibited ranges

| Flash offsets | Rule |
|---|---|
| `0x0000000..0x0156afff` | complete stock boot container, code, region 2 and padding; never erase/write |
| `0x01800000..0x019fffff` | stock/legacy five-profile configuration partition; preserve wholesale |
| `0x01a00000..0x01bfffff` | active stock five-profile configuration partition; preserve wholesale |
| `0x01f00000..0x01ffffff` | stock-owned 1-MiB upload/store partition referenced by both recovered code regions |

The in-image gap `0x0008d000..0x000fffff` is erased in both reads but remains
prohibited. The first release does not need it, and preserving it avoids an
unnecessary loader/version compatibility assumption.

## Tail allocation

| Start | End exclusive | Length | Purpose / policy |
|---:|---:|---:|---|
| `0x0156b000` | `0x0156c000` | 4 KiB | future superblock A; currently prohibited |
| `0x0156c000` | `0x0156d000` | 4 KiB | future superblock B; currently prohibited |
| `0x0156d000` | `0x01570000` | 12 KiB | alignment/reserved; prohibited |
| `0x01570000` | `0x016b0000` | `0x140000` (1.25 MiB) | custom `KBS1` screen slot A |
| `0x016b0000` | `0x017f0000` | `0x140000` (1.25 MiB) | custom `KBS1` screen slot B |
| `0x017f0000` | `0x01800000` | 64 KiB | erased guard band; prohibited |
| `0x01800000` | `0x01a00000` | 2 MiB | stock legacy configuration partition |
| `0x01a00000` | `0x01c00000` | 2 MiB | stock active configuration partition |
| `0x01c00000` | `0x01c38000` | `0x38000` (224 KiB) | custom `KBP1` profile slot A |
| `0x01c38000` | `0x01c70000` | `0x38000` (224 KiB) | custom `KBP1` profile slot B |
| `0x01c70000` | `0x01f00000` | `0x290000` | erased/unallocated; prohibited |
| `0x01f00000` | `0x02000000` | 1 MiB | stock upload/store partition |

All slot boundaries are 4-KiB sector aligned and multiples of the 256-byte
page size. Commands above 16 MiB require the proven 4-byte address path.

## Stock tail observations

Both stock configuration headers begin with `f5 10`, have version 1, declare
five profiles and have valid trailing additive checksums. The legacy header at
`0x1800000` selects profile 0; the active header at `0x1a00000` selects profile
4. Record groups consistently enumerate indices 0 through 4. The active
type-`0x20` records contain the same 85-byte default usage table independently
recovered from program flow, which cross-checks the replacement key map.
Active type-`0x30` records contain five checksum-valid 85-entry `uint16_t`
permutations: profile 0 swaps indices 6 and 22, while profiles 1 through 4 are
identity mappings. This supports the custom firmware's per-profile remapping
model, but it is not conflated with the distinct MCU2 sensor-route variants.

These observations justify expanding the clean-room runtime/KBP1 limit from
four to five profiles. They do **not** justify writing or reusing the stock
record format: several record semantics remain unresolved, and preserving the
entire stock partitions is the safer compatibility boundary.

## Custom slot header and commit

Each custom slot begins with 64 bytes: magic `KSL1`, version/header length,
state, generation, payload length, payload CRC-32, header CRC-32 and 36 reserved
bytes. The header CRC is calculated with `state=VALID` and the CRC field zero.
Finalization therefore changes only `WRITING=0x7fffffff` to
`VALID=0x3fffffff`, a legal NOR 1→0 transition. Erased state is `0xffffffff`.

Commit:

1. Select the non-active/older slot; never erase the active slot.
2. Erase its header sector and later sectors lazily as ordered payload writes
   reach them.
3. Write the WRITING header with generation `max+1` and final-state header CRC.
4. Program page-bounded payload chunks, read them back and CRC the result.
5. Clear the state word to VALID and read back the header.
6. At boot, validate payload and object semantics for both generations, trying
   the older valid object if the newer one fails.

Ordinary boot is read-only. Writes occur only on explicit host commit and the
public build compiles mutation fail-closed. Factory reset erases only the four
custom slot headers. The future superblocks and unallocated erased spans are not
part of the mutation allow-list.
