# Fixed scratch executor hardware validation — 2026-08-23

> **Historical v1 evidence.** This record applies to fixed-plan SHA-256
> `491b06c1beb66fa606639e1d420109dcf856c91b50ad02d5fbd0e6bafe1cc797`
> and the source revision used for that run. The current v3 executor makes a
> boundary-9 durable-command-complete/pre-WIP self-termination checkpoint and
> has a
> different plan and journal schema; it subsequently completed its own hardware
> run. V2 also completed its own hardware run; see the historical
> [mandatory-checkpoint test plan](USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md)
> and [v2 validation record](USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md).
> The current experiment is specified in the
> [v3 host-termination plan](USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md)
> and its [validation record](USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md).

## Result

The owner completed one end-to-end hardware run of
`tools/flash-access/kb7-updater-scratch-executor.py` on the development KB7 in
USB-ISP mode. The fixed 22-operation transaction reached every journal boundary,
restored the complete 32-MiB baseline, completed its required final read-only
reconciliation in a new process, and cleared its journal. A subsequent capture
through the separate read-only verifier matched the baseline byte-for-byte, and
the owner reported that the keyboard returned to normal operation and worked
normally after power cycling.

This is one successful run on one V1.22 unit with the reviewed loader. It
validates the fixed scratch executor's command-boundary orchestration on that
unit. It does not authorize firmware-region mutation or make the project a
supported USB updater. The paired-firmware executor remains mutation-locked and
the replacement firmware remains `flash_approved=false`.

## Bound inputs

The committed preflight accepted only these reviewed inputs:

- fixed-plan SHA-256:
  `491b06c1beb66fa606639e1d420109dcf856c91b50ad02d5fbd0e6bafe1cc797`;
- complete baseline SHA-256:
  `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`;
- preserved-loader SHA-256:
  `9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`;
- stock V1.22 image with `SN_FWIN` manifest header version `v1.0.00`; and
- erased, non-firmware containment envelope
  `[0x000c0000,0x00100000)`.

The observed USB topology was `3-2.2`. That path is session evidence, not a
unique device identity. Preflight obtained two stable exact 32-MiB reads,
classified boundary 0 as `exact_stock_or_complete`, and selected only the
immutable plan's first operation, `program-00`.

## Completed sequence

The owner then ran each state-derived step as a separate Python process. The
executor issued exactly the plan's 18 one-block `F6 06` programs and four
4-KiB `F6 15` erases. Every mutation was preceded by `F6 18`; no address, CDB,
payload, operation or retry was selected by the caller. Each successful step
required two exact full-chip reads at its preimage and two more at its
postimage before advancing the durable journal.

The first operation reached boundary 1 with classification
`exact_scratch_boundary` and complete-image SHA-256
`53f814866c911da26f9eac26e5a07d86898b6c269efde6a46f0e31bb6ce1dbb7`.
The remaining 21 fresh-process steps completed without a reported stop. The
last operation, `erase-upper-guard`, reached boundary 22 with classification
`exact_baseline_restored_pending_finalize`; its observed complete-image hash
was the original baseline hash:

```text
2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f
```

The required final `reconcile --commit` ran in another process. It was read-only,
obtained two more stable complete reads, classified
`exact_stock_or_complete` at boundary 22, reproduced the baseline hash, and
reported `state_cleared=true`. No uncertain intent occurred, so this run did
not exercise the non-final preimage/postimage reconciliation branch or an
automatic retry; automatic retry remained disabled throughout.

## Separate post-cycle verifier entry point

After final reconciliation, the owner ran `kb7-isp-verify.py --full-chip`. This
is a separate program entry point, but it still reads through the same
preserved USB loader's `F6 05` path and the SoC's own flash controller. It is
therefore not an independent electrical/SPI measurement.

The verifier read all 33,554,432 bytes and reported all manifest region CRCs as
valid:

| Region | Declared | Computed | Result |
|---:|---:|---:|---|
| 0 | `0xc3f43a6f` | `0xc3f43a6f` | pass |
| 1 | `0xc8ed2815` | `0xc8ed2815` | pass |
| 2 | `0xaa83e9a3` | `0xaa83e9a3` | pass |

The saved verifier capture had SHA-256
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`
and compared byte-identically with the pre-run baseline. The binary capture and
terminal log remain owner-local and are not part of this public source tree.

The owner subsequently reported a normal working keyboard after the power
cycle. That boot/function result is operator-reported; no post-cycle enumeration
transcript was committed, and it is not an independent board-validation
campaign.

## Exact evidence boundary

This run establishes, for this unit, loader and fixed scratch plan:

- the scratch executor's live identity and exact-baseline preflight path;
- 22 journal-derived, one-operation-per-process command-boundary transitions;
- exact two-read preimage and two-read postimage acceptance at every completed
  step;
- durable progression through all 22 boundaries without caller-selected
  mutation parameters;
- finalization only after a new-process, two-read, read-only reconciliation;
- exact complete-array restoration as observed by both executor and verifier
  entry points; and
- a subsequent operator-reported normal boot and keyboard operation.

It does **not** establish:

- behavior after a physical disconnect during CBW, data, CSW or WIP polling;
- behavior after power loss during a NOR program or erase pulse;
- classification or recovery of a physically torn, disturbed or misaddressed
  command;
- an independent flash measurement, because all USB reads used the same loader
  and SoC controller;
- `F6 17`, `F6 19`, another loader revision, another unit or arbitrary
  addresses;
- any program or erase inside a declared firmware region;
- replacement-firmware correctness, cold-start safety or a supported updater;
  or
- permission to enable the paired-firmware executor's mutation backend.

External 3.3-V SPI remains the independent recovery and bit-level verification
path. A future physical-interruption experiment must retain that recovery path,
must remain confined to reviewed scratch space, and must not be represented as
firmware-update authorization. The paired-firmware executor remains read-only,
and `flash_approved` remains false.
