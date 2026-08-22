# `F6` write-command encoding — final investigation record

Status as of 2026-08-22: **`F6 06` program is confirmed on hardware and
`F6 15`/`F6 19` erase is resolved by calibrated static data-flow analysis.**
This does not authorize USB writes; see the safety verdict below.

The result was independently summarized from local static analysis of a
lawfully obtained updater. No vendor binary, recovered symbol table,
disassembly listing, or bulk decompilation is included in this tree.

## Final encodings

All commands use a 16-byte CDB and leave unspecified bytes zero.

| Command | Function | Address | Count |
|---|---|---|---|
| `F6 05` | read | `CDB[3:7]` = BE32 raw byte address | `CDB[7:9]` = BE16 512-byte blocks |
| `F6 06` | program | `CDB[3:7]` = BE32 raw byte address | `CDB[7:9]` = BE16 512-byte blocks |
| `F6 15` | 4-KiB-path erase | `CDB[3:5]` = BE16 of `(aligned_address >> 9) & 0xffff` | none |
| `F6 19` | alternate 128-KiB-path erase | `CDB[3:7]` = BE32 of `aligned_address >> 9` | none |

The official NOR path uses memory-mapped addresses beginning at `0x60000000`.
For `F6 15`, the low 16 bits of `(0x60000000 + flash_offset) >> 9` equal
`flash_offset >> 9`. `F6 19` preserves the high part and must not be modelled by
blindly reusing that simplification.

The complete clean-room data-flow proof, builder behavior, and status of each
claim are in [F6-ERASE-ENCODING.md](F6-ERASE-ENCODING.md).

## Calibration: why the result is trustworthy

The static method was first applied to `F6 06`, whose answer was already known
from hardware:

- the program start address reaches the builder without a shift;
- the selected transfer size is shifted right by 9 and reaches a separate
  builder argument;
- the shared builder serialises those arguments to `CDB[3:7]` and `CDB[7:9]`.

This re-derives a raw byte address plus a count in 512-byte blocks. It exactly
predicts the destructive result of sending address `0x470`, count `0x0100`:
128 KiB programmed from byte `0x470` through `0x2046f`.

The same calling convention and common builder were then followed for erase.
There the aligned **address itself** is shifted right by 9 and passed as the
builder's address argument; the `F6 15`/`F6 19` cases serialize it directly.
The count argument is zero and neither erase case writes a count field.

The complete companion SDK package was then checked for a downstream rewrite.
The updater's active SCSI submission path copies the finished 16-byte CDB
verbatim, an accompanying standalone transport does the same, and the SDK
program/erase entry points only schedule the plugin operation. No lower layer
rescales the address, changes the count units, or supplies an erase length.

## Corrections to the Phase-0 model

The earlier write-path model made several safety-critical mistakes:

1. `F6 06` program does **not** use a block-index address. Its address is raw
   byte units.
2. `F6 06` count is not bytes. It is 512-byte blocks.
3. The eight apparent command builders are switch branches in one shared
   function, not independent functions.
4. The flash-type selector is not the current three-/four-byte NOR address-mode
   bit. The registered NOR operator defaults it to zero; a separate
   configuration handler can change it.
5. A separate scalar is wait-timing state, not a flash address-unit table.
6. `F6 19` is not selected simply because an address exceeds 16 MiB.

Four-byte addressing is asserted independently. The higher-level updater
compares the end address with `0x61000000` and emits `F6 17` when it crosses
that boundary, or `F6 18` when the range remains below it. This is done for
both program and erase. It does not change the interpretation of the `F6 15`
block index and has no interaction with the separate flash-type selector that
chooses `F6 15` versus `F6 19`. The normal NOR erase can therefore still use
`F6 15` in either address mode: its 16-bit field is in 512-byte units and covers
the KB7's complete 32-MiB flash.

## Why USB is still not the supported write path

**Use the ESP32/flashrom SPI path for ordinary, recovery and production
writes.**

The recovered layout is now precise, but the loader's erase implementation has
not been exercised safely on hardware. No no-op or bounded query can validate
it: an erase command capable of testing the interpretation necessarily erases
at least one complete unit. The bootloader calls itself `v0.001 test!`, its bulk
endpoint fails above 4 KiB, and the first program experiment destroyed the boot
chain after a host-side guard validated the intended rather than encoded
address. The SPI path is proven on this board and supports explicit flashrom
layouts and read-back verification.

The branch now contains `kb7-isp-write2.py`, a deliberately narrow,
dry-run-by-default two-stage validation utility. It can emit only the reviewed
marker-program and sector-erase experiment after explicit `--commit` and
fail-closed preconditions. It is not a supported USB flasher and does not make
replacement firmware flash-approved.

## No non-destructive erase test

None exists. Static analysis resolves byte-address versus block-index encoding.
The remaining question is whether the target performs the destructive operation
correctly, and testing that necessarily changes flash. The bounded experiment
in [WRITE-TEST-PLAN.md](WRITE-TEST-PLAN.md) accepts that risk; it does not make
the test non-destructive under every remaining interpretation or implementation
failure.
