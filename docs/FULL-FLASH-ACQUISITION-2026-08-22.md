# Full SPI-NOR acquisition and firmware consequences

Date: 2026-08-22

## Outcome

Two complete 32-MiB reads of the keyboard's external Macronix SPI NOR are
bit-identical. This is a strong read-only backup and gives us the missing
physical tail/configuration data. It does **not** yet prove that erase, program,
restore or post-restore boot works, so `flash_approved` remains false.

The dump materially changed the clean-room firmware in two ways:

1. the previous custom storage map was unsafe because it overlapped stock
   configuration and upload partitions; the four mutable slots have been moved;
2. stock has five profile indices (`0..4`), so the runtime, `KBP1`, host
   capabilities and offline compiler now support five rather than four.

No proprietary binary or programmer log is included in the public tree. The
machine-readable file `hardware/kb7-stock-flash.json` records only hashes,
offsets, lengths and independently derived format facts.

## Acquisition evidence

| Fact | Result |
|---|---|
| programmer | CH341B PCB through flashrom's `ch341a_spi` backend |
| flashrom | 1.7.0 |
| JEDEC ID | `c2 20 19` |
| identified part | Macronix `MX25L25635F/MX25L25645G`, 32 MiB |
| status register | `0x00`; block protection, WEL and WIP clear |
| board power | normal USB power; programmer VCC disconnected |
| reset hold | `MCU_RST` measured about 3.2 V released and 0.2 V through 1 kΩ to ground |
| read size | 33,554,432 bytes each |
| both SHA-256 | `c3c4125b8c42019bac65be8cb71ee1d8b9f91dd32c1f8cc918b34454d9bb7027` |
| equality | byte-for-byte identical |

The second log is the canonical acquisition transcript. The first log contains
an interleaved failed second flashrom invocation (`LIBUSB_ERROR_BUSY`), although
the completed first binary is independently validated by the matching second
read. Flashrom also warns that it does not clone the chip's one-time-programmable
area; the 32-MiB main array backup is complete, but OTP/security-register state
is outside this evidence.

Log SHA-256 values are `a5cc887ff442979a6c4b9a9f619ebf401a8d63c0a08a6f63257c19b73815460a`
for read 1 and `dc569c5c659c0bf7ebe032e239c068a182fccbad9092314bc8aef8139a28019c`
for the canonical read-2 transcript.

The successful read proves that the in-circuit wiring and reset hold are
sufficient for repeatable main-array reads. It does not prove the pad's physical
continuity to SoC lead 88, nor any write behavior.

## USB extraction cross-check

The full read exactly contains every previously extracted V1.22 component:

| Object | Flash range | SHA-256 |
|---|---|---|
| 4-KiB boot header | `0x00000000..0x00000fff` | `70d8c190dabfeab8ff75395131dc2ae89c279d95c967bfc9102f961f79a68af3` |
| preserved loader | `0x00001000..0x0000ffff` | `9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56` |
| manifest sector | `0x00010000..0x00010fff` | `a945368195d825160ebfdd49e5f96581334da3205e0c3bd924e17fb5a7940590` |
| region 0 | `0x00011000`, length `0xf35c` | `d779faf9f591e71602e5f17e966ac366602699a83fb5e612534d694d3dafd153` |
| region 1 | `0x00021000`, length `0x6b168` | `b2869bc657ba896474e760f513e4514fac678a951364efc29cbf9b6bb5e2ba72` |

This is important provenance: the machine code used for the clean-room analysis
really is the code installed on this physical unit, not merely a matching update
package.

## Manifest verification and unresolved region-2 state

The recovered checksum is the sum modulo 2^32 of zlib CRC-32 values for each
successive 64-KiB chunk. Regions 0 and 1 reproduce their stored checksums exactly.
Region 2 does not:

| Region | Stored | Calculated from installed flash |
|---|---:|---:|
| 0 | `0xc3f43a6f` | `0xc3f43a6f` |
| 1 | `0xc8ed2815` | `0xc8ed2815` |
| 2 | `0xaa83e9a3` | `0xdaa1be3b` |

The installed region 2 differs from the official V1.24 region 2 by exactly 52
bytes in four ranges: `0xa02022..0xa0202f`, `0xa020be..0xa020d1`,
`0xa020d6..0xa020db`, and `0xa020e8..0xa020f3`. Every differing installed byte
is zero; the remaining `0x146af58` bytes are identical. Running the recovered
checksum over the official region produces exactly the manifest's stored
`0xaa83e9a3`, so the manifest describes the official bytes rather than the
installed zeroed variant. The official bytes look like small RGB565/pixel data,
but their exact asset role is not established.

The preserved loader contains a generic manifest checksum routine and the boot
configuration names only the manifest at `0x60010000`. The keyboard was working
before acquisition, but that does not prove a later cold boot checked this exact
post-runtime array state successfully. Whether runtime modified the asset,
normal boot skips or tolerates it, or another state/path is involved remains
unresolved. We must not silently replace those 52 bytes or claim a fully
understood boot-integrity policy. A targeted sector reread before and after a
true cold boot is useful; it must remain read-only.

## Tail findings

The first programmed tail clusters are `0x1800000..0x1804fff` and
`0x1a00000..0x1a0efff` (with erased holes). Both contain valid version-1 headers
declaring five profiles. The active bank selects profile 4. Recovered code also
contains concrete XIP references to the active bank's sectors and implements a
separate transfer/store path at `0x1f00000`.

The type-`0x20` profile records carry the same 85-byte default selector-to-HID
table used by the replacement firmware. This independent storage/code agreement
raises confidence in the key map. Active type-`0x30` records are also resolved
structurally: each has an 8-byte header, an 85-entry little-endian `uint16_t`
permutation, and a valid trailing additive checksum. Profiles 1 through 4 are
identity permutations. Profile 0 swaps entries 6 and 22, which is direct stock
evidence for per-profile logical remapping. Header byte 3 is 1 only in that
record, but it is not assumed to be the separate MCU2 route-layout selector.
Parsed record groups consistently cover five indices and most have matching
trailing additive sums; several programmed groups remain unparsed and the
complete semantics have not been assumed by the clean-room format.

Conservative ownership is therefore:

- preserve `0x1800000..0x1bffffff` as stock configuration;
- preserve `0x1f00000..0x1ffffff` as the stock upload/store partition;
- use only the erased custom A/B ranges documented in `STORAGE-MAP.md`.

## Reproducible inspection

`tools/inspect_stock_flash.py` validates size, hash, manifest regions/checksums,
4-KiB programmed ranges, stock configuration framing and optional duplicate/
region-2 reference comparisons. It is read-only:

```sh
python3 tools/inspect_stock_flash.py kb7-stock-1.bin \
  --compare kb7-stock-2.bin --output inspection.json
```

Raw filenames and artifacts are operator inputs and stay outside the repository.

## What remains before any write

1. Store the two original binaries in two independent locations and retain the
   canonical log and hashes.
2. Reread the `0xa02000` sector after a true cold boot to confirm the 52-byte
   region-2 state is stable.
3. Read the flash configuration/security registers needed to establish 4-byte
   addressing, quad mode and protection behavior; preserve any OTP identifiers.
4. Prove `MCU_RST` continuity/waveform and check that the SoC never drives the
   SPI bus while held.
5. Validate a bounded erase/program/readback cycle on an expendable or known
   custom-safe sector before contemplating a firmware region.
6. Prove complete stock restore and normal boot. Until then the backup is a
   strong recovery asset, not a demonstrated recovery procedure.
