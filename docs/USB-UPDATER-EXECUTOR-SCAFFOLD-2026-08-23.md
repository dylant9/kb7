# USB updater executor scaffold — 2026-08-23

## Status

The repository now contains a deliberately **read-only** executor scaffold:

```text
tools/flash-access/kb7-updater-executor.py
```

Its public command line exposes only `preflight` and `reconcile`. Both commands
read the device through the preserved V1.22 USB-ISP loader; neither can erase or
program flash. There is no execute, commit, force, arbitrary-offset or raw-CDB
option. The mutation adapter's methods unconditionally raise; the executor
contains no wired erase, program, address-mode or busy-poll call. The reported
mutation-enabled status also remains false.

This is the next software step after the offline paired updater planner. It is
not a firmware installer, does not make the replacement firmware safe to run,
and does not change `flash_approved=false`.

A second tool now exists with a deliberately different domain:
`kb7-updater-scratch-executor.py`. It can replay only the fixed 22-operation
V1.22 scratch experiment, is dry-run by default, and has no firmware-bundle or
caller-selected mutation interface. Its preceding v1 plan completed once on the
development unit. The historical v2 plan also completed once: its fixed
boundary-9 command-complete/no-postread checkpoint exited 4, a fresh process
over a mutation-incapable transport accepted two exact postimage reads without
retry, and the fixed continuation restored the baseline and normal operation.
The current v3 scratch plan has also completed once. It self-terminates with
signal 9/status 137 after validated program CSW and durable/read-back
`checkpoint_command_complete`, but before WIP polling, postread or explicit USB
close; fresh-process read-only reconciliation supplies the omitted poll. No
revision unlocks this paired-firmware executor; the two tools use
distinct plans and journal schemas. See the
[fixed scratch executor plan](USB-UPDATER-SCRATCH-EXECUTOR-2026-08-23.md) and
[v3 host-termination plan](USB-UPDATER-SCRATCH-HOST-TERMINATION-TEST-PLAN-2026-08-23.md),
the [v3 validation record](USB-UPDATER-SCRATCH-HOST-TERMINATION-VALIDATION-2026-08-23.md),
the historical
[v2 mandatory checkpoint plan](USB-UPDATER-SCRATCH-ACTIVE-INTENT-TEST-PLAN-2026-08-23.md),
the [v2 validation record](USB-UPDATER-SCRATCH-ACTIVE-INTENT-VALIDATION-2026-08-23.md),
and the [historical v1 validation record](USB-UPDATER-SCRATCH-EXECUTOR-VALIDATION-2026-08-23.md).

## Transaction reconstruction

Before opening USB, the scaffold independently reloads the owner-local bundle
and the two distinct 32-MiB baseline captures. It delegates the complete strict
bundle verification to `kb7-updater-plan.py`, then reconstructs:

- the exact V1.22 source anchors and full baseline hash;
- both checksum-balanced replacement sector envelopes;
- the canonical poison, staging and sparse-gate operation sequence;
- every operation-boundary mutable-state hash; and
- the exact final 32-MiB target hash.

Symlinked bundles or baselines, differing or aliased captures, extra bundle
files, malformed JSON, changed payloads, noncanonical operations and an altered
simulation report all fail before device access.

## Read-only live preflight

`preflight` performs this sequence:

1. Reconstruct and verify the complete offline transaction.
2. Open the strict BOT transport and require the reviewed `F6 00`/`F6 F1`
   loader identity.
3. Read all 32 MiB twice. Both reads must be byte-identical.
4. Require that exact image to equal the bundle's owner-supplied baseline and
   revalidate the header, preserved-loader, manifest and stock-core anchors.
5. Bind the journal to the USB topology path, stable loader response, live
   loader-window hash, live manifest hash, baseline, bundle and all relevant
   tool-source hashes.
6. Persist a `preflight_verified` journal.

The USB topology is useful session evidence, not a cryptographic device serial.
Two byte-identical keyboards attached at the same topology are not
distinguishable by the recovered protocol. The exact full-chip image is the
stronger effective binding.

## Durable journal

The owner-local journal records either an exact verified operation boundary or
one active operation intent. Each intent binds the operation descriptor, exact
preimage hash and exact expected postimage hash. A journal update:

1. writes a mode-`0600` temporary file in the same directory;
2. flushes and `fsync`s that file;
3. atomically replaces the journal; and
4. `fsync`s the containing directory.

Strict JSON parsing rejects duplicate fields and non-finite values. Missing,
unknown or stale fields fail closed. The journal is also bound to hashes of the
executor, planner, strict writer and verifier sources, so changing any of those
files between stages invalidates it.

The journal is never treated as proof of flash state. It is only a hint about
the edge that might have been interrupted.

## Read-only reconciliation

`reconcile` queries the loader again and obtains two new, byte-identical
full-chip reads. It first proves that every byte outside the two authorized core
sector envelopes still equals the baseline. It then classifies the observed
image as one of:

- exact stock;
- an exact canonical intermediate boundary;
- exact paired target;
- a modeled partial transition confined to the active operation unit; or
- external-SPI recovery required.

An exact boundary can repair a missing or torn journal because the image, not
the journal, establishes the boundary. A valid journal whose bundle, source or
device binding is stale is refused rather than silently replaced. A partial
transition never authorizes an automatic retry, and an unexplained byte outside
the active unit requires SPI recovery.

## Offline mutation-state tests

The source includes an internal one-operation state engine used only with fake
transports by the test suite. It writes durable intent before a modeled command,
requires two exact pre-reads and two exact post-reads, and handles Ctrl-C as an
unknown result after intent. Tests inject interruption at all 15 recorded sites:

- before, during and after intent persistence;
- address-mode selection;
- CBW, payload/erase and CSW handling;
- ready polling and timeout;
- readback and comparison; and
- verified-journal persistence.

They also cover strict journal parsing, file/directory `fsync`, path alias and
symlink refusal, live identity mismatch, exact-boundary journal repair,
reachable partial-unit classification and immutable-range damage.

The tests do not make the mutation adapter callable. They prove state-machine
behavior against the recovered model, not physical power-loss atomicity.

All live byte verification still uses the same preserved loader and SoC flash
controller (`F6 05`). Two matching reads detect instability but cannot detect a
repeatable bug in that same read path. External SPI remains the independent
bit-level recovery and verification route.

## Read-only commands

After generating an owner-local bundle with the offline planner, an operator may
run the following diagnostics. Each command performs two complete 32-MiB reads:

```sh
sudo python3 tools/flash-access/kb7-updater-executor.py preflight \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --bundle /path/to/owner-local-plan \
  --journal /path/to/owner-local-updater-journal.json

sudo python3 tools/flash-access/kb7-updater-executor.py reconcile \
  --baseline-a /path/to/fresh-read-a.bin \
  --baseline-b /path/to/fresh-read-b.bin \
  --bundle /path/to/owner-local-plan \
  --journal /path/to/owner-local-updater-journal.json
```

Do not place the bundle, sector images, full captures or journal in the public
repository. Their standard generated names are ignored and rejected by the
public-tree checker. Exit status 0 means an exact canonical boundary was
classified, 2 means validation/transport failure, 3 means the image requires
SPI recovery, and 4 means a modeled partial transition was observed but no
automatic mutation is authorized.

## Live read-only validation

The owner ran both commands in separate Python/libusb sessions on 2026-08-23.
The locally generated plan contained 161 fixed operations and had bundle ID
`77f435c8154f3052f1eafc34160a495345b3388c869cef7f7391afe135cf83a7`.
Its offline simulation passed with zero early checksum-valid non-target states.

Live `preflight` obtained two exact captures and classified the device as
`exact_stock` at USB topology `3-2.2`. The observed complete-image SHA-256 was
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`,
matching both owner baselines. It durably created a bound read-only journal.

A subsequent `reconcile`, started as a new process with a new USB handle,
again classified the complete image as `exact_stock`, operation boundary 0,
with no pre-existing journal error and no rebuild. Both commands reported live
mutation disabled, and neither issued a mutating command. This validates the
live read-only reopen, identity, whole-image and journal-binding path on the
development unit. It does not validate updater writes, a unique device serial,
or physical interruption recovery.

## Separate fixed scratch executor

The scratch harness turns the already reviewed scratch command list into 22
one-operation process boundaries: 18 fixed 512-byte programs and four fixed
4-KiB erases inside `[0x000c0000,0x00100000)`. Preflight publishes
`preflight_started`, and each step publishes raw intent, before constructing a
backend or opening USB. Each step then requires two exact full-chip pre-reads
and normally two exact postreads before strict close and boundary publication.
Its current v3 policy
instead locally abandons USB after `program-09` CSW validation, atomically
publishes and reads back `checkpoint_command_complete`, then self-terminates
before WIP polling or postread. The intervening `fsync` means this is durable
command completion followed by host death, not immediate post-CSW death.

Visible `preflight_started` or raw intent at every index is terminal external
SPI. Only exact
checkpoint-command-complete and final-complete states are reconcilable;
intermediate boundaries are not. Before opening its mutation-incapable backend,
each pass atomically consumes a one-shot `checkpoint_reconcile_started` or
`final_reconcile_started` state. A start-publication error with the exact source
retained permits a fresh-process retry because USB was never opened. Once
started is visible, any backend/open, transport, exact-classification or close
failure is terminal. Exact classification and strict USB close precede final
publication or clear. A final-publication error is accepted only when the exact
target is visible (or the final journal is exactly absent); an unclassifiable
atomic result permits local-only inspection, never another USB probe.
An in-process atomic ambiguity permits only the local `inspect` command; it has
no commit mode, opens no USB and reports a permitted dry run or SPI action.

Status 137 is required for experiment-valid continuation. Exact ready after
status 126 or a ready-publication error permits one cleanup reconciliation only,
then SPI restoration even if boundary 10 is observed. The journal cannot encode
the shell outcome. The last mutation leaves `complete` until its one-shot final
read-only pass verifies the baseline twice, closes cleanly and clears state.

The caller cannot provide an address, CDB, payload, length, bundle, device,
force, retry or skip choice. All operations are re-derived from a source-bound
plan and separate scratch journal. This provides an offline-testable bridge
between the earlier one-off scratch script and a state-derived executor without
placing any mutation code in the paired-firmware executor.

The current v3 source and fake-transport/state tests pass offline, and plan
`c1aa9348e74d6d4590b0e9666a9daf83e5544c3b23292b3df217c34038d5b653`
has completed one hardware cycle on the development unit. It produced status
137, rejected a duplicate `step` before USB, reconciled the exact postimage in
a fresh read-only process without replay, restored the exact baseline, cleared
state and returned to normal `5038` keyboard operation. The historical v2 plan
also completed one hardware cycle on the development unit. The fixed
`program-09` command and WIP-ready poll completed without a postread; the
process exited 4 with intent active; and a fresh process using the verifier-only
backend classified two exact 32-MiB postimage reads without retry. The remaining
plan restored the baseline, final reconciliation cleared the journal, a separate
verifier passed all three region CRCs, and the owner confirmed normal operation.

The preceding v1 harness also completed one full hardware cycle on the
development unit. All 22 ordinary exact operation boundaries passed; a
final new-process read-only reconciliation
verified the restored complete baseline twice and cleared the journal; and a
separate verifier entry point reproduced complete-image SHA-256
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`
before the owner reported normal keyboard operation. Both live readers use the
same USB loader and SoC `F6 05` controller path. This remains destructive
laboratory tooling rather than an updater qualification. V1 never left an
intent unresolved or entered active-intent reconciliation; the completed v2
checkpoint ended only after its command and WIP poll completed. V3 moves abrupt
host termination to after validated CSW and durable command-complete
publication but before WIP polling. None physically
interrupts a command or flash pulse, tests device power loss or touches firmware
regions.

## Remaining gates

Live firmware-region execution remains unavailable until all of the following
are separately completed and reviewed:

1. The fixed scratch-only multi-sector/process-restart experiment has passed:
   both command-complete no-readback operations reconciled to their exact
   postimages in new processes, the complete baseline was restored, and normal
   `5038` operation returned. This closed only the host-session restart gate.
2. The current v3 fixed durable-command-complete/pre-WIP host-termination plan
   has passed once. It is narrower than physical disconnect or power loss and
   must not be represented as either. Later work still needs deliberately
   modeled physical disconnect, power-loss and partial-operation outcomes at
   safe scratch addresses.
3. Re-review the exact operation transport, intent/restart behavior and source
   freeze. The separate scratch harness has no raw mutation interface; its v1
   plan passed once on hardware, its v2 mandatory active-intent plan passed once
   at a WIP-ready/no-postread boundary, and its v3 plan passed once at the
   durable-command-complete/pre-WIP host-termination boundary. Physical
   mid-command and power-loss behavior remain untested. Any
   future paired-firmware executor
   must remain independently locked until its own review and must likewise
   expose no raw mutation interface.
4. Provision release authenticity policy: detached Ed25519 bundle
   authentication is implemented and re-runs the complete planner verifier,
   but no project release key, independently distributed trust fingerprint,
   rotation/revocation procedure, or signed release exists yet. Authentication
   does not authorize installation.
5. Prove a reliable path back to USB ISP after a checksum-valid but
   nonfunctional custom core0, or require independently tested external SPI for
   every trial.
6. Pass the replacement firmware's cold-start, USB, memory, pinmux and
   peripheral hardware gates. The staged, no-write-first sequence is in
   `BOARD-VALIDATION-PLAN-2026-08-23.md`.

Until then, the paired-firmware executor's `preflight` and `reconcile` remain
diagnostics only. The scratch harness does not change that status. Any actual
custom-firmware write remains outside the supported project workflow.
