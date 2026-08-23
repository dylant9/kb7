# Mandatory active-intent checkpoint hardware validation — 2026-08-23

> **Historical v2 hardware result.** It validates plan
> `f0a8acf...ca0e`; it is not a hardware result for the current v3 source. The
> hardware-unrun v3 self-`SIGKILL` checkpoint is specified in the
> [host-termination test plan](USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md).

## Result

The owner completed one end-to-end hardware run of the then-current v2
`kb7-updater-scratch-executor.py` plan on the development KB7. The exact
hash-bound plan was:

```text
f0a8acfcdc7ab5fb7a7dc2753ed8bdca0e381a9433f64fe311348442a8bbdb32
```

The run passed its mandatory boundary-9 active-intent checkpoint, continued
through all remaining fixed scratch operations, restored the exact 32-MiB
baseline, cleared the journal through final read-only reconciliation, and was
followed by an operator-confirmed normal keyboard boot.

This result is deliberately separate from the earlier v1 validation. V1 plan
`491b06c1beb66fa606639e1d420109dcf856c91b50ad02d5fbd0e6bafe1cc797`
proved the same fixed command set at ordinary command boundaries. V2 adds the
mandatory active-intent state transition and mutation-incapable fresh-process
reconciliation described below.

The general paired-firmware executor remains read-only, custom-firmware
mutation remains unavailable, and `flash_approved=false`.

## Observed checkpoint and completion

The fixed checkpoint operation was `program-09`, transitioning the expected
whole-image state from boundary 9 to boundary 10:

| Evidence | Observed result |
|---|---|
| Boundary-9 preimage SHA-256 | `ea8f9c343781027db13ad221a63784fe52e4689f1543f10562ff7504c8b6f7b6` |
| Operation | fixed 512-byte program at `0x000c6000` |
| Checkpoint behavior | program command and strict WIP-ready poll completed; no postread occurred |
| Checkpoint process result | durable intent remained active and the process exited 4 |
| Reconciliation transport | verifier-only USB backend, unable to represent program or erase commands |
| Fresh-process reads | two stable, exact 32-MiB reads |
| Boundary-10 postimage SHA-256 | `f67fb2f28944d13d82ffcc7f15514558c757db0e6e0a0f261866043093afa3e7` |
| Reconciliation result | exact postimage accepted at boundary 10; no automatic retry |

The owner then ran the remaining state-derived operations through boundary 22.
The complete image returned to baseline SHA-256:

```text
2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f
```

Final read-only reconciliation accepted the complete baseline and cleared the
journal. A separate invocation of `kb7-isp-verify.py` read all 32 MiB through
the loader, reproduced the same SHA-256, and reported all three manifest-region
CRCs valid. The owner also confirmed that the KB7 returned to normal operation.

No owner filesystem paths, raw USB transcript, journal, stock image or payload
bytes are retained in this public record.

## What this run proves

For this one development unit, accepted V1.22 loader, exact baseline and tested
v2 plan/checkout, the run demonstrates that:

- the executor can leave its canonical intent durable after the fixed program
  command and WIP-ready poll while deliberately omitting same-process postread;
- the checkpoint process closes and exits 4 without advancing its verified
  boundary;
- a genuinely fresh process using the mutation-incapable verifier backend can
  classify two full-chip reads as the exact boundary-10 postimage;
- reconciliation does not retry the program and can authorize later
  state-derived scratch operations from boundary 10;
- the remaining fixed cleanup returns every loader-visible byte to the exact
  baseline and final reconciliation clears state; and
- the device can return to operator-observed normal operation afterward.

This is **command-complete/no-postread** evidence. The program command and WIP
poll had already completed before the first process closed. Nothing was
physically disconnected or power-cycled at the checkpoint.

## What this run does not prove

The result does not prove behavior under a physical USB interruption, host or
device power loss, a torn NOR program or erase pulse, flash disturb,
device-side misaddressing, unstable cells, or other electrical faults. Both
the executor reconciliation and separate post-cycle verifier invocation read
through the same preserved-loader `F6 05`/SoC flash-controller path; the latter
is a separate entry point, not an electrically independent SPI observation.

The run used `F6 17` for full-chip reads, but it does not cover the `F6 17`
mutation path at or above 16 MiB, any `F6 19` mutation path, firmware-region
writes, another loader or flash revision, another unit, replacement-firmware
correctness, custom-firmware boot, or a general USB updater. External 3.3-V SPI
remains the independent recovery route for future destructive work.

## Status after validation

The v2 scratch executor now has one successful fixed-plan hardware result in
addition to its offline tests. That evidence is intentionally narrow: it
qualifies this exact scratch-only checkpoint flow on the tested unit and does
not authorize broadening its mutation domain or enabling the general
paired-firmware executor.
