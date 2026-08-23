# KB7 USB-ISP scratch restart test plan

## Status and purpose

This is the next bounded laboratory experiment after the successful guarded
4-KiB erase-footprint test. It is prepared in source but has **not yet been run
on hardware**.

The experiment asks two narrow questions:

1. Can a fixed sequence program and erase two adjacent scratch sectors while
   exact full-chip checks detect every observable out-of-plan change?
2. After the host deliberately closes a USB session without doing post-readback,
   can a new process classify the command as the exact preimage or exact
   postimage without trusting or replaying the journal?

It is not a firmware updater, power-loss test, generic resume mechanism or
authorization to touch a declared firmware region. `flash_approved` remains
false, and the firmware updater executor remains read-only.

## Fixed geometry

The script accepts no address or payload arguments. It requires the complete
V1.22-aligned envelope `[0x000c0000,0x00100000)` to be `0xff` in two distinct,
byte-identical 32-MiB owner captures.

| Purpose | Flash range |
|---|---:|
| Lower guard block | `0x000c4e00..0x000c4fff` |
| Work sector A | `0x000c5000..0x000c5fff` |
| Work sector B | `0x000c6000..0x000c6fff` |
| Upper guard block | `0x000c7000..0x000c71ff` |

All 18 programmed blocks are deterministic and distinct. Every byte has
exactly one cleared bit, so no programmed byte is already `0xff`. Each program
is one hardware-validated 512-byte `F6 06`; every erase is one aligned `F6 15`.
`F6 18` is sent immediately before every mutation, and WIP is polled to ready.

The four erase CDBs are fixed:

```text
lower guard sector 0xc4000: f6 15 00 06 20 00 00 00 00 00 00 00 00 00 00 00
work sector A      0xc5000: f6 15 00 06 28 00 00 00 00 00 00 00 00 00 00 00
work sector B      0xc6000: f6 15 00 06 30 00 00 00 00 00 00 00 00 00 00 00
upper guard sector 0xc7000: f6 15 00 06 38 00 00 00 00 00 00 00 00 00 00 00
```

The plan hash binds all 18 literal program CDBs and payload hashes, all four
erase CDBs, geometry, sizes, `F6 18`, the preserved-loader hash, and hashes of
the experiment/writer/verifier sources. Tool drift invalidates saved state.
For the reviewed source tree, the plan SHA-256 is
`d784f036e06a972d9688d15c76a41cbd7e90ca806d5ced1aeab5aae16745085b`.
The script prints this value on every dry run; stop if it differs before the
first committed stage. This is a source-consistency binding, not a signature.

## Preconditions

- Keep two distinct, byte-identical fresh 32-MiB USB captures from this unit.
- Retain the proven external-SPI restore path and exact owner baseline.
- Physically disconnect the SPI programmer from the flash bus during USB use;
  never leave it attached and unpowered.
- Enter `10f5:5037` ISP mode and keep the keyboard powered and in ISP until the
  final exact-baseline cleanup completes.
- Do not edit, switch branches, pull, or regenerate any of the three bound
  Python sources while state exists.
- Keep the state file and captures outside the public repository.

The script independently requires the reviewed V1.22 manifest geometry and
pins live flash `[0x1000,0x10000)` to preserved-loader SHA-256
`9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`.

## Exact stages

Set `BASE_A`, `BASE_B` and `STATE` to owner-local absolute paths, then run a
stage once without `--commit` before its committed form.

1. `prepare-a` writes the lower guard and all eight blocks of work sector A.
   Every block receives a complete 32-MiB post-read before the next block.
2. `program-cut` writes the first block of work sector B, polls ready, then
   deliberately closes without readback. Exit status **4 is expected**.
3. `reconcile` in a new Python process reads the whole chip twice. Exact
   postimage advances; exact preimage returns to `prepare_a_verified` without
   retry; anything else exits 3 and requires SPI.
4. `prepare-b` writes work sector B's remaining seven blocks and the upper
   guard, with full-chip verification after each.
5. `erase-cut` erases work sector A, polls ready, then deliberately closes
   without readback. Exit status **4 is expected**.
6. A second `reconcile` performs the same two-read pre/post classification.
7. `erase-b` erases and verifies work sector B.
8. `cleanup-lower` erases and verifies the lower guard sector.
9. `cleanup-upper` erases the upper guard sector, requires the exact original
   32-MiB baseline, and removes the durable state.

The separate invocations are the process/libusb-session restart test. Do
**not** unplug or power-cycle the keyboard between them. A physical power-loss
experiment is not part of this plan.

## State and reconciliation rules

Before every mutation, the script durably writes an exact intent and fsyncs
both the file and its directory. The intent binds the CDB, payload (if any),
source state, exact full-chip preimage and exact full-chip postimage.

An interrupted transfer, CSW anomaly, poll failure, short read, Ctrl-C, or
journal-publish failure leaves the intent unresolved. No mutation stage accepts
that state. `reconcile` is read-only and:

- requires the same topology and stable loader identity;
- requires two byte-identical 32-MiB reads;
- accepts only the intent's exact preimage or exact postimage;
- never automatically retries a command; and
- retains the unresolved state and requires SPI for every other stable image.

The topology is not a unique serial number. The exact full flash image is the
effective device binding.

## Proof boundary

A successful cycle would demonstrate fixed multi-sector sequencing and
image-derived recovery from two intentionally unresolved, command-complete
host sessions on this one unit, loader, mode and address range. It would also
show both patterned work sectors and adjacent guards behaved exactly as
predicted and that cleanup restored the complete baseline.

It would **not** prove:

- recovery from physical power loss during an erase or page program;
- arbitrary torn-NOR states, disturb or repeatable same-path read bugs;
- operation above 16 MiB, `F6 17` mutation mode or `F6 19`;
- arbitrary offsets, payload lengths, loader/flash revisions or devices;
- updater transaction safety in core0/core1 regions;
- custom-firmware correctness or a return to 5037 from custom code; or
- production release authenticity.

## Recovery

If the tool prints `SPI RECOVERY REQUIRED`, or if anything is unclear while
markers remain:

1. issue no more USB mutations;
2. disconnect keyboard power;
3. connect and power the proven 3.3-V SPI programmer while holding `MCU_RST`;
4. take two external reads and compare them for diagnosis; and
5. restore and verify the exact owner baseline using the already demonstrated
   full-chip SPI procedure.

Do not improvise a USB cleanup command for a noncanonical image.
