# USB-ISP bounded write validation

Date: 2026-08-23

## Outcome

The guarded two-stage experiment in
[`tools/flash-access/kb7-isp-write2.py`](../tools/flash-access/kb7-isp-write2.py)
completed successfully on one owner-controlled KB7 running the recovered V1.22
preserved loader.

The experiment programmed a 512-byte marker at flash offset `0x0008e000`, then
removed that marker with the recovered erase command. Before and after each
mutation the tool read and compared the complete 32-MiB main array through the
SoC. The final image was byte-for-byte identical to the original baseline.

This is the first direct hardware confirmation of the corrected sub-16-MiB
program and normal-NOR erase sequence:

```text
F6 18
F6 06 00 60 08 e0 00 00 01 00 00 00 00 00 00 00

F6 18
F6 15 00 04 70 00 00 00 00 00 00 00 00 00 00 00
```

It does not turn the validator into a general firmware flasher, validate the
alternate `F6 19` path, or make the replacement firmware flash-approved.

## Preconditions and baseline

Two separately invoked read-only USB-ISP captures were taken immediately before
the experiment. Each capture:

- identified the loader with exact `F6 00` response `01 01`;
- accepted the stable fields of the 36-byte `F6 F1` descriptor;
- used `F6 17` for the full-chip address range;
- read exactly 33,554,432 bytes;
- reproduced every declared `SN_FWIN` region checksum; and
- matched the other capture byte-for-byte.

Their common SHA-256 was:

```text
2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f
```

The connected manifest placed the complete target sector inside the erased gap
`[0x0008d000, 0x00100000)`, outside every declared firmware region. The complete
4-KiB sector at `0x0008e000` was `0xff` before mutation. An independently
rehearsed external-SPI full-chip restore remained the recovery path.

## Program stage

After an offline dry run, the committed program stage:

1. revalidated the connected loader and live manifest;
2. selected `F6 17`, read all 32 MiB, and required an exact match to the
   baseline;
3. selected the vendor's sub-16-MiB mode with `F6 18`;
4. sent one 512-byte marker using `F6 06` at absolute address `0x6008e000` with
   block count `1`;
5. polled `F6 01` to completion;
6. selected `F6 17` and reread all 32 MiB; and
7. required the exact expected marker image before authorizing erase.

The exact marked-image SHA-256 was:

```text
ff04edf228413f97053a408c2eb3d8dc83ecd0a9d6d7c9ef1c6c3bcfe6325154
```

No other byte differed in that complete postflight image.

## Erase stage

After a separate offline dry run, the committed erase stage:

1. required the saved, identity-bound program authorization;
2. revalidated the loader and manifest;
3. selected `F6 17`, read all 32 MiB, and required an exact match to the marked
   image;
4. selected `F6 18`;
5. persisted the fail-closed `erase_started` state;
6. sent `F6 15` with big-endian 16-bit block index `0x0470`;
7. polled `F6 01` to completion; and
8. selected `F6 17`, reread all 32 MiB, and required an exact match to the
   original baseline before deleting the authorization state.

The final SHA-256 returned to
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`.
The tool's `PASS` result therefore means the complete in-session postflight
image compared byte-for-byte equal to the baseline and the state file was
successfully removed.

## What this proves

For this V1.22 loader, flash configuration, unit, offset and command size, the
experiment confirms:

- `F6 18` is the vendor-sequence address-mode command immediately before a
  sub-16-MiB program and erase, and the complete sequence operates correctly in
  the tested state;
- `F6 06` interprets `0x6008e000` as the absolute program address and `1` as one
  512-byte block;
- after the tested `F6 18`, normal NOR erase uses `F6 15` and interprets its
  field independently of the raw byte address used by `F6 06`;
- `F6 15` interprets `0x0470` as the 512-byte-block index for offset
  `0x0008e000`;
- the marker was removed at the encoded target; and
- neither complete postflight image contained any observable unintended byte
  difference.

The hardware run also corroborates the loader-specific BOT behavior used by
the tools: a completed data-bearing `F6` command reports CSW residue equal to
the requested CBW data length, while a no-data command reports zero. Exact
transfer length, signature, tag, status and command-specific residue checks all
remained enabled.

## What this does not prove

- Exact erase granularity is not observable here. The other 3,584 bytes in the
  target sector and the surrounding gap were already `0xff`, so a narrower or
  wider erase of erased bytes could yield the same final image.
- `F6 19`, the alternate flash-type path, was not exercised.
- The run operationally corroborates `F6 18`, but does not independently expose
  or measure the flash controller's internal address-mode transition.
- Independence between the `F6 17`/`F6 18` address-mode choice and the
  `F6 15`/`F6 19` flash-type choice remains a static-analysis result; only the
  `F6 18` + `F6 15` combination was exercised here.
- No above-16-MiB mutation, other offset or length, repeated-cycle endurance,
  interruption/power-loss behavior, or other loader revision was tested.
- Both automatic postflight reads used the same loader/SoC `F6 05` path. They
  prove exact content as observed through that path, not an electrically
  independent SPI read.
- A subsequent cold boot and normal `10f5:5038` functional check were not part
  of the captured mutation transcript.
- The experiment did not install or execute replacement firmware and does not
  validate its clock, memory, USB, display, touch, RGB, Hall or pinmux paths.
- A narrow successful experiment is not a production updater. Arbitrary image
  parsing, erase planning, power-fail recovery, version policy and safe boot-
  chain update semantics remain separate engineering work.

## Operational consequence

The corrected CDB model is no longer static-only for the tested path. Repeating
this destructive marker cycle merely to reconfirm it is unnecessary. Further
USB write work should build on the confirmed `F6 18`/`F6 06`/`F6 15` semantics
while retaining full-image verification and an external-SPI recovery path.

External SPI remains the supported owner-recovery and ordinary write method.
The replacement firmware remains `flash_approved=false` until its independent
hardware gates are satisfied.
