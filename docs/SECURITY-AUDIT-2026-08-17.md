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
historical v2 plan also completed once. Its fixed active-intent checkpoint
followed `program-09` and WIP-ready polling, before postread; the process exited
4 and a fresh process with a mutation-incapable backend classified two full-chip
reads as the exact postimage without retry. The plan then restored the baseline,
cleared state, passed all three region CRCs in a separate verifier invocation,
and returned to operator-reported normal operation. The current v3 plan has
also completed once. It self-terminates with signal 9/status 137 after validated
program CSW and durable/read-back command-complete state, before WIP polling,
postread or explicit USB close. Preflight-started and raw-intent markers are
published before backend construction or USB and are terminal if left visible.
Only exact command-complete and final-complete states are reconcilable; each
consumes a one-shot started state before USB and closes strictly before final
publication. Atomic ambiguity permits only local inspection, never USB. Status
137 is operator-observed, not journal-bound; status 126 permits cleanup only and
does not validate continuation. The observed v3 run produced status 137,
reconciled the exact postimage in a fresh read-only process without replay,
restored and cleared the exact baseline, passed all three region CRCs and
returned to operator-confirmed normal `5038` keyboard operation.
All plans stay outside firmware regions; none physically interrupts a command
or flash pulse or tests device power loss, and none unlocks the paired executor.
See `USB-UPDATER-OFFLINE-DESIGN-2026-08-23.md`,
`USB-UPDATER-EXECUTOR-SCAFFOLD-2026-08-23.md`,
`USB-UPDATER-SCRATCH-EXECUTOR-2026-08-23.md` and
`USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md` and
`USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md`. The historical
v2 plan is in `USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md`; the
v1 result is in `USB-UPDATER-SCRATCH-EXECUTOR-VALIDATION-2026-08-23.md`, and the
v2 result is in
`USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md`.

A later offline-only Ed25519 tool closes the mechanical publisher-
authentication gap without changing the execution boundary: it re-runs the
complete planner verifier, binds every bundle file and false authorization
flag, and requires a separately pinned public-key fingerprint. No project key
or trust root is provisioned, so no signed release exists. The remaining board
gates now have a staged powered-off/passive-first plan in
`BOARD-VALIDATION-PLAN-2026-08-23.md`; it authorizes no firmware write.

The full SNC7320 datasheet review on 2026-08-18 added a critical correction:
AIRCR/software reset restarts PRAM, not mask ROM. The former mailbox-marker plus
software-reset helper therefore did not prove entry to the preserved loader.
The public helper consequently changed to marker-and-park. That historical
finding remains correct: marker plus AIRCR alone is not loader entry.

A later hash-pinned audit recovered the missing stock operations. V1.22, V1.24
and V1.33 copy a small routine to SRAM; that routine replaces PRAM with the
preserved loader before AIRCR reset, after which the loader consumes the
marker. The stock route is now statically proved, and an independently authored
default-off proof profile passes offline. It has not run on hardware, so it
does not change this audit's no-install verdict or unlock the general firmware
executor. See the
[stock loader-reentry proof](STOCK-LOADER-REENTRY-2026-08-23.md) and
[boot/recovery model](BOOT-RECOVERY-MODEL.md).

A later fixed campaign closes the remaining offline orchestration gap without
enabling hardware. It builds a checksum-valid proof Core 0 while retaining
exact stock Core 1, uses one temporary Core-1 sector poison as the independent
barrier during Core-0 rebuild, and derives the reverse exact-stock sequence.
Its separate executor persists terminal state before every USB open, permits
one internally derived mutation per CLI invocation, requires two exact
full-chip pre/post reads and strict close-before-publication, and has no USB
reconciliation for an ordinary intent. The supporting sources/policy are
pinned, and two exact owner baselines now independently reproduce the pinned
168-operation campaign ID and both stable targets. Later evidence found a
separately SPI-confirmed two-byte physical corruption and, after restoration, a
command-aligned USB acquisition failure. Both proof preflight and mutation are
relocked pending the fixed baseline-aware short-read gate. This is not a
reduction in the hardware
severity of finding 12. See the
[fixed proof campaign](LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md) and
[read-reliability incident](USB-ISP-READ-RELIABILITY-INCIDENT-2026-08-31.md).

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

12. **At audit time, a validly checksummed bad core0 had no proven recovery
    route.** The loader protects against invalid checksums, not early faults in
    accepted firmware. The recovery chord ran after unsafe clock code, fault
    handlers slept forever, and USB recovery was unavailable. The later static
    loader-reentry result supplies a viable early-stage design, and the later
    fixed install/restore campaign supplies a fail-closed offline test route.
    Its custom proof is still hardware-unrun. Later physical-corruption and USB
    acquisition evidence has relocked both proof preflight and mutation pending
    the fixed read-reliability gate.

13. **Software reset was incorrectly treated as loader entry.** The later
    datasheet review proved that it restarts PRAM. The subsequent stock audit
    did not reverse that fact: it proved that stock first copies the preserved
    loader into PRAM from SRAM and only then resets. External SPI remains the
    final independent fallback.

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
   loader route before any general hardware test of an independent core0. The
   external-SPI half is complete; the later relocation route is complete
   offline but still awaits its bounded custom-proof hardware run.
