# Fixed scratch executor status and test plan — 2026-08-23

## Status

The repository contains a separate, deliberately narrow USB mutation harness:

```text
tools/flash-access/kb7-updater-scratch-executor.py
```

It is **dry-run by default**, is restricted to the reviewed V1.22 loader and
scratch layout, and can replay only the 22 operations listed below. The current
v3 source and fake-transport tests pass offline, but v3 has **not** run on
hardware. Its mandatory checkpoint completes the fixed `program-09` CBW,
512-byte data-OUT and strictly validated CSW, locally abandons USB, atomically
publishes and reads back `checkpoint_command_complete`, then self-terminates
with `SIGKILL` before WIP polling, postread, boundary-10 publication or explicit
USB close. Only a fresh-process, mutation-incapable backend may consume that
ready state, poll ready and classify the result.

The preceding v1 plan, SHA-256
`491b06c1beb66fa606639e1d420109dcf856c91b50ad02d5fbd0e6bafe1cc797`,
completed one hardware cycle, restored the exact baseline and returned to
operator-reported normal keyboard operation. That result remains historical
evidence for the unchanged commands and geometry; it is not a hardware result
for the current v3 state machine. The historical v2 plan, SHA-256
`f0a8acfcdc7ab5fb7a7dc2753ed8bdca0e381a9433f64fe311348442a8bbdb32`,
also completed once: it terminated gracefully only after WIP was ready and
fresh-process reconciliation accepted its exact postimage. See the
[historical validation record](USB-UPDATER-SCRATCH-EXECUTOR-VALIDATION-2026-08-23.md)
and the separate
[v2 checkpoint test plan](USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md)
and [v2 validation record](USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md).
The current checkpoint is specified in the
[v3 host-termination test plan](USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md).

The current canonical v3 descriptor has SHA-256
`c1aa9348e74d6d4590b0e9666a9daf83e5544c3b23292b3df217c34038d5b653`.
It includes the mandatory checkpoint index, command, signal-9 termination and
stop policy. The v3
journal binds that plan plus the scratch-plan, writer, verifier and executor
source hashes, so implementation or policy drift fails closed between
invocations.

This is not the paired-firmware updater. The general
`kb7-updater-executor.py` command line still exposes only read-only `preflight`
and `reconcile`, its mutation adapter remains hard-disabled, and firmware-region
mutation remains unavailable. The scratch harness accepts no bundle, operation,
address, length, CDB, payload, device selector, retry, force or skip option.
Neither the historical runs nor the current hardware-unrun scratch-only revision
changes `flash_approved=false`.

## Fixed operation domain

All mutations remain inside the erased V1.22 containment envelope
`[0x000c0000,0x00100000)`. Programs are exactly one 512-byte block using
`F6 06`; erases are exactly one 4-KiB sector using `F6 15`. Every mutation is
preceded immediately by the sub-16-MiB `F6 18` address-mode command. Every
ordinary step follows with the strict WIP poll; at index 9 the mandatory fresh
reconciliation process performs that poll instead. The plan is:

| Index | Action | Offset(s) | Fixed content |
|---:|---|---|---|
| 0 | program | `0x000c4e00` | deterministic pattern slot 0, lower guard |
| 1–8 | program | `0x000c5000..0x000c5e00`, step `0x200` | pattern slots 1–8, work sector A |
| 9 | program | `0x000c6000` | pattern slot 9; mandatory durable `checkpoint_command_complete` and self-`SIGKILL` after validated CSW, before WIP poll/postread |
| 10–16 | program | `0x000c6200..0x000c6e00`, step `0x200` | pattern slots 10–16, remainder of work sector B |
| 17 | program | `0x000c7000` | pattern slot 17, upper guard |
| 18 | erase | `0x000c5000` | work sector A |
| 19 | erase | `0x000c6000` | work sector B |
| 20 | erase | `0x000c4000` | sector containing the lower guard |
| 21 | erase | `0x000c7000` | sector containing the upper guard; restores the exact baseline |

For a program at offset `O`, the canonical 16-byte CDB is
`f6 06 00 BE32(0x60000000 + O) 00 01 00 00 00 00 00 00 00`; its payload is
the corresponding deterministic 512-byte pattern from the fixed source plan.
The four erase CDBs, in order, are:

```text
f6 15 00 06 28 00 00 00 00 00 00 00 00 00 00 00
f6 15 00 06 30 00 00 00 00 00 00 00 00 00 00 00
f6 15 00 06 20 00 00 00 00 00 00 00 00 00 00 00
f6 15 00 06 38 00 00 00 00 00 00 00 00 00 00 00
```

The tool recomputes and checks the exact CDBs, payload hashes,
manifest-derived scratch range, erased sectors, the reviewed imported-plan and
source hash, the fixed executor descriptor, and every expected whole-image
boundary before it can open USB. The executor's own full source hash is then
recorded by read-only preflight and must match on every later invocation.

## Per-operation protocol

`preflight --commit` is read-only. It uses the verifier transport whose command
whitelist cannot represent a flash program or erase. It requires two distinct,
byte-identical, exactly 32-MiB owner captures; checks the reviewed loader, V1.22
manifest and erased scratch envelope; and creates a new owner-local scratch
journal. Before constructing its backend or opening USB it durably publishes
`preflight_started`. It then obtains two stable full-chip reads equal to the
baseline, closes USB strictly, and only then publishes verified boundary 0.
Visible `preflight_started` is terminal external SPI.

Each separate `step --commit` invocation then:

1. acquires a persistent, nonblocking sibling lockfile, then reloads and
   validates the complete fixed transaction and journal;
2. durably records one raw operation intent using file `fsync`, atomic
   replacement and directory `fsync`, before constructing a backend or opening
   USB;
3. opens the bound device and obtains two stable 32-MiB reads equal to the exact
   current boundary;
4. emits `F6 18` and exactly one state-derived `F6 06` or `F6 15`; normally it
   then runs the strict WIP poll; and
5. normally obtains two more stable 32-MiB reads equal to the one exact
   postimage, closes USB strictly, and then publishes the verified boundary.

Operation index 9 is the mandatory exception to the poll and postread portions
of steps 4 and 5. After the fixed `program-09` CBW, exact 512-byte data-OUT and
strict CSW validation complete, the process marks its handle abandoned, emits
no WIP poll or flash read, atomically publishes and reads back
`checkpoint_command_complete`, and sends itself `SIGKILL` without explicit USB
close. The shell must report status 137. The journal `fsync` and readback are
fallible work between CSW and the signal, so this is durable command completion
followed by abrupt userspace termination—not immediate post-CSW death, a proven
NOR-pulse interruption, a physical USB disconnect or device-power interruption.
This checkpoint cannot be selected, moved or skipped through the CLI.

No invocation can perform a second mutation. Raw `intent` at every index is
terminal: it cannot prove command completion, prohibits every further USB
command and requires external-SPI recovery. For an ordinary operation, exact
postimage verification is followed by strict USB close and only then exact
boundary publication. A publication error is accepted only if the exact target
is visible and validates; raw intent remains terminal, while an unclassifiable
or third state requires local-only inspection. A mutation close failure is also
terminal.

An atomic publication/readback that cannot be classified in-process produces
`STATE INSPECTION REQUIRED` / exit 4. It authorizes only a fresh local
`inspect`, which has no `--commit` option and never opens USB. Inspection reports
the exact journal status and only a permitted dry run or external-SPI action; it
does not itself authorize USB. Exact `preflight_started`, raw intent or either
reconciliation-started state requires SPI.

`reconcile --commit`, started as a new process, uses a verifier-only backend
whose endpoint-recovery traffic is disabled. It admits only exact
`checkpoint_command_complete` or final `complete`; intermediate
`boundary_verified` states are not reconcilable. Before opening USB it
atomically consumes the source into `checkpoint_reconcile_started` or
`final_reconcile_started` and reads the started state back exactly. If that
publication fails with the exact source retained, no USB was opened and exit 4
permits a fresh-process retry. Once a started state is visible, the one-shot
authorization is consumed: backend/open, transport, verification or close
failure is terminal external SPI. Final publication accepts only the exact
target; an unclassifiable atomic result permits local-only inspection, never
another USB probe.

For checkpoint reconciliation, the backend performs the omitted WIP-ready
poll, then takes two stable full-chip reads and accepts only the exact preimage
or exact postimage. The exact postimage advances to boundary 10 without replay.
The exact preimage is known and non-corrupt, but consumes the single permitted
checkpoint attempt: after strict USB close the journal enters
`checkpoint_no_effect`, the command exits 5 and every later `step` is refused.
The campaign must stop and must not silently retry. Restore and verify the
complete owner baseline through the rehearsed external-SPI path before normal
boot or another campaign. Any other stable image also requires external SPI
recovery.

Read-only reconciliation is equally fail-closed. After a started state is
durable, a backend/open, identity, omitted WIP poll, full-chip read or exact-
classification anomaly exits 3; an attempted close that itself fails also exits
3. None may be retried over USB. Exact classification and strict close precede
the final boundary/no-effect publication or journal clear. A reported atomic
publication error is accepted only when the exact target is visible; a reported
clear error is accepted only when the journal is exactly absent. A retained
started state requires external SPI. An outcome that cannot be classified in
the same process requires local-only `inspect`; USB remains unauthorized until
that exact state is understood.

Eligible clean-session closes use strict device subclasses. Release and
kernel-driver-reattach return codes are checked; reattach is never attempted
after failed release; and local handle close plus context exit are attempted in
all cases. Any failure in that sequence is exit 3 and requires external-SPI
recovery.

At the checkpoint, this global policy includes any `F6 18`, program CBW,
data-OUT or CSW anomaly before strict program-CSW validation, and any failure
that leaves raw intent instead of exact `checkpoint_command_complete`. Shell
status 137 is required for experiment-valid continuation. If ready publication
reports an error but exact ready is visible, the tool does not send `SIGKILL`;
it exits 4 and authorizes one read-only cleanup only. If `SIGKILL` cannot be
delivered or returns, the process uses status 126. Exact ready still permits one
safe cleanup reconciliation, but either outcome invalidates the experiment:
restore over SPI after cleanup even if boundary 10 is observed. Journal state
alone cannot encode whether the shell observed status 137.

The last step leaves a durable `complete` journal rather than deleting state in
the same mutation process. A final read-only `reconcile --commit` first consumes
it into `final_reconcile_started`, then verifies the exact restored baseline
twice, closes USB strictly and clears the journal.

Committed `preflight`, `step` and `reconcile` hold the same lock through state
read, USB close and final state publication. A concurrent invocation therefore
fails before opening USB. The empty mode-`0600` lockfile is intentionally never
deleted; reusing one persistent inode avoids a replacement/unlink lock race.
Like the journal, it remains owner-local and outside the repository.

## Offline inspection commands

Keep both captures and the journal outside the repository. These commands are
dry runs: they validate local inputs and state but do not open USB.

```sh
python3 tools/flash-access/kb7-updater-scratch-executor.py preflight \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --journal /path/to/owner-local-scratch-journal.json

# After a committed preflight has created the journal, this displays the one
# state-derived next operation without opening USB.
python3 tools/flash-access/kb7-updater-scratch-executor.py step \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --journal /path/to/owner-local-scratch-journal.json

# With exact checkpoint-command-complete or final-complete state, this validates
# the one permitted reconciliation request locally.
python3 tools/flash-access/kb7-updater-scratch-executor.py reconcile \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --journal /path/to/owner-local-scratch-journal.json

# After STATE INSPECTION REQUIRED, this only validates local state. It has no
# --commit option and never opens USB.
python3 tools/flash-access/kb7-updater-scratch-executor.py inspect \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --journal /path/to/owner-local-scratch-journal.json
```

The owner-authorized v1 and v2 hardware runs are documented separately. V1 is
historical evidence for the same fixed operation list; v2 additionally
exercised the WIP-ready/no-postread active-intent path. Neither is a hardware
result for v3 or standing approval to repeat the experiment or broaden the
mutation domain. `--commit` is the only switch that opens USB.
`preflight --commit` remains read-only; every `step --commit` is destructive
and normally advances exactly one operation; the mandatory boundary-9 step
instead durably records `checkpoint_command_complete` and self-terminates with
status 137. `reconcile --commit` remains read-only. Each command must be a fresh
process.

## Stop and recovery rules

- Exit 0 means only that the requested dry run or exact live classification
  completed.
- Exit 2 is a local validation, setup, CLI or lock abort before an authorized
  USB operation begins. Do not infer anything about a different invocation's
  durable state from that status alone.
- Exit 3 means `preflight_started`, raw intent or a reconciliation-started state
  is authoritative; a USB close failed; or another classified terminal outcome
  occurred. Before safe classification the process does not explicitly close
  or reattach the interface. Do not run any further USB command; recover the
  complete baseline over external SPI.
- Exit 4 with `STATE INSPECTION REQUIRED` authorizes only fresh-process
  `inspect`. It opens no USB and reports the exact journal state plus a permitted
  dry run or external-SPI action. Exit 4 with `RECONCILIATION REQUIRED` permits
  only the stated fresh read-only reconciliation. It can mean that `step` was
  invoked while exact `checkpoint_command_complete` was already present, that
  a reconciliation-start publication retained its exact source before USB, or
  that exact checkpoint-command-complete became visible after a reported ready-
  publication error. The last case is cleanup-only and invalidates the
  experiment. Do not run `step` again.
- A reported atomic publication error is accepted only when its exact target is
  visible under that transition's policy. A final clear error is accepted only
  when the journal is exactly absent. Any unclassifiable outcome goes through
  local-only inspection before another action is chosen.
- Shell status 137 is the planned v3 boundary-9 self-`SIGKILL`. It is expected
  only after exact `checkpoint_command_complete` publication. No diagnostic is
  emitted after that publication because terminal output could block at the
  tested boundary. Keep USB and power connected and run only fresh-process
  `reconcile --commit` next.
- Exit 126 means the planned self-`SIGKILL` failed or returned unexpectedly. It
  is not validation evidence. Exact `checkpoint_command_complete` permits one
  read-only cleanup reconciliation, after which the complete baseline must be
  restored over SPI even if boundary 10 was observed.
- Exit 5 means the mandatory checkpoint produced its exact preimage and the
  single permitted attempt is consumed. The flash is in an exact known scratch
  state, not a corruption state, but the campaign and all USB mutations must
  stop. Keep the journal, then use the rehearsed external-SPI path to restore
  and verify the complete owner baseline before normal boot or another
  campaign.
- An operator interruption before any durable one-shot marker exits 130. An
  interruption while `preflight_started` or raw intent exists is an exit-3
  external-SPI outcome. Exact
  `checkpoint_command_complete` permits only its one read-only reconciliation;
  without status 137, that reconciliation is cleanup rather than experiment-
  valid continuation.

Keep the independently rehearsed 3.3-V external-SPI path, two exact owner
backups and the ability to hold the SoC off the flash bus available throughout
any eventual run. If reconciliation sees neither exact preimage nor exact
postimage, stop USB work and restore/verify the complete owner image over SPI.

## What remains unproved

Offline tests cover the fixed operation construction, rejection of non-scratch
and firmware-domain operations, transport ordering, two-read gates, preflight-
started and raw-intent gates before backend construction, durable command-
complete publication before post-CSW/pre-poll termination, one-shot
reconciliation-started gates, local-only state inspection, strict-close
ordering, fresh-process nonce, mutation-incapable no-recovery reconciliation
backend, one-operation process boundary, reconciliation and journal faults. The
exact v3 plan is hardware-unrun. See the
[v3 host-termination plan](USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md).

The exact v2 plan completed once on the development unit: `program-09` and
WIP-ready completed, the process exited 4 without postread, and a fresh
verifier-only process classified two exact 32-MiB postimage reads at boundary
10 without retry. The fixed continuation restored the baseline at boundary 22;
final reconciliation cleared state; a separate verifier reproduced the
baseline and passed every region CRC; and the owner confirmed normal boot. See
the
[v2 validation record](USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md).

The historical v1 hardware run proved traversal of all 22 ordinary exact
command boundaries and finalization on the tested loader, unit and geometry. It
never left an intent unresolved or exercised active-intent reconciliation. The
completed v2 run adds only controlled command-complete/no-postread
reconciliation and continuation evidence. V3 moves the planned host-process
termination to after validated program CSW and durable command-complete
publication but before WIP polling; it has no hardware result. None of these
revisions physically interrupts CBW, data, CSW,
a NOR program pulse or an erase pulse. They therefore do not prove arbitrary
torn-state recovery, physical-disconnect or power-loss recovery, `F6 17`,
`F6 19`, other loader versions, other units, firmware-region writes, replacement-firmware
correctness or a production updater. The final separate verifier was a
separate program entry point, but both it and the executor read through the
same loader and SoC flash controller; matching reads cannot exclude a
repeatable defect in that path. External SPI remains the independent recovery
and bit-level verification route.
