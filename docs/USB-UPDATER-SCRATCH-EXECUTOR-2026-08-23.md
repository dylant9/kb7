# Fixed scratch executor status and test plan — 2026-08-23

## Status

The repository contains a separate, deliberately narrow USB mutation harness:

```text
tools/flash-access/kb7-updater-scratch-executor.py
```

It is **dry-run by default**, is restricted to the reviewed V1.22 loader and
scratch layout, and can replay only the 22 operations listed below. The current
v2 source and fake-transport tests pass offline, and the exact v2 plan has now
completed once on the development KB7. Its mandatory active-intent checkpoint
followed the fixed `program-09` command and WIP-ready poll, before any postread
or verified boundary publication. The process exited 4 with intent active; a
fresh process using the mutation-incapable verifier backend then classified two
full-chip reads as the exact postimage without retry. The remaining operations
restored the exact baseline, final reconciliation cleared state, a separate
verifier reproduced the same full-chip hash with all three region CRCs valid,
and the owner confirmed normal boot.

The preceding v1 plan, SHA-256
`491b06c1beb66fa606639e1d420109dcf856c91b50ad02d5fbd0e6bafe1cc797`,
completed one hardware cycle, restored the exact baseline and returned to
operator-reported normal keyboard operation. That result remains historical
evidence for the unchanged commands and geometry; it is not a hardware result
for the current v2 state machine. See the
[historical validation record](USB-UPDATER-SCRATCH-EXECUTOR-VALIDATION-2026-08-23.md)
and the separate
[v2 checkpoint test plan](USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md)
and [v2 validation record](USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md).

The current canonical v2 descriptor has SHA-256
`f0a8acfcdc7ab5fb7a7dc2753ed8bdca0e381a9433f64fe311348442a8bbdb32`.
It includes the mandatory checkpoint index, command and stop policy. The v2
journal binds that plan plus the scratch-plan, writer, verifier and executor
source hashes, so implementation or policy drift fails closed between
invocations.

This is not the paired-firmware updater. The general
`kb7-updater-executor.py` command line still exposes only read-only `preflight`
and `reconcile`, its mutation adapter remains hard-disabled, and firmware-region
mutation remains unavailable. The scratch harness accepts no bundle, operation,
address, length, CDB, payload, device selector, retry, force or skip option.
Neither the historical run nor the current validated scratch-only revision
changes `flash_approved=false`.

## Fixed operation domain

All mutations remain inside the erased V1.22 containment envelope
`[0x000c0000,0x00100000)`. Programs are exactly one 512-byte block using
`F6 06`; erases are exactly one 4-KiB sector using `F6 15`. Every mutation is
preceded immediately by the sub-16-MiB `F6 18` address-mode command and followed
by the strict WIP poll. The plan is:

| Index | Action | Offset(s) | Fixed content |
|---:|---|---|---|
| 0 | program | `0x000c4e00` | deterministic pattern slot 0, lower guard |
| 1–8 | program | `0x000c5000..0x000c5e00`, step `0x200` | pattern slots 1–8, work sector A |
| 9 | program | `0x000c6000` | pattern slot 9; mandatory active-intent checkpoint after WIP ready and before postread |
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
manifest and erased scratch envelope; opens the live loader; obtains two stable
full-chip reads equal to the baseline; and creates a new owner-local scratch
journal.

Each separate `step --commit` invocation then:

1. acquires a persistent, nonblocking sibling lockfile, then reloads and
   validates the complete fixed transaction and journal;
2. obtains two stable 32-MiB reads equal to the exact current boundary;
3. durably records one operation intent using file `fsync`, atomic replacement
   and directory `fsync`;
4. emits `F6 18`, exactly one state-derived `F6 06` or `F6 15`, and the WIP
   poll; and
5. normally obtains two more stable 32-MiB reads equal to the one exact
   postimage before durably advancing the journal.

Operation index 9 is the mandatory exception to step 5. After the fixed
`program-09` command and strict WIP poll complete, the process deliberately
does not read flash or advance the journal. It closes with the canonical intent
still active and exits 4. This checkpoint cannot be selected, moved or skipped
through the CLI. It is command-complete/no-readback behavior, not a physical
USB interruption or power cut.

No invocation can perform a second mutation. If anything fails after intent is
durable, the tool exits with reconciliation required and does not retry.
`reconcile --commit`, started as a new process, uses the verifier-only backend:
it takes two stable full-chip reads and accepts only the exact intent preimage
or exact postimage. Every intent includes a process-instance nonce and the same
process is refused before USB opens. At the mandatory checkpoint, the exact
postimage advances to boundary 10 without replay. The exact preimage is a known,
non-corrupt image but consumes the single permitted checkpoint attempt: the
journal enters `checkpoint_no_effect`, exits 5 and refuses every later `step`.
The campaign must stop for a separately reviewed cleanup decision; it must not
silently retry. Any other stable image requires external SPI recovery.

The last step leaves a durable `complete` journal rather than deleting state in
the same mutation process. A final read-only `reconcile --commit` must verify
the exact restored baseline twice before it clears the journal.

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

# With an existing intent, this validates the reconciliation request locally.
python3 tools/flash-access/kb7-updater-scratch-executor.py reconcile \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --journal /path/to/owner-local-scratch-journal.json
```

The owner-authorized v1 and v2 hardware runs are documented separately. V1 is
historical evidence for the same fixed operation list; v2 additionally exercised
the mandatory active-intent path. Neither is standing approval to repeat the
experiment or broaden the mutation domain. `--commit` is the only switch that
opens USB.
`preflight --commit` remains read-only; every `step --commit` is destructive
and normally advances exactly one operation; the mandatory boundary-9 step
instead exits 4 with intent active. `reconcile --commit` remains read-only.
Each command must be a fresh process.

## Stop and recovery rules

- Exit 0 means only that the requested dry run or exact live classification
  completed.
- Exit 2 is a validation or transport abort before the tool can classify a
  required recovery outcome. Do not infer that a durable intent had no effect.
- Exit 3 explicitly requires SPI recovery. Do not issue another USB mutation.
- Exit 4 means a durable intent exists and a new-process
  `reconcile --commit` is required. Do not run `step` again first.
- Exit 5 means the mandatory checkpoint produced its exact preimage and the
  single permitted attempt is consumed. The flash is in an exact known scratch
  state, not a corruption state, but the campaign and all USB mutations must
  stop pending a separately reviewed cleanup decision. Keep the journal and
  device state intact; do not power-cycle.
- An operator interruption before durable intent exits 130. An interruption at
  or after a mutating transport boundary must still be treated as uncertain.

Keep the independently rehearsed 3.3-V external-SPI path, two exact owner
backups and the ability to hold the SoC off the flash bus available throughout
any eventual run. If reconciliation sees neither exact preimage nor exact
postimage, stop USB work and restore/verify the complete owner image over SPI.

## What remains unproved

Offline tests cover the fixed operation construction, rejection of non-scratch
and firmware-domain operations, transport ordering, two-read gates, durable
state binding, the mandatory no-postread checkpoint, fresh-process nonce,
mutation-incapable reconciliation backend, one-operation process boundary,
reconciliation and journal faults. The exact v2 plan then completed once on the
development unit: `program-09` and WIP-ready completed, the process exited 4
without postread, and a fresh verifier-only process classified two exact
32-MiB postimage reads at boundary 10 without retry. The fixed continuation
restored the baseline at boundary 22; final reconciliation cleared state; a
separate verifier reproduced the baseline and passed every region CRC; and the
owner confirmed normal boot. See the
[v2 validation record](USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md).

The historical v1 hardware run proved traversal of all 22 ordinary exact
command boundaries and finalization on the tested loader, unit and geometry. It
never left an intent unresolved or exercised active-intent reconciliation. The
completed v2 run adds only controlled command-complete/no-postread
reconciliation and continuation evidence. Neither
revision physically interrupts CBW, data, CSW, WIP polling, a NOR program pulse
or an erase pulse. They therefore do not prove
arbitrary torn-state recovery, power-loss recovery, `F6 17`, `F6 19`, other
loader versions, other units, firmware-region writes, replacement-firmware
correctness or a production updater. The final separate verifier was a
separate program entry point, but both it and the executor read through the
same loader and SoC flash controller; matching reads cannot exclude a
repeatable defect in that path. External SPI remains the independent recovery
and bit-level verification route.
