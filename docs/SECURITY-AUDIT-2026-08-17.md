# Firmware security and release-readiness audit

Audit date: 2026-08-17
Method: three independent read-only source/artifact audits, reconciled with
clean-room builds, ELF comparisons, static checks, and unit tests
Hardware access: none

> Historical baseline: this document records the defects found in the earlier
> skeleton. Their current implementation status is in
> `FIRMWARE-COMPLETION-2026-08-18.md`; do not interpret the old stub inventory
> below as a description of the current tree.

## Verdict

The audited independent replacement firmware was an engineering skeleton, not
safe or functional enough to flash. It must remain non-flashable. A structurally
valid checksum did not imply correct or recoverable behavior.

The earlier feasibility conclusion was not overturned: low-level LCD behavior
was present in the supplied application flash rather than exclusively in SoC
mask ROM. The replacement implementation nevertheless failed to reproduce that
behavior correctly.

For public release, all generated images and stock-patch tooling were excluded;
bundle generation was disabled; and the panel, RGB, and USB hardware profiles
were replaced by fail-closed stubs. The remaining source is still not approved
for device installation.

The actionable source findings have since been incorporated with fail-closed
hardware boundaries and host-side regression tests. See
`AUDIT-REMEDIATION-2026-08-17.md` for the finding-by-finding status. This does
not change the non-flashable verdict. A later external-SPI full-stock
restore/verification rehearsal established the development unit's rollback
path, but the required replacement-firmware hardware profiles remain
unavailable; see `FULL-FLASH-ACQUISITION-2026-08-22.md` and
`USB-ISP-WRITE-VALIDATION-2026-08-23.md`. A subsequent guarded footprint run is
recorded separately in `USB-ISP-ERASE-GRANULARITY-VALIDATION-2026-08-23.md`;
it validates one stock-loader erase boundary, not replacement firmware.

A later offline-only V1.22 planner addresses the single-manifest power-loss
hazard by leaving that manifest byte-exact, CRC-balancing paired replacement
regions and checking an invalidate/stage/sparse-gate transaction model. It also
adds a symmetric runtime pair-ID/ABI guard. This is a software design result,
not board validation or a live firmware-mutation path. A later paired-firmware
executor scaffold adds only read-only live preflight/reconciliation and
fake-transport fault injection; its mutation adapter remains hard-disabled. A
distinct dry-run-default scratch executor wires only the fixed 22-operation
V1.22 scratch plan and accepts no firmware bundle or caller-selected operation.
Its v1 plan completed once on the development unit with exact final baseline
restoration and an operator-reported return to normal keyboard operation. The
current v2 plan has also completed once. Its fixed active-intent checkpoint
followed `program-09` and WIP-ready polling, before postread; the process exited
4 and a fresh process with a mutation-incapable backend classified two full-chip
reads as the exact postimage without retry. The plan then restored the baseline,
cleared state, passed all three region CRCs in a separate verifier invocation,
and returned to operator-reported normal operation. Both runs stayed outside all
firmware regions; neither physically interrupted a command or tested power loss,
and neither unlocks the paired executor. See
`USB-UPDATER-OFFLINE-DESIGN-2026-08-23.md` and
`USB-UPDATER-EXECUTOR-SCAFFOLD-2026-08-23.md`, plus
`USB-UPDATER-SCRATCH-EXECUTOR-2026-08-23.md` and
`USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md`; the v1 result is in
`USB-UPDATER-SCRATCH-EXECUTOR-VALIDATION-2026-08-23.md` and the v2 result is in
`USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md`.

The full SNC7320 datasheet review on 2026-08-18 added a critical correction:
AIRCR/software reset restarts PRAM, not mask ROM. The former mailbox-marker plus
software-reset helper therefore did not prove entry to the preserved loader.
The public helper now parks for external reset; see `BOOT-RECOVERY-MODEL.md`.

## Critical and high-severity findings

1. **Clock ROM return semantics were inverted.** `drivers/clock.c` treated two
   reference fatal-return sentinels as success, omitted a reference divider
   calculation, and core0 continued boot after failure.

2. **USB was not an enumerating stack.** The pre-remediation source marked
   USB ready without an EP0 state machine, descriptor-request handling, OUT
   dispatch, or IN submission; sends always failed. Its emitted report IDs and
   lengths also disagreed with its descriptor.

3. **Valid Hall frames were rejected.** `drivers/mcu2.c` applied the request
   trailer rule to response sample bytes, causing ordinary A3 sample frames to
   fail validation.

4. **The physical-key-to-HID map was absent.** `core1/main.c` used sensor selector
   indices directly as HID usages and always emitted zero modifier bits.

5. **The core0 vector table was too short.** It contained 64 words while the
   reference hardware contract used entries through vector index 72. Higher IRQs
   could interpret instruction words as handler addresses.

6. **Timeout loops failed open.** Post-decrement conditions in MCU2, RGB, LCD,
   USB, and optional DRAM paths wrapped zero to `UINT32_MAX`; actual timeouts could
   proceed as success. The DRAM path could then enter a destructive memory test.

7. **Panel ordering and timing were wrong.** Two commands preceded a delay that
   the reference sequence placed before them, and raw CPU loops replaced the
   reference tick-based 100/120/20 delays.

8. **Key/media releases and interactive UI state were missing.** Actions emitted
   presses without releases; touch move/up was not dispatched; sliders and
   toggles reused immutable values.

9. **A/B storage did not provide corruption fallback.** Selection considered
   header CRC before payload validity, so a corrupt newer payload hid an older
   valid slot and could cause the updater to erase the surviving copy.

10. **The C parser and host server diverged from their canonical models.** The
    C parser accepted unknown actions, reserved-field values, noncanonical
    layouts, and duplicate/range cases rejected by Python. Several documented
    host operations and status distinctions were absent.

11. **Unvalidated buses were actively driven.** MCU2/RGB bring-up was invoked
    despite a passive-validation requirement. Touch I²C drove SCL high rather
    than releasing it open-drain, preventing clock stretching and risking
    contention.

12. **A validly checksummed bad core0 had no proven recovery route.** The loader
    protects against invalid checksums, not early faults in accepted firmware.
    The recovery chord ran after unsafe clock code, fault handlers slept forever,
    and USB recovery was unavailable.

13. **Software reset was incorrectly treated as loader entry.** The later
    datasheet review proved that it restarts PRAM. A ROM-entering watchdog,
    remap, external reset, or direct programmer path is still required.

## Release-pipeline findings

- Auditors checked ELF structure and binary structure separately but did not
  prove that a binary was generated from its accompanying ELF. Deliberately
  substituted test binaries still received an offline pass.
- Header changes did not trigger recompilation because Makefile dependency files
  were missing. The public Makefile now uses `-MMD -MP`.
- Only one application region was hash-pinned; recovery-critical inputs were not
  anchored to known-good values.
- A flash plan could be empty and still pass, and bounded bundles had no plan at
  all despite runbook requirements.
- The RGB experiment used a stale configuration transaction rather than the
  later-characterized PWM packet.
- The LCD test calculated eight bars across the full memory stride, leaving only
  roughly two visible across the active width.
- Output names were not confined to the requested output directory.

## Verified positive properties

- Clean replacement core0/core1 builds completed with no unresolved relocations.
- All six bounded build experiments passed structural confinement checks; no
  generated artifacts are distributed here.
- Locally generated ELF extraction matched every corresponding local payload.
- Region lengths, erased-byte padding, checksums, and bundle containment were
  internally consistent.
- Eight package tests and twenty PC-application tests passed.
- Additional GCC analyzer, conversion, alignment, and stack-usage checks found
  no new compiler-detectable defect; direct stack frames were modest.
- Parser range arithmetic appeared bounds-safe despite its contract mismatch.
- DRAM training and NOR mutation were disabled by default.
- No hardware was accessed, flashed, or represented as validated.

## Required remediation order

1. Correct clock semantics, vector capacity, fail-closed boot policy, and every
   timeout loop.
2. Implement and test a real EP0/USB endpoint lifecycle with coherent HID
   descriptors and reports.
3. Correct MCU2 response validation and introduce a reviewed logical HID map.
4. Reproduce panel timing only from a redistributable, hardware-validated
   profile.
5. Repair storage fallback, parser parity, host protocol conformance, and UI
   press/release/state handling.
6. Prove an external recovery route and full backup/restore, then prove a
   ROM-entering reset/loader route, before any hardware test of an independent
   core0.
