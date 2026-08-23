# Offline USB updater design — 2026-08-23

## Status

The repository now contains an **offline-only** V1.22 update planner and
interruption-model checker:

```text
tools/flash-access/kb7-updater-plan.py
```

It cannot open a USB device and has no execute, commit, force, address, length
or raw-CDB option. It emits owner-local replacement sector images, a
full-image-bound plan and a model report. It is not a flasher, its bundles are
unsigned, and every result records `execution_authorized=false` and
`flash_approved=false`.

An optional
[detached authentication tool](OFFLINE-UPDATER-AUTHENTICATION-2026-08-23.md)
now revalidates the complete bundle before producing or checking an Ed25519
envelope. It requires a separately pinned public-key SPKI fingerprint and
repeats the false authorization flags. No project release key or trust root is
provisioned, and authentication never makes a bundle executable.

A separate [read-only executor scaffold](USB-UPDATER-EXECUTOR-SCAFFOLD-2026-08-23.md)
now performs live two-read preflight and reconciliation, durable journal
binding, and offline fault injection. Its public CLI cannot mutate flash and
its mutation adapter is hard-disabled. It is not a supported updater.

A further [fixed scratch executor](USB-UPDATER-SCRATCH-EXECUTOR-2026-08-23.md)
provides a deliberately separate, dry-run-default harness for 22 immutable
operations in the V1.22 erased scratch gap. It accepts no firmware bundle or
caller-selected mutation and does not unlock the paired-firmware executor. Its
source and fake-transport/state tests have passed offline. Its complete fixed
v1 plan also passed once on the development unit: all 22 ordinary
command-boundary postimages were accepted, final new-process reconciliation
cleared the journal at the exact baseline, and a separate verifier entry point
reproduced the same 32-MiB image before operator-reported normal keyboard
operation. The historical v2 plan added a mandatory active intent after
`program-09` completes and WIP reports ready, then closes without postread; only
a fresh process with a mutation-incapable backend may reconcile. V2 has now
completed once: two exact postimage reads were accepted without retry, the
remaining fixed plan restored the baseline, final reconciliation cleared state,
a separate verifier passed every region CRC, and the owner confirmed normal
operation. The current v3 plan has also completed once. It self-terminates with
signal 9/status 137 after validated `program-09` CSW and durable/read-back
`checkpoint_command_complete`, but before WIP polling, postread or explicit USB
close. Preflight publishes `preflight_started`, and every step publishes raw
intent, before backend construction or USB; either surviving marker is terminal
SPI. Only exact checkpoint-command-complete and final-complete are reconcilable.
Each read-only pass consumes a one-shot reconciliation-started state before USB,
then classifies exactly and closes strictly before final publication. Atomic
ambiguity permits only fresh local `inspect`, never USB. Status 137 is operator-
observed rather than journal-bound; status 126 or ready-publication error permits
cleanup only and cannot validate continuation. In the observed run, fresh-
process reconciliation accepted the exact postimage without replay, cleanup
restored the baseline, the separate verifier passed every region CRC, and the
owner confirmed normal `5038` keyboard operation. This is fixed scratch work
only; it does not authorize firmware-region execution. See the
[v3 host-termination plan](USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md),
[v3 validation record](USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md),
historical [v2 test plan](USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md),
[v2 validation record](USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md) and
[historical validation record](USB-UPDATER-SCRATCH-EXECUTOR-VALIDATION-2026-08-23.md).

A third, non-general domain now exists for the
[minimal loader-reentry proof campaign](LOADER-REENTRY-PROOF-CAMPAIGN-2026-08-23.md).
Its offline builder derives only one proof-Core0/exact-stock-Core1 install and
the exact-stock restore, with a temporary Core1 checksum barrier and a sparse
rank-32 Core0 gate committed last. Its separate executor accepts exactly one
campaign operation per process and no caller-selected address, payload, CDB or
firmware bundle. The two exact owner baselines now independently reproduce its
pinned 168-operation campaign and exact proof/stock closures. Offline
simulation and fault tests pass, but live commit is independently
hard-disabled and no proof image has run on hardware. This does not alter or unlock the
general paired executor described above.

The planner was exercised offline against two matching V1.22 full-chip inputs
and the current locally built ELFs. An independent `simulate` pass reproduced
the same 161-operation plan, preserved every immutable byte, found no early
checksum-valid mixed pair and reached the exact predicted final image. No
hardware write was performed.

## Why this replaces the old manifest-last idea

V1.22 has one active manifest sector. Erasing it creates an unavoidable
power-loss window in which a partly erased mapping could be neither safely old
nor safely new. The older audit bundle also described logical region lengths
that are not multiples of the loader's proven 512-byte program unit.

The new design never erases or programs the header, preserved loader or
manifest. The two replacement regions are CRC-balanced so their final
`SN_FWIN` checksums equal the existing V1.22 values:

| Region | Flash range covered by CRC | Preserved checksum |
|---|---:|---:|
| core0 | `0x11000..0x2035c` | `0xc3f43a6f` |
| region-1 application | `0x21000..0x8c168` | `0xc8ed2815` |

Only the aligned sector envelopes `0x11000..0x21000` and
`0x21000..0x8d000` appear in the plan. Bytes `0x00000..0x10fff` and
`0x8d000..0x1ffffff` are immutable and hash-bound to two fresh, matching
32-MiB captures.

CRC balancing is compatibility with the recovered loader, not authenticity.
CRC-32 is not a signature. The bundle content ID detects accidental or
unreviewed changes but does not identify a publisher. The detached Ed25519
mechanism can identify a publisher only after a project key and independently
distributed fingerprint are provisioned; neither exists yet. The independent
`simulate` command binds and reconstructs the sector payloads, but it does not
receive the original ELF inputs and therefore does not independently attest
their source provenance.

## Paired-build guard

Both images now contain a fixed 32-byte `KB7P` marker:

- core0 marker: execution address `0x00000140`;
- region-1 marker: execution address `0x10000100`;
- runtime ABI: version 2;
- pair identifier: a deterministic 16-byte value patched into both images by
  the offline planner.

The standalone ELF contains an all-`0xff` identifier and therefore deliberately
fails the runtime pair check. The planner derives one identifier from both raw
ELF images and patches the same value into both targets.

After clock, DRAM and cache preparation, core0 validates both markers **before
USB attach**, publishes the pair identifier through runtime ABI v2, and only
then branches to the region-1 application. Region-1 validates both markers,
the ABI and the published identifier **before data/BSS initialization or board
I/O**. An old/new, new/old, wrong-ABI or independently built pair parks fail
closed for external reset.

This guard matters because stock, replacement and a mixed stock/replacement
pair deliberately share the same weak manifest checksums after CRC balancing.

## Transaction model

The offline plan has this normative order:

1. Require two distinct, byte-identical 32-MiB captures. Pin the V1.22 header,
   preserved loader, manifest and both stock cores; verify all three manifest
   region checksums and erased sector-tail padding.
2. Program one requested `1 -> 0` poison bit in stock core0. A modeled
   interruption leaves either exact stock or a checksum-invalid core0.
3. Program one requested `1 -> 0` poison bit in stock core1. Both regions are
   then checksum-invalid.
4. Erase, program and read back the region-1 body while core0 is an exact
   invalid barrier. The four-byte region-1 commit gate remains erased.
5. Erase, program and read back the core0 body while region-1 remains an exact
   invalid barrier. The four-byte core0 commit gate remains erased.
6. Program the sparse region-1 gate, leaving core0 invalid.
7. Program the sparse core0 gate last. Only the exact paired target now matches
   both unchanged manifest checksums.

Every program command is one 512-byte block and every erase is one aligned
4-KiB sector. The plan records the literal `F6 06`/`F6 15` CDB, mandatory
sub-16-MiB `F6 18` mode command, payload hash, exact sector pre/post hashes and
whole mutable-state hashes. It contains no manifest operation and no stock
bytes.

## CRC correction and commit gates

Each linker script reserves post-image padding for a four-byte CRC correction
word and a separate four-byte gate:

| Region | Maximum linked extent | Correction offset | Gate offset/block |
|---|---:|---:|---:|
| core0 | `0xee00` | `0xee00` | `0xf000` / flash `0x20000` |
| region-1 | `0x6ac00` | `0x6ac00` | `0x6ae00` / flash `0x8be00` |

The target gate is `00 00 00 00`; its staged value is `ff ff ff ff`. The
planner solves the separate correction word so the target retains the stock
checksum, then independently recomputes it. It also proves that the 32 gate
bits have rank 32 in the CRC transform. Under the modeled requested-bit-subset
program behavior, no proper subset of those 32 clears can produce the target
checksum. The sparse 512-byte commit block contains only the zero gate word and
`0xff` elsewhere.

## What the checker proves

For every ordered mutation it checks the no-effect and exact-effect command
boundaries, boot classification, opposite-core invalid barrier, immutable
hashes, literal CDB and exact target. It records interruption sites around
journal intent, address mode, CBW/data/CSW, busy polling, readback and verified
journal replacement. A symbolic rank proof covers every subset of the final 32
requested gate clears.

Only exact stock (before the first effective poison) and the exact paired
target (after the last gate) may satisfy the recovered loader checksum model.
All known intermediate command-boundary states select ISP.

The planner report is a boundary/invariant analysis, not an exhaustive
emulation of physical torn commands. The paired-firmware executor scaffold now
implements restart classification and a durable-intent model with fake
transports, but live firmware mutation remains unavailable. The separate
scratch executor wires the same principles only to its immutable, non-firmware
22-operation command set. Its v1 plan completed once on the tested physical
loader; its historical v2 mandatory active-intent plan also completed once on
that unit. V1 exercised ordinary exact command boundaries, and the v2
checkpoint ended after command completion and WIP ready, before postread; a
fresh verifier-only process accepted two exact postimage reads. The current v3
plan moves abrupt userspace termination to after validated program CSW and
durable command-complete publication but before WIP polling, and has completed
once on the same unit. None is a physical mid-command or power-loss event. None
of these components claims
power-loss atomicity. They
cannot prove behavior for an interrupted NOR erase pulse, program disturb,
misaddressed device-side handler, unstable cell, loader defect or electrical
failure. Any mid-command hardware result requires two stable full reads and
exact image-derived classification; no journal may authorize a blind retry. An
unclassified result requires external SPI recovery.

## Offline use

Build the firmware and run the repository checks first. Keep two fresh
full-chip captures outside the repository, then create a new output directory
name:

```sh
make -C replacement_fw clean all

python3 tools/flash-access/kb7-updater-plan.py build \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --core0-elf replacement_fw/build/core0.elf \
  --core1-elf replacement_fw/build/core1.elf \
  --out /path/to/new-owner-local-plan

python3 tools/flash-access/kb7-updater-plan.py simulate \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --bundle /path/to/new-owner-local-plan
```

Do not place the generated binaries or JSON beside project source and do not
publish them as a release. The planner refuses a non-V1.22 source image, a
single/aliased capture, differing captures, a shifted ELF, an occupied reserve,
a stale or tampered payload/report, a manifest change, a checksum-valid staged
image or an early-valid mixed state.

## Remaining steps before any firmware-region hardware trial

1. Independently review the planner, pair guard and model after every change.
   The detached Ed25519 mechanism is implemented, but a release key, trusted
   fingerprint distribution, rotation/revocation policy, and signed release
   procedure still need approval.
2. The paired-firmware executor's strict read-only preflight, durable intent journal
   (`fsync` file, atomic rename and directory `fsync`), two-read
   reconciliation, live loader/topology/session binding and fake-transport
   fault injection are implemented. Its live mutation adapter remains
   hard-disabled and there is no execute command. The offline baseline hash and
   USB topology are not a unique physical-device identity; two byte-identical
   units remain indistinguishable.
3. The reviewed fixed scratch-only multi-sector/reconciliation experiment has
   passed once. It classified two command-complete no-readback outcomes from
   new processes and restored the exact baseline. A new separate harness now
   expresses that geometry as 22 one-operation, state-derived invocations. Its
   v1 plan passed once on hardware, including final new-process reconciliation
   and exact baseline restoration. Its historical v2 plan also passed once: its
   mandatory boundary-9 active-intent checkpoint was followed by fresh-process,
   read-only exact-postimage reconciliation and fixed baseline restoration. Both
   the executor and separate verifier read through the same USB loader/SoC
   controller. The current v3 durable-command-complete/pre-WIP self-termination
   plan has also passed once: status 137 was observed, exact postimage
   reconciliation continued without replay, and cleanup restored the baseline.
   Physical mid-command, power-loss and arbitrary torn-NOR reconciliation remain
   separate gates before reviewing
   any source change that could enable firmware-region execution.
4. Prove entry back to `5037` after a checksum-valid but nonfunctional custom
   core0, or continue to require an attached and independently tested SPI
   recovery path.
5. Validate the replacement firmware's remaining cold-start, USB, memory and
   functional peripheral hardware gates before its first installation. The pin
   routes are recovered offline.

Until all of those are complete, the paired-firmware work is planning and
read-only diagnostic evidence only. The fixed scratch harness is destructive
laboratory tooling, not authorization for a firmware-region trial.
