# Fixed scratch executor status and test plan — 2026-08-23

## Status

The repository contains a separate, deliberately narrow USB mutation harness:

```text
tools/flash-access/kb7-updater-scratch-executor.py
```

It is **dry-run by default**, is restricted to the reviewed V1.22 loader and
scratch layout, and can replay only the 22 operations listed below. Its source
and fake-transport tests have passed offline. **This new harness has not been
run on hardware.** The earlier successful `kb7-isp-scratch-restart.py` run
validated the underlying fixed commands and process-restart model on one unit;
it does not by itself validate this new orchestration implementation.

The canonical fixed-plan descriptor currently has SHA-256
`491b06c1beb66fa606639e1d420109dcf856c91b50ad02d5fbd0e6bafe1cc797`.
The journal binds that plan plus the scratch-plan, writer, verifier and executor
source hashes, so implementation drift fails closed between invocations.

This is not the paired-firmware updater. The general
`kb7-updater-executor.py` command line still exposes only read-only `preflight`
and `reconcile`, its mutation adapter remains hard-disabled, and firmware-region
mutation remains unavailable. The scratch harness accepts no bundle, operation,
address, length, CDB, payload, device selector, retry, force or skip option.

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
| 9 | program | `0x000c6000` | pattern slot 9, first block of work sector B |
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

`preflight --commit` is read-only. It requires two distinct, byte-identical,
exactly 32-MiB owner captures; checks the reviewed loader, V1.22 manifest and
erased scratch envelope; opens the live loader; obtains two stable full-chip
reads equal to the baseline; and creates a new owner-local scratch journal.

Each separate `step --commit` invocation then:

1. acquires a persistent, nonblocking sibling lockfile, then reloads and
   validates the complete fixed transaction and journal;
2. obtains two stable 32-MiB reads equal to the exact current boundary;
3. durably records one operation intent using file `fsync`, atomic replacement
   and directory `fsync`;
4. emits `F6 18`, exactly one state-derived `F6 06` or `F6 15`, and the WIP
   poll; and
5. obtains two more stable 32-MiB reads equal to the one exact postimage before
   durably advancing the journal.

No invocation can perform a second mutation. If anything fails after intent is
durable, the tool exits with reconciliation required and does not retry.
`reconcile --commit`, started as a new process, is read-only: it takes two
stable full-chip reads and accepts only the exact intent preimage or exact
postimage. Any other stable image requires external SPI recovery.

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

There is intentionally no documented hardware-run approval in this record.
When a hardware trial is separately reviewed and authorized, `--commit` is the
only switch that opens USB. `preflight --commit` remains read-only; every
`step --commit` is destructive and advances exactly one operation; and
`reconcile --commit` remains read-only. Each command must be a fresh process.

## Stop and recovery rules

- Exit 0 means only that the requested dry run or exact live classification
  completed.
- Exit 2 is a validation or transport abort before the tool can classify a
  required recovery outcome. Do not infer that a durable intent had no effect.
- Exit 3 explicitly requires SPI recovery. Do not issue another USB mutation.
- Exit 4 means a durable intent exists and a new-process
  `reconcile --commit` is required. Do not run `step` again first.
- An operator interruption before durable intent exits 130. An interruption at
  or after a mutating transport boundary must still be treated as uncertain.

Keep the independently rehearsed 3.3-V external-SPI path, two exact owner
backups and the ability to hold the SoC off the flash bus available throughout
any eventual run. If reconciliation sees neither exact preimage nor exact
postimage, stop USB work and restore/verify the complete owner image over SPI.

## What remains unproved

Offline tests cover the fixed operation construction, rejection of non-scratch
and firmware-domain operations, transport ordering, two-read gates, durable
state binding, one-operation process boundary, reconciliation and journal
faults. They do not prove the new harness on the physical USB loader.

Even a successful run would prove only exact command-boundary restart behavior
for this V1.22 unit and fixed erased scratch geometry. It would not prove an
actual mid-CBW/data/CSW disconnect, interruption during a NOR program or erase
pulse, arbitrary torn-state recovery, `F6 17`, `F6 19`, other loader versions,
firmware-region writes, replacement-firmware correctness or a production
updater. Two matching reads through the same loader also cannot exclude a
repeatable defect in that read path. External SPI remains the independent
recovery and verification route.
