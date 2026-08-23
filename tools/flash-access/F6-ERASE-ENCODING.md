# `F6 15` / `F6 19` erase-command encoding

Status: **resolved by static data-flow analysis on 2026-08-22; the normal-NOR
`F6 15` target interpretation and an exact observable 4-KiB footprint at one
guarded target were confirmed on hardware on 2026-08-23.** `F6 19` remains
static-only.

## Result

The erase address is a **512-byte-block index**, not a raw byte address.

| Command | Exact address field | Count/length in CDB |
|---|---|---|
| `F6 15` | `CDB[3:5] = BE16((aligned_address >> 9) & 0xffff)` | none |
| `F6 19` | `CDB[3:7] = BE32(aligned_address >> 9)` | none |

`aligned_address` is the address supplied to the vendor erase operator, rounded
down to its erase granularity. In the official NOR path that address is in the
SoC flash window: `0x60000000 + flash_offset`.

That base convention is visible independently of the erase builder. The NOR
operation is initialized inside the `0x60000000` SoC flash window, passes each
record's absolute start address to the erase operator, and compares `start +
length` against the absolute `0x61000000` 16-MiB boundary beforehand.

Consequently, for the KB7 NOR path:

```text
F6 15 field = ((0x60000000 + flash_offset) >> 9) & 0xffff
             = flash_offset >> 9
```

The equality holds because `0x60000000 >> 9` has zeroes in its low 16 bits.
Do not generalise that simplification to `F6 19`: its four-byte field preserves
the high part, so the DLL would send `(0x60000000 + flash_offset) >> 9`.

For example, flash offset `0x00080000` is aligned for both recovered erase
paths. It gives absolute address `0x60080000` and block index `0x00300400`:

```text
F6 15  00 04 00 00 00 00 00 00 00 00 00 00 00 00
F6 19  00 00 30 04 00 00 00 00 00 00 00 00 00 00
```

The first two bytes shown on each line are the `F6` opcode and subcode. Both
CDBs are 16 bytes. Unlisted bytes remain zero.

## Analysis provenance and function boundaries

The result was independently summarized from local static analysis of a
lawfully obtained PE32+ updater. It was loaded in radare2 with relocations
applied. Proper function recovery showed a primary erase routine, an alternate
erase routine, a program routine, and one switch-based command builder. No
vendor binary, recovered symbol table, exact internal offset, disassembly
listing, or bulk decompilation is included here; the independently written
data-flow relationships needed to reproduce the interoperability result are
recorded below.

### Companion-package cross-layer check

A second pass used the complete companion SDK package rather than the command
builder in isolation. It closed a possible gap in the original proof:

- the package manifest assigns both the generic command-builder service and the
  NOR-flash operator to the implementation analysed here;
- the active submission path copies the completed 16-byte CDB verbatim into the
  operating system's SCSI pass-through structure;
- an accompanying standalone SCSI transport independently performs the same
  fixed 16-byte copy and does not parse or rescale address/count fields; and
- the exported SDK program/erase entry points store operation parameters and
  schedule plugin work, but do not contain a second `F6` encoder.

The builder output is therefore the CDB delivered to the device. There is no
lower transport layer that could turn the recovered block index back into a
byte address or add an erase count. The other packaged mode-switch and HID
components contain no competing `F6 05`/`06`/`15`/`17`/`18`/`19` builder.

## Calibration: re-deriving the known `F6 06` program format

This trace was calibrated against the destructive hardware result before the
erase result was accepted.

In the recovered program flow:

1. The start-address argument is preserved without a shift.
2. The NOR transfer size is selected as `0x1000` bytes.
3. That **size**, not the address, is shifted right by 9. For NOR the resulting
   count is 8 blocks.
4. The shared builder receives the unchanged address and shifted size as
   separate arguments.
5. Its `F6 06` case writes the address big-endian to `CDB[3:7]` and the shifted
   size big-endian to `CDB[7:9]`.

Therefore the binary independently yields:

```text
CDB[3:7] = BE32(raw byte address)
CDB[7:9] = BE16(byte_count >> 9)
```

This exactly predicts the hardware incident: address field `0x00000470` and
count field `0x0100` mean 256 blocks, so 128 KiB was programmed beginning at
byte address `0x470`. The last affected byte, `0x2046f`, is
`0x470 + (0x100 * 512) - 1`. The static method therefore reproduces both known
program-field units correctly.

## Erase data flow

The erase path is different from program in precisely the disputed place.

In the primary erase flow:

1. The start address is retained and rounded down to the erase granularity.
2. That aligned **address** is shifted right by 9 and saved.
3. The saved block index is passed unchanged as the shared builder's address
   argument. Optional arguments, including the position used as a count by
   `F6 05`/`F6 06`, are zero.

The alternate erase implementation independently repeats the same flow: it
shifts the aligned start address and invokes the same builder with the shifted
value as the address argument.

The common builder initially zeroes all 16 CDB bytes. Its subcode switch maps:

- `F6 15` to a case that writes the low 16 bits of the address argument,
  big-endian, to `CDB[3:5]`;
- `F6 19` to a case that writes the full 32-bit address argument, big-endian,
  to `CDB[3:7]`.

Neither case writes a length. One CDB represents one erase operation. The host
loop advances the block index by `erase_granularity >> 9`: 8 blocks for the
4-KiB path and 256 blocks for the alternate 128-KiB path.

This closes the original ambiguity: the shifted local is not merely a loop or
progress value. It is the exact value passed as the builder's address argument.

## `F6 19`, `F6 17`, and the selectors

The earlier notes conflated two independent controls.

The service instance registered as the NOR-flash operator initializes an
internal flash-type selector to zero. In the erase routines it selects the
4-KiB/`F6 15` path when zero and the 128-KiB/`F6 19` path when nonzero. A
separate flash-type configuration handler can set it nonzero, so `F6 19` is
reachable. The selector is **not** the three-/four-byte NOR address-mode state.

Four-byte NOR addressing is handled independently. The higher-level
orchestrator compares `start + length` with `0x61000000`, emitting `F6 17` when
the range crosses that boundary and `F6 18` otherwise. That logic neither reads
nor changes the flash-type selector.

This decision is made around both the NOR program and NOR erase operations. A
program or erase wholly below 16 MiB therefore receives `F6 18`, not `F6 17`,
before its mutation command. The address-mode command does not rescale or
reinterpret the 16-bit block index carried by `F6 15`.

Thus:

- entering four-byte NOR mode with `F6 17` does **not** select `F6 19`;
- leaving four-byte NOR mode with `F6 18` does **not** select `F6 15`;
- the normal KB7 NOR erase remains `F6 15` above 16 MiB;
- a 16-bit index in 512-byte units covers exactly 32 MiB. The final 4-KiB
  sector begins at offset `0x01fff000`, whose index is `0xfff8`, so `F6 15`
  can address the entire MX25L25645G.

`F6 19` is statically reachable only if the flash-type selector is nonzero, but
that is not needed for this KB7 NOR. The exact CDB encoding is proven; the
device-side meaning of the nonzero alternate mode has not been exercised on KB7
hardware.

The old claim that another nearby state field was an address-unit/config-table
pointer is also incorrect. The erase/program routines use that scalar only in
busy-wait timing calculations. It does not contribute to any CDB address or
count field.

## Hardware validation at `0x0008e000`

The guarded experiment in [WRITE-TEST-PLAN.md](WRITE-TEST-PLAN.md) completed on
one owner-controlled KB7 using the recovered V1.22 preserved loader. With the
full target sector initially erased, it first selected `F6 18` and programmed a
512-byte marker using:

```text
F6 06 00 60 08 e0 00 00 01 00 00 00 00 00 00 00
```

The complete 32-MiB post-image matched the exact expected marker image. The
erase stage then selected `F6 18` and sent:

```text
F6 15 00 04 70 00 00 00 00 00 00 00 00 00 00 00
```

The marker disappeared at offset `0x0008e000`, and the subsequent complete
32-MiB image compared byte-for-byte equal to the original baseline. No other
byte difference was observable in either postflight image.

This confirms that this loader's normal-NOR `F6 15` path interprets `0x0470` as
the 512-byte-block index for the tested target. It does not prove the exact
erase granularity: the other 3,584 bytes in the sector and the surrounding gap
were already `0xff`, so erasing a narrower or wider all-erased range would be
observationally identical. See the
[dated result](../../docs/USB-ISP-WRITE-VALIDATION-2026-08-23.md) for the hashes,
transport checks and full evidence boundary.

## Guarded footprint validation at `0x000c6000`

A second fixed experiment populated all eight 512-byte blocks of sector
`[0x000c6000,0x000c7000)` with non-`0xff` patterns and placed non-`0xff`
512-byte guards immediately below and above it. After an exact full-chip
preflight, it selected `F6 18` and sent:

```text
F6 15 00 06 30 00 00 00 00 00 00 00 00 00 00 00
```

All 4,096 target bytes read back as erased, both adjacent guards survived
exactly, and the complete 32-MiB image matched its predicted postimage. Separate
cleanup stages restored the original baseline exactly, a final new-session USB
capture matched it, and the owner then confirmed normal operation after a cold
boot.

This establishes an observable exact 4-KiB programmed-data erase footprint at
that target on the tested unit, preserved V1.22 loader and normal-NOR path. It
does not generalize the result to every address, device, loader or flash
revision, and it does not test `F6 19`, above-16-MiB mutation or interruption
behavior. See the
[dated footprint result](../../docs/USB-ISP-ERASE-GRANULARITY-VALIDATION-2026-08-23.md).

## Proven facts versus remaining inference

Proven from the updater's register and stack data flow:

- both erase commands use a 512-byte-block index;
- the two-byte and four-byte field widths and byte order shown above;
- neither erase CDB carries a count;
- one command is issued per host-loop erase unit;
- `F6 17`/`F6 18` selection is independent of `F6 15`/`F6 19` selection and
  does not change how the erase index is interpreted;
- the registered NOR operator defaults the flash-type selector to zero, and a
  separate configuration path can change it;
- the separately traced state is timing data, not an address-unit table.
- both available SCSI submission implementations copy the completed CDB
  unchanged, with no lower-layer unit conversion.

Inferred from the known MX25L25645G target and the zero-selector NOR default:

- the normal KB7 configuration should leave the selector at zero and use the
  `F6 15` 4-KiB path. Static analysis proves the default and the available
  setter, but cannot prove which optional flash-type choice an operator would
  make at runtime.

Still not proven on hardware:

- arbitrary targets, other command sizes, repeated/interrupted operation or
  another loader/flash revision; and
- the exact device-side purpose and behavior of the alternate
  `F6 19`/128-KiB mode.

## Tooling and write-path verdict

An earlier command emitter was based on two disproven `F6 06` fields. This
branch now includes `kb7-isp-write2.py`, a narrow, dry-run-by-default laboratory
utility for a coupled marker-program and sector-erase experiment. It is not a
general USB writer or a supported firmware installation path.

**Use the proven SPI/flashrom path for ordinary, recovery and production
writes.**

Static analysis settles both CDB layouts, and the normal-NOR `F6 15` target
interpretation has now passed once at `0x8e000`. That narrow result does not
make a general erase operation safe: erase is irreversible for a whole unit;
the loader identifies itself as `v0.001 test!`; its bulk transport is unreliable
above 4 KiB; and the prior program experiment destroyed the boot chain despite
correct host-side range guards. By contrast, the SPI path is the demonstrated
recovery route on this exact board and can be constrained with flashrom layouts.

There is no erase test that is non-destructive under every implementation
failure. [WRITE-TEST-PLAN.md](WRITE-TEST-PLAN.md) documents the explicitly
destructive two-stage validation experiment whose recovery assumption is a
working external-SPI path and byte-exact backup. That experiment has now passed
once for the exact sequence recorded above. It does not validate `F6 19`, create
a supported updater or change `flash_approved=false`.
