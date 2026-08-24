# Fixed loader-reentry proof install and stock-restore campaign

Review date: 2026-08-23

## Current result

The remaining software work for the first checksum-valid custom-image proof is
implemented, bound to the exact owner baseline and independently reverified
offline. The exact bounded proof-install/exact-stock-restore campaign is now
live-enabled; it remains hardware-unrun.

The exact proof Core-0 image produced by `make -C replacement_fw recovery-proof`
has entry `0x00000175`, length 1,228 bytes and SHA-256
`dde05f5274952a30afb0d315ab21628da8ab0361b17aab9906f84216d364656c`.
The private campaign generator balances that image to the unchanged V1.22
manifest checksum. Its stable proof target consists of:

- the checksum-valid minimal proof in Core 0;
- the byte-exact stock V1.22 Core 1;
- the byte-exact stock header, preserved loader and manifest; and
- every byte after the Core-1 envelope unchanged.

`tools/flash-access/kb7-loader-reentry-campaign.py` derives both an install
sequence and a reverse sequence that restores the exact 32-MiB baseline.
`tools/flash-access/kb7-loader-reentry-executor.py` is a separate fixed-domain
executor for only that rederived campaign. It does not unlock or call the
general paired-firmware executor.

The fixed executor currently has:

- `LIVE_PROOF_CAMPAIGN_ENABLED = True` for only this pinned campaign;
- expected owner campaign identifier
  `3fa076a69bb04ab2ef11c9369d80976e293d1d57a52ddeb63f9d8d71b004d82f`;
- pinned supporting-source, policy and normalized executor-source hashes;
- no caller-selected offset, payload, CDB, operation index, retry, force or
  USB-device selector; and
- a dry-run default, with `--commit` admitted only after the independent
  campaign, source, policy and general-executor-lock checks pass.

Two distinct owner files were supplied outside the checkout. Each is exactly
33,554,432 bytes, they compare byte-for-byte equal, and both have SHA-256
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`.
The campaign was generated once and then independently rederived from those
inputs and the reviewed proof ELF. The exact owner-bound result is:

- proof full-image SHA-256
  `d08e8e32af512abf0d2a73248f88d08a5520348af64ad699a67194ee3db40bac`;
- 168 operations: 32 install plus 136 exact-stock restore;
- 148 fixed 512-byte programs and 20 fixed 4-KiB erases;
- exactly 20 operations in the one temporary Core-1 barrier sector at
  `0x00022000` and zero operations in the preserved boot regions;
- 169 exact command boundaries, 157,528 modeled byte-prefix states, 154,462
  opposite-barrier prefix states, 2,044 poison-prefix states and two rank-32
  sparse-gate proofs; and
- zero early loader-valid non-target command boundaries, exact proof-image
  closure after install and byte-exact baseline closure after restore.

Every saved operation descriptor was checked against an independently
constructed internal CDB and its exact payload hash. The private campaign,
proof-sector image and simulation remain outside the public repository.

## Why one stock Core-1 sector is temporarily touched

Changing only Core 0 would leave a difficult interruption case: an arbitrary
partial Core-0 rebuild might, in principle, accidentally satisfy its checksum
before the intended final commit. The campaign therefore establishes two
independent checksum barriers while rebuilding Core 0:

1. clear one reviewed erased bit in Core 0;
2. clear one reviewed erased bit in Core 1;
3. rebuild Core 0 with its final four-byte checksum gate left erased;
4. erase and program only the one poisoned Core-1 sector back to exact stock
   while Core 0 is still invalid; and
5. program the sparse Core-0 gate last.

The reverse campaign repeats the same structure while restoring stock Core 0.
Core 1 is exact stock at both stable targets; it is only an invalid barrier
during the middle of each campaign.

The simulator proves the following for the requested NOR-transition model:

- the first poison has only two distinct byte-prefix outcomes: the exact stable
  preimage or the one-bit-invalid postimage;
- every dense Core-0 and Core-1-sector prefix has the opposite core invalid;
- the final Core-0 gate is a rank-32 CRC transform, so only the exact four-byte
  target word reaches the declared checksum;
- no non-target command boundary has both application checksums valid;
- no operation overlaps `[0x00000000,0x00011000)`; and
- applying install then restore yields the exact original 32-MiB image.

This is a software proof over intended monotone bit transitions. It does not
model misaddressing, disturb, arbitrary analog torn-NOR behavior or a faulty
loader implementation. Those remain external-SPI recovery cases.

## Fixed executor protocol

The public CLI has only `preflight`, `step`, `validate-reentry`, `finalize` and
local-only `inspect` commands.

- `preflight` durably publishes `preflight_started` before constructing a USB
  backend, takes two exact full-chip reads, verifies the exact baseline and
  loader identity, strictly closes the clean BOT session, then publishes
  boundary zero.
- `step` durably publishes the exact operation intent before constructing a USB
  backend. It takes two exact pre-reads, executes one internally constructed
  fixed command, takes two exact post-reads, strictly closes, and only then
  publishes the next boundary.
- The install commit publishes `proof_installed`; no restore operation is
  authorized until a cold boot and `validate-reentry` succeed.
- `validate-reentry` consumes that authority before USB open. It requires the
  same bus/physical topology, a different USB enumeration address, two exact
  reads of the complete proof target and a strict close before publishing
  `restore_ready`. The new address supports re-enumeration but does not by
  itself prove what caused it; the observed cold boot and `10f5:5037` result are
  operator evidence.
- The last restore step publishes `complete`. `finalize` consumes it before USB
  open, verifies two exact stock full-chip reads, strictly closes and then
  clears the journal.

Any constructor, identity, BOT transport, checksum, exact-image or strict-close
anomaly after a terminal marker is visible leaves a non-authorizing journal and
requires external SPI. There is no ordinary intent reconciliation and no
automatic mutation retry. Atomic state outcomes that cannot be classified are
exit-4 local-inspection cases; that result authorizes no USB action.

## Owner-local campaign generation

The following remains offline. The output directory, sector image, simulation
and journal are private artifacts and must stay outside the checkout.

```text
make -C replacement_fw recovery-proof

python3 tools/flash-access/kb7-loader-reentry-campaign.py build \
  --baseline-a /path/to/first-exact-32MiB-baseline.bin \
  --baseline-b /path/to/second-exact-32MiB-baseline.bin \
  --proof-core0-elf replacement_fw/build/core0.elf \
  --campaign /path/to/new-private-loader-reentry-proof-campaign

python3 tools/flash-access/kb7-loader-reentry-campaign.py verify \
  --baseline-a /path/to/first-exact-32MiB-baseline.bin \
  --baseline-b /path/to/second-exact-32MiB-baseline.bin \
  --proof-core0-elf replacement_fw/build/core0.elf \
  --campaign /path/to/new-private-loader-reentry-proof-campaign
```

Both baselines must be distinct regular 33,554,432-byte files, byte-identical
to one another and SHA-256
`2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`.
Generation refuses any other stock layout or proof raw identity.

The offline review has now recorded the rederived campaign ID, exact operation
counts, proof full-image hash, fixed Core-1 barrier sector, every operation
CDB/payload hash and all simulation invariants. A separate source change has
now set the live boolean, refreshed the normalized executor, policy and
full-source pins, rerun private campaign verification, and updated the
machine-readable status. This authorizes only the exact fixed campaign
described here; it does not authorize a caller-selected firmware install or the
general paired-firmware executor.

## Authorized bounded hardware run

The exact pinned owner campaign is authorized for the following stop-gated
hardware run:

1. keep the rehearsed full-chip external-SPI restore available, with the
   external programmer physically disconnected from the powered keyboard;
2. require stable `10f5:5037`, matching baselines and a dry preflight;
3. commit preflight, then execute exactly one fixed step per process, checking
   every returned boundary;
4. stop at `proof_installed`, power down normally, and cold boot the proof;
5. require `10f5:5037` and run one fresh-process `validate-reentry`;
6. only after exact `restore_ready`, execute the fixed restore operations one
   at a time;
7. require `complete`, then run finalization;
8. capture a separate complete verifier read, require all declared region CRCs,
   SHA-256 and byte comparison to the baseline; and
9. only then cold boot and require `10f5:5038` plus normal keyboard operation.

An exit 3, terminal marker, unstable read, unexpected image, identity change or
strict-close failure prohibits every further USB command. Preserve the private
journal and use the already rehearsed external-SPI full-baseline restore. Never
leave the external programmer wired while it is unpowered.

## Proof boundary

A successful run would show, on this V1.22 unit, that one checksum-valid custom
Core 0 can execute the minimal SRAM relocation path and return to the untouched
stock USB loader, after which the fixed campaign can restore the exact stock
image. It would not authorize general firmware installation, prove arbitrary
application recovery, validate a power-cut or torn-NOR path, or make the stock
loader physically immutable. The general paired-firmware executor remains
mutation-locked, and external SPI remains the final recovery mechanism.
