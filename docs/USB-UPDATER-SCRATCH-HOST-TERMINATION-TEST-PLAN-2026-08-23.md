# Fixed scratch host-termination test plan — 2026-08-23

## Status

**Implemented and tested offline; not yet run on hardware.** The current v3
`kb7-updater-scratch-executor.py` plan retains the same 18 fixed programs and
four fixed erases as the completed v1 and v2 campaigns. Its defining boundary-9
change is that, after the complete `program-09` BOT exchange has returned with a
validated CSW, the process locally abandons the USB handle, atomically publishes
and reads back `checkpoint_command_complete`, then sends itself `SIGKILL`. It
does not poll flash WIP, read flash, publish boundary 10 or explicitly close USB.
V3 also binds the plan-wide state and failure policy described below.

The canonical v3 plan SHA-256 is:

```text
c1aa9348e74d6d4590b0e9666a9daf83e5544c3b23292b3df217c34038d5b653
```

Its schemas are `kb7-usb-updater-fixed-scratch-plan-v3` and
`kb7-usb-updater-scratch-journal-v3`. The checkpoint policy is
`after_validated_program_csw_before_wip_poll_or_postread`. Signal 9 is fixed in
the plan and its expected shell status is 137. That status is operator-observed
validation evidence; it is not encoded in or recoverable from the journal.

This is a destructive, dry-run-default laboratory harness. It is not a
physical cable-disconnect or power-loss test, does not accept a firmware bundle
or caller-selected mutation, and does not enable the paired-firmware executor.
The general executor remains read-only and `flash_approved=false`.

The v3 descriptor also binds a plan-wide failure policy. Committed preflight
durably publishes `preflight_started` before constructing a backend or opening
USB. Each committed step likewise publishes its raw `intent` before backend
construction or USB. Either state is a consumed one-shot marker: if it remains
visible, every further USB command is prohibited and complete external-SPI
restoration is required. Preflight closes its clean read-only session before it
publishes boundary 0. An ordinary step verifies its exact postimage and closes
strictly before it publishes the next boundary.

The sole mutation-side reconciliation state is exact, read-back
`checkpoint_command_complete` at boundary 9. It authorizes one fresh-process
read-only reconciliation, never replay. The final `complete` state similarly
authorizes one read-only finalization pass. Intermediate `boundary_verified`
states are not reconcilable.

Before either read-only pass opens USB, it must atomically replace its source
with `checkpoint_reconcile_started` or `final_reconcile_started` and read that
state back exactly. A publication error with the exact source still visible
uses exit 4 and permits a fresh-process retry because no USB was opened. Once a
started state is visible, every open, transport, verification or close failure
is terminal external SPI. Exact classification and strict USB close therefore
happen before publishing boundary 10,
`checkpoint_no_effect` or the absent final-journal state. No path permits
automatic replay.

Atomic writes are classified by the exact visible state. If an operation
reports a publication error but the exact target is visible and validates, that
target is normally accepted. Exact checkpoint-command-complete reached through
that error authorizes read-only cleanup only and invalidates the experiment; it
must not be followed by `SIGKILL`. If reconciliation-start publication reports
an error with its exact source retained, exit 4 permits a fresh-process retry
because USB never opened. A final clear error with the journal exactly absent
accepts the safe cleared state.

If an atomic publication or readback cannot be classified in-process, exit 4
authorizes only a fresh `inspect` command. `inspect` validates the local journal
and never opens USB. It can report only a permitted dry run—absent to preflight,
an exact verified boundary to step, or exact command-complete/final-complete to
reconcile—or external SPI. It is not itself USB authority. In particular,
`preflight_started`, raw intent and either reconciliation-started state are
terminal. An ambiguity that later exposes exact checkpoint-command-complete is
cleanup-only and cannot count as a valid termination experiment.

When a session is eligible for a clean close, the harness uses strict close
devices: it checks the `libusb_release_interface` result, attempts kernel-driver
reattachment only after a successful release, checks that result, and always
performs local handle close and context exit. Any release, reattach, local-close
or context-exit failure is exit 3 and requires external-SPI recovery.

The completed v2 command-complete/no-postread campaign is now historical
evidence for the same command set and geometry. Its checkpoint ran later than
v3's: the v2 process first observed WIP ready and then exited normally without
postread. See the
[v2 test plan](USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md)
and [v2 hardware result](USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md).

## Fixed checkpoint

The first nine ordinary steps reach boundary 9. The next step is
unconditionally:

| Field | Fixed value |
|---|---|
| Operation | `program-09` |
| Transition | boundary 9 to expected boundary 10 |
| Flash offset | `0x000c6000` |
| Length | 512 bytes |
| Address mode | complete, strictly validated `F6 18` command first |
| Program CDB | `f6 06 00 60 0c 60 00 00 01 00 00 00 00 00 00 00` |
| Payload SHA-256 | `ed41dcb56145068e569b99ca07c7827889e163f5cccc444b128512da244cf380` |
| Termination point | after exact data-OUT, validated program CSW and durable/read-back `checkpoint_command_complete`; before WIP poll or postread |
| Termination | self-`SIGKILL`, signal 9; expected shell status 137 |
| Termination failure | exit 126; no synthetic status 137; one ready-state cleanup reconciliation only, then SPI restoration |

The program CSW must have the exact mass-storage signature and tag, status
zero, and the V1.22 loader's expected residue of 512. Under the plan-wide
policy, once checkpoint intent is durable, any short CBW, short data-OUT,
missing or malformed CSW, transport error or unexpected residue is an
unclassified BOT transaction. The failure path sends no explicit USB close,
interface reattachment, halt clearing or BOT reset; process teardown reclaims
the local handle. This is an external-SPI stop, not authorization to run USB
reconciliation, and the tool reports recovery-required exit 3.

At the checkpoint, the sequence is exactly:

1. validate the local boundary-9 journal, then atomically publish, `fsync` and
   read back the canonical raw `program-09` intent before backend construction
   or USB;
2. construct the backend, bind the V1.22 loader identity and require two exact
   32-MiB boundary-9 reads;
3. complete and validate `F6 18`;
4. send the exact program CBW and all 512 payload bytes;
5. receive and strictly validate the program CSW;
6. mark the USB handle locally abandoned without release, driver reattachment
   or other explicit close traffic;
7. atomically publish, `fsync` and exactly read back
   `checkpoint_command_complete`;
8. issue no `F6 01` status command and no `F6 05` read; and
9. self-send `SIGKILL` without attempting post-publication diagnostic output.

Once step 1 publishes raw intent, a backend-construction, identity or preimage-
read failure is terminal external SPI. It cannot be retried or reconciled over
USB.

The durable journal publication and readback between CSW and `SIGKILL` are
intentional fallible work and can add filesystem delay. The tested claim is
therefore durable command completion followed by abrupt host-process death,
not immediate post-CSW death and not interruption while flash WIP is known to
be active.

`SIGKILL` bypasses Python exception handlers, `finally` blocks and `atexit`
cleanup. The operating system will reclaim the process's USB handle. That is
the condition under test; a graceful process close is not substituted. If
signal delivery fails or returns unexpectedly, the tool uses exit 126, never a
synthetic 137. The durable command-complete state permits one fresh-process,
read-only cleanup reconciliation after exit 126, but the experiment is invalid:
even an exact postimage must not be followed by `program-10`. Complete the
cleanup read, then restore and verify the baseline over external SPI. A pre-CSW
transport failure leaves raw intent and permits no USB reconciliation.

For the validated owner baseline SHA-256
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`,
the two exact images accepted by reconciliation are:

```text
boundary 9 preimage : ea8f9c343781027db13ad221a63784fe52e4689f1543f10562ff7504c8b6f7b6
boundary 10 postimage: f67fb2f28944d13d82ffcc7f15514558c757db0e6e0a0f261866043093afa3e7
```

A different accepted owner baseline derives different complete-image hashes.
Baselines, journal and live image must remain bound throughout one campaign.

## Fresh-process reconciliation

The checkpoint process cannot return a normal result after `SIGKILL`; shell
status 137 is the expected indication that the fixed termination point was
reached. Keep the keyboard powered and physically connected in `10f5:5037`.
Do not unplug it, power-cycle it, reset it, clear endpoint halts or run a
mass-storage reset.

Start `reconcile --commit` as a genuinely new Python process. It uses the
verifier-only transport with endpoint recovery disabled. That transport cannot
represent `F6 06`, `F6 15`, `F6 18` or a data-OUT program phase. Before it
constructs or opens that backend, it atomically consumes
`checkpoint_command_complete` into `checkpoint_reconcile_started` and reads the
started state back exactly. It then binds the loader identity, performs the
WIP-ready poll omitted by the killed process, and obtains two byte-identical
32-MiB reads. An intermediate verified boundary cannot enter this path.

- Exact postimage records `exact_postimage_completed`, advances to boundary
  10 and permits `program-10` in a later process. The program is never replayed.
- Exact preimage is known and non-corrupt, but it consumes the plan's single
  checkpoint attempt. Reconciliation records `checkpoint_no_effect`, exits 5
  and prohibits every later USB mutation. Use the rehearsed external-SPI path
  to restore and verify the owner baseline before normal boot or another
  campaign.
- A stable image other than the exact preimage or postimage requires external
  SPI recovery.
- If reconciliation-start publication reports an error and the exact
  `checkpoint_command_complete` source remains visible, no USB was opened;
  exit 4 permits one fresh-process retry. A normally confirmed exact started
  state proceeds. If a reported publication error leaves exact started state
  visible, the one-shot attempt is consumed and external SPI is required; an
  unclassifiable state permits only local inspection.
- Once `checkpoint_reconcile_started` is durable, a backend/open, poll,
  identity, short-read, unstable-read, exact-verification or USB-close failure
  is recovery-required exit 3. Before safe exact classification, the backend
  sends no explicit close or reattachment traffic. Do not retry USB
  reconciliation; recover and verify the complete baseline over external SPI.
- After exact classification, strict USB close must succeed before the tool
  publishes boundary 10 or `checkpoint_no_effect`. A final-publication error is
  accepted only when the exact target is visible and validates; a retained
  started state or any third state is terminal external SPI.

Successful fresh-process polling means only that flash was ready before
readback. The present interface does not record whether WIP was observed busy,
so it cannot establish that the NOR was actively programming when `SIGKILL`
arrived.

## Hardware sequence

Any separately authorized run must use two fresh, distinct and byte-identical
owner captures, the reviewed V1.22 loader, the erased
`[0x000c0000,0x00100000)` containment envelope and a new owner-local v3 journal.
Keep the rehearsed 3.3-V SPI recovery path immediately available, but
physically disconnect every programmer from the flash bus during USB use.

1. Run the complete repository checks. Run a dry preflight and require plan
   SHA-256
   `c1aa9348e74d6d4590b0e9666a9daf83e5544c3b23292b3df217c34038d5b653`.
2. Run committed read-only preflight. It must establish exact boundary 0 and
   create the new v3 journal. It publishes `preflight_started` before opening
   USB, then closes USB strictly before publishing boundary 0.
3. Run nine separate committed steps. They must complete only `program-00`
   through `program-08` and leave boundary 9 verified. Each publishes raw intent
   before opening USB, then closes strictly before publishing its verified
   boundary. An exit-3 anomaly on any step is an immediate external-SPI stop,
   not permission to reconcile over USB.
4. Run a dry step. It must identify `program-09` and print the mandatory
   `after_validated_program_csw_before_wip_poll_or_postread` policy.
5. Run the committed checkpoint step. It must be killed with shell status 137
   and must not print a normal result object. Before the signal it durably
   records `checkpoint_command_complete`; it deliberately emits no diagnostic
   after that publication because terminal output could block at the tested
   boundary. Without opening another mass-storage session, confirm from the
   existing sysfs topology that `10f5:5037` remains enumerated and that neither
   USB nor keyboard power was interrupted.
6. Start a new process and run dry reconciliation, then committed
   reconciliation. This is allowed after the planned status-137 path only when
   the journal is exactly `checkpoint_command_complete`, never from raw intent.
   The commit must consume `checkpoint_reconcile_started` before USB opens.
   Exact postimage and boundary 10 are the expected successful continuation.
   Exit 5 or any other outcome is a mandatory stop; exit 5 requires full
   external-SPI baseline restoration.
7. After exact postimage only, run the remaining twelve state-derived steps,
   `program-10` through `erase-upper-guard`, one process at a time. Boundary 22
   must equal the original 32-MiB baseline. The same exit-3 stop policy applies
   to every command, poll, postread and exact-verification phase.
8. Run final read-only reconciliation from another process. It must atomically
   consume `complete` into `final_reconcile_started` before USB opens, verify
   the exact baseline twice, close USB strictly, and clear the journal.
9. Use the separate read-only verifier for a final full-chip capture and exact
   comparison. Only then power-cycle and confirm normal `10f5:5038` operation.

If the checkpoint instead returns status 126 or exit 4 with exact
`checkpoint_command_complete` visible, use its sole reconciliation only for
safe read-only cleanup, then restore the baseline over SPI; do not continue at
`program-10` even if cleanup reports the exact postimage. Do not automate past
status 137, exit 5 or any unexpected result. Preserve the complete console
output outside this public repository.

Any `STATE INSPECTION REQUIRED` / exit-4 ambiguity authorizes only this local
command in a fresh process:

```sh
python3 tools/flash-access/kb7-updater-scratch-executor.py inspect \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --journal /path/to/owner-local-scratch-journal.json
```

Do not add `--commit`; `inspect` has no such option and never opens USB. Follow
only its reported dry-run or external-SPI action. If it cannot validate an exact
known state, use external SPI.

## Stop and recovery rules

- Status 137 is expected only at the fixed boundary-9 checkpoint. The only
  next command is fresh-process, read-only reconciliation from exact
  `checkpoint_command_complete`.
- `preflight_started`, raw `intent` at any index, and either
  `*_reconcile_started` state are terminal external SPI. They are consumed
  one-shot markers and never authorize another USB session.
- On every ordinary operation, any command, WIP-poll, postread,
  exact-verification or close failure after raw intent is durable is an exit-3
  terminal outcome. The process must not explicitly close or reattach after a
  transport/verification anomaly. Do not run `step`, USB
  reconciliation, halt clearing or BOT reset; use external SPI to restore and
  verify the complete baseline.
- A mutation-session close failure after safe exact verification is also exit 3
  and requires complete external-SPI restoration; journal state does not
  authorize another USB probe.
- Exit 4 has two explicit forms. `STATE INSPECTION REQUIRED` authorizes only
  fresh-process local `inspect`, never USB. `RECONCILIATION REQUIRED` permits
  only the stated fresh read-only action. It can mean that `step` was invoked
  while exact checkpoint-command-complete was already present, that
  reconciliation-start publication retained its exact source before USB, or
  that exact checkpoint-command-complete became visible after a reported ready-
  publication error. The last case is cleanup-only and invalidates the
  experiment.
- Any backend/open, identity, WIP-poll, read, exact-classification or close
  anomaly after a reconciliation-started state is durable is exit 3. A final-
  publication anomaly follows the atomic-state rule below: accept only an exact
  target, require SPI for an exact terminal source, and use local-only
  inspection when the visible state cannot be classified. Do not start a
  second USB reconciliation attempt.
- A reported publication error whose exact safe target is visible is accepted
  where the stage policy says so. A final clear error with the journal exactly
  absent is likewise accepted. An exact terminal source requires SPI; an
  unclassifiable result requires local-only inspection, not a USB probe.
- Intermediate `boundary_verified` states are not reconcilable; the only
  permitted actions are the next fixed `step` or stopping without more USB.
- Exit 126 means the planned self-`SIGKILL` could not be delivered as specified
  or returned unexpectedly. It is not validation evidence. Exact
  `checkpoint_command_complete` authorizes its one read-only cleanup
  reconciliation, but no continuation: restore the complete baseline over SPI
  even if cleanup observes boundary 10.
- Any other checkpoint status is unexpected. Do not rerun `step`; preserve the
  journal and stop for review.
- Exit 5 is an exact preimage, not observed corruption, but the checkpoint is
  consumed. Restore and verify the complete owner baseline over the rehearsed
  external-SPI path before normal boot or another campaign.
- Do not use an external `kill -9`; the tool's self-signal is sequenced after
  strict CSW validation. An external signal has no trustworthy phase.
- If reconciliation reports neither exact image, stop USB activity, remove
  keyboard power, attach and power the proven 3.3-V SPI programmer while
  holding the SoC off the bus, take two diagnostic reads, and restore and
  verify the complete owner baseline.
- Never leave an ESP32 or other programmer wired to the flash while it is
  unpowered.

## What must not be attempted in this revision

V3 does not authorize a physical USB disconnect, device or host power cut,
partial CBW or data transfer, unread CSW, endpoint halt clearing, BOT reset,
kernel-driver rebind, `usbreset`, `uhubctl`, sysfs power control, erase
interruption or an externally timed signal. An incomplete BOT transaction needs
a separately proven, VBUS-preserving reset/re-enumeration path before it can be
tested safely.

It also does not authorize another checkpoint index, arbitrary address, CDB,
payload, length, retry, `F6 17` mutation, `F6 19`, another loader/flash revision,
firmware-region writes or general-updater execution.

## Proof boundary

If the hardware-unrun v3 checkpoint later reconciles to its exact postimage and
the fixed cleanup restores the baseline, it will demonstrate on that one unit
that:

- the complete valid program BOT transaction and CSW finished before abrupt
  userspace death;
- `checkpoint_command_complete` was durably published and read back after CSW,
  then no WIP poll, flash readback, boundary advance or explicit USB close
  occurred in the terminated process;
- a fresh process could poll ready, classify the exact flash state without
  replay, and continue the fixed scratch transaction; and
- cleanup returned every loader-visible byte to the owner baseline.

It will not prove that WIP was active at termination—the journal `fsync` and
readback add an unmeasured delay after CSW—or that `SIGKILL` interrupted a NOR
program pulse. It will not prove that a physical disconnect or power loss is
safe, that a torn program/erase is recoverable, or that pre-CSW BOT recovery
works. It does not generalize to firmware regions, another device or a
production updater.

Both reconciliation and the final verifier still read through the same
preserved-loader/SoC `F6 05` path. External SPI remains the independent
verification and recovery route.
