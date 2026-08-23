# KB7 USB-ISP write-path validation plan

Status: **completed successfully once on hardware on 2026-08-23**. The exact
program post-image and exact restoration to the 32-MiB baseline both passed.

`kb7-isp-write2.py` is a destructive laboratory validator, not a supported
flasher. It is dry-run by default. Its purpose is to validate the loader's
`F6 15` erase implementation on one recoverable development keyboard; it is not
an installation route for end users.

The procedure below is retained as the reviewed experiment and recovery
runbook, not as an invitation to repeat a now-settled destructive test.

## Preconditions

Do not run a committed stage unless all of these are true:

- two independent external-SPI reads of this keyboard are byte-identical and
  retained separately;
- a complete SPI write and exact readback have been rehearsed with the same
  programmer, wiring, reset hold, and baseline image;
- the programmer uses 3.3-V logic, the SoC can be held in reset, and the person
  running the test accepts that recovery may take roughly 30 minutes;
- the keyboard is in `10f5:5037` ISP mode with the external programmer physically
  disconnected; and
- the baseline and state paths are absolute, distinct, and outside the repository.

The script additionally refuses unless the baseline is exactly 32 MiB, has the
expected KB7 header, boot configuration, manifest identity and mappings, and
valid region checksums, and exposes a complete erased 4-KiB sector in the
manifest-derived application-to-assets gap. It compares a fresh full-chip USB
read with that baseline before the first mutation, and independently checks the
connected loader identity. The default target is sector `0x0008e000`; the entire
sector, not merely the 512-byte marker area, must be `0xff`.

## Operator command sequence

Use the same baseline, target, and state path for every invocation:

```sh
# 1. Offline checks and display the program plan; opens no USB device.
sudo python3 tools/flash-access/kb7-isp-write2.py \
  --stage program --offset 0x8e000 \
  --baseline /absolute/path/kb7-baseline.bin \
  --state-file /absolute/path/kb7-write-test-state.json

# 2. Program and verify the marker.
sudo python3 tools/flash-access/kb7-isp-write2.py \
  --stage program --offset 0x8e000 \
  --baseline /absolute/path/kb7-baseline.bin \
  --state-file /absolute/path/kb7-write-test-state.json --commit

# 3. Recheck the saved authorization and display the erase plan; still no USB.
sudo python3 tools/flash-access/kb7-isp-write2.py \
  --stage erase --offset 0x8e000 \
  --baseline /absolute/path/kb7-baseline.bin \
  --state-file /absolute/path/kb7-write-test-state.json

# 4. Erase and verify the marked sector.
sudo python3 tools/flash-access/kb7-isp-write2.py \
  --stage erase --offset 0x8e000 \
  --baseline /absolute/path/kb7-baseline.bin \
  --state-file /absolute/path/kb7-write-test-state.json --commit
```

Stop immediately on any refusal, transport anomaly, timeout, unexpected output,
or exit status other than zero. Do not repeat a mutation after an unknown
result. The erase stage is authorized only by the state written after a fully
verified program stage; a dry run cannot create that authorization.

## Device-command sequence

Both committed stages first check `F6 00` identify and `F6 F1` descriptor. A
full-chip read spans the absolute `0x61000000` boundary, so each preflight and
postflight capture sends `F6 17` and reads all 32 MiB with `F6 05` in transfers
no larger than 4 KiB. The default mutation lies wholly below the boundary, so
the vendor sequence sends `F6 18` before it. This is fixed behavior, not a user
toggle. Verification intentionally covers the settings areas too: the
application is not running in ISP mode, so it cannot create mid-session settings
churn.

The loader is non-standard in one precisely characterized BOT detail. For every
`F6` command, its CSW residue remains equal to the CBW data length even after an
exact successful data phase. The first read-only baseline attempt exposed this
as residue 8 because the old verifier also requested the wrong 8-byte length for
the 2-byte `F6 00` identity. Static loader tracing independently proves both
behaviors. The corrected tools request exactly `01 01` and require residue 2;
they likewise require residue 1 for the one-byte status poll, the exact read or
program length for data commands, and zero for commands with no data phase.
Any other residue, short transfer, tag mismatch, nonzero status, or bad signature
remains fatal. This is exact quirk validation, not a general relaxation.

The 36-byte `F6 F1` response has four uninitialized stack-tail bytes at offsets
28–31. The tool still requires all 36 bytes to transfer, validates the exact
initialized version/device/magic fields, and binds state to those stable fields;
the four undefined bytes are not used as a device fingerprint.

The program stage is:

1. Validate the connected loader with `F6 00` and `F6 F1`.
2. Send `F6 17`, read and exactly match the entire baseline, then validate its
   live manifest and require the whole target sector to be erased.
3. `F6 18`.
4. Send 512 marker bytes with
   `f6 06 00 60 08 e0 00 00 01 00 00 00 00 00 00 00`.
5. Poll `F6 01` until ready, then `F6 17`, read all 32 MiB, and require an exact
   match to `baseline + marker`.
6. Atomically save authorization bound to USB topology, loader fingerprint,
   manifest hash, baseline hash, marker hash, target, and expected programmed
   image hash.

This stage reconfirms the recovered `F6 06` absolute byte address and one-block
length on the chosen scratch sector. The exact postflight comparison also shows
that no other byte differs at the time of the read. It does not prove erase.

The erase stage is:

1. Require the saved static authorization and validate the connected loader
   with `F6 00` and `F6 F1`.
2. Send `F6 17`, read all 32 MiB and require an exact match to `baseline +
   marker`; then revalidate the live manifest, require the full identity-bound
   state to match, and require the sector to be exactly the marker followed by
   `0xff`.
3. `F6 18`, then persist an `erase_started` state before mutation.
4. Send `f6 15 00 04 70 00 00 00 00 00 00 00 00 00 00 00`.
5. Poll `F6 01` until ready, then `F6 17`, read all 32 MiB, and require an exact
   match to the original baseline before clearing the state file.

A pass proves that this loader interpreted `0x0470` as a 512-byte-block index
that affected the marker at offset `0x8e000`, restored the exact baseline, and
did not observably alter any non-`0xff` byte elsewhere. It does **not** prove the
erase granularity: the other 3584 bytes in the target sector and the surrounding
scratch gap were already `0xff`, so erasing only the marker-containing block or
a larger all-erased range would produce the same final image. The block-index
encoding is independent of three-/four-byte NOR address mode. The independent
flash-type selector chooses `F6 15` versus `F6 19`; changing address mode does
not change that selector.

## Remaining failure modes

The guards detect damage after a command; they cannot prevent a defective or
misunderstood device handler from causing it. The material residual risks are:

- an ambiguous USB disconnect, short transfer, failed CSW, busy timeout, power
  loss, or reset after mutation can leave the flash state unknown; the strict
  transport aborts, but cannot undo a command already accepted by the loader;
- static tracing and the completed hardware cycle agree on the loader's non-
  standard CSW residue behavior: data-phase commands returned the exact expected
  requested-length residue and no-data `F6 18`/`F6 15` returned zero. This
  remains another reason not to treat the loader as a general-purpose,
  standards-compliant mass-storage programming transport;
- any further absolute-address program remains destructive even though this
  exact target and one-block encoding have now passed;
- the marker makes the encoded erase target observable but cannot distinguish
  the loader's exact erase granularity inside surrounding bytes that were
  already `0xff`;
- topology path and loader fingerprints strongly bind the two stages but are not
  a cryptographically unique hardware serial number; and
- one successful marker cycle validates only this loader, flash configuration,
  sector, and command size. It does not validate `F6 19`, arbitrary ranges,
  interruption recovery, repeated writes, another firmware version, or a
  production-quality USB updater.

An exact final image proves content at that read, not safe behavior across a
subsequent power cycle. Detection is also not recovery: USB must not be treated
as the rollback path after an anomalous mutation.

## Recovery procedure

On any unknown result or post-mutation mismatch, do not retry over USB. Preserve
the log and state file, power down, attach the proven 3.3-V SPI programmer, and
hold `MCU_RST` low before powering the board. Confirm that only the `10f5:503d`
hub enumerates, so the SoC is not contending for the flash bus. Keep the ESP32
powered whenever its SPI wires are attached.

Restore the exact preflight-matching full-chip baseline, using the programmer
device path established during the recovery rehearsal:

```sh
flashrom -p 'serprog:dev=/dev/ttyACM0:921600,spispeed=1M' \
  -c 'MX25L25635F/MX25L25645G' \
  -w /absolute/path/kb7-baseline.bin --progress

tools/flash-access/kb7-read-1m.sh \
  /absolute/path/kb7-post-restore.bin

sha256sum /absolute/path/kb7-baseline.bin \
  /absolute/path/kb7-post-restore.bin
cmp /absolute/path/kb7-baseline.bin \
  /absolute/path/kb7-post-restore.bin
```

Require flashrom's verification and the independent full-chip read/hash/cmp to
pass. Then power down, physically disconnect the programmer's SPI leads, release
reset, power-cycle, and confirm both normal USB enumeration and normal keyboard
operation. Never leave an unpowered programmer connected to the flash bus.

## Verdict

**The authorized one-time experiment passed. Do not repeat it merely to
reconfirm the same fact.** `F6 18` plus the exact `F6 06`/`F6 15` sequence
programmed and removed the marker at `0x8e000`; both complete postflight images
were exact, and the final image returned byte-for-byte to the baseline. The
dated evidence record is
[`../../docs/USB-ISP-WRITE-VALIDATION-2026-08-23.md`](../../docs/USB-ISP-WRITE-VALIDATION-2026-08-23.md).

The granularity limitation above remains an accurate description of this first
marker cycle. A separate guarded run later populated a complete sector and
immediate guards at `0x000c6000`, establishing an observable exact 4-KiB
footprint at that target. Its evidence is recorded in
[`../../docs/USB-ISP-ERASE-GRANULARITY-VALIDATION-2026-08-23.md`](../../docs/USB-ISP-ERASE-GRANULARITY-VALIDATION-2026-08-23.md).

That result justifies further engineering of a non-invasive updater, not use by
general users. Any new destructive test still requires the full-chip SPI
recovery rehearsal, matching backups and explicit acceptance of losing the
board. External SPI remains the rollback path.
