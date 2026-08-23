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

## Remaining gates

Live firmware-region execution remains unavailable until all of the following
are separately completed and reviewed:

1. Design, independently review and run a fixed scratch-only
   multi-sector/restart experiment while external SPI recovery is connected and
   proven.
2. Exercise reconciliation after controlled disconnects at safe scratch
   boundaries and after modeled partial scratch operations.
3. Re-review the exact operation transport, intent/restart behavior and source
   freeze. A future live executor must still have no raw mutation interface.
4. Add release authenticity: the present owner-local bundle is content-hashed
   but unsigned.
5. Prove a reliable path back to USB ISP after a checksum-valid but
   nonfunctional custom core0, or require independently tested external SPI for
   every trial.
6. Pass the replacement firmware's cold-start, USB, memory, pinmux and
   peripheral hardware gates.

Until then, `preflight` and `reconcile` are diagnostics only. Any actual custom
firmware write remains outside the supported project workflow.
