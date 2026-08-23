# Offline updater authentication — 2026-08-23

## Status and boundary

`tools/flash-access/kb7-updater-sign.py` implements detached Ed25519
authentication for the current V1.22 offline paired bundle. It has only
`sign`, `verify`, and public-key `fingerprint` commands. It imports no USB
library and exposes no execute, commit, device, address, payload, CDB, force,
or operation-selection option.

This closes a specific release-pipeline gap: a verifier with a separately
trusted public-key fingerprint can identify the publisher of one exact bundle.
It does **not** make that bundle installable. The raw bundle remains
`unsigned=true`, `execution_authorized=false`, and `flash_approved=false`; the
detached statement repeats that its signature is not installation
authorization. No project release key or trusted fingerprint is provisioned
in this repository yet.

## What is authenticated

Before signing or verifying, the tool calls the offline planner's complete
`verify_bundle()` path against two distinct, matching 32-MiB V1.22 captures.
That rechecks the source anchors, unchanged manifest and immutable ranges,
paired markers, balanced region checksums, canonical 161-operation order,
poison payload, exact target image, and independently reconstructed simulation.

The domain-separated signed statement then binds:

- the bundle format, schema and content ID;
- baseline and exact target full-image SHA-256 values;
- the paired-firmware identifier;
- name, byte length, and SHA-256 for all five exact bundle files;
- the Ed25519 public-key SPKI SHA-256; and
- the fail-closed offline/execution/flash policy.

The five files are `bundle.json`, `simulation.json`, both sector images, and
`poison-blocks.bin`. The detached JSON envelope must stay outside the bundle,
is created atomically without overwrite, and receives mode `0600`.

## Key and trust-root procedure

Key generation is intentionally not part of the KB7 tool. A release owner can
create an owner-local Ed25519 key with OpenSSL:

```sh
umask 077
openssl genpkey -algorithm Ed25519 -out /secure/offline/kb7-release-private.pem
openssl pkey -in /secure/offline/kb7-release-private.pem \
  -pubout -out /secure/offline/kb7-release-public.pem
chmod 600 /secure/offline/kb7-release-private.pem
```

The private key must be a regular, non-symlink file with no group or other
permissions. The current noninteractive tool deliberately fails on a key that
requires an interactive passphrase. Production key custody, backup, rotation,
revocation, and multi-party release approval remain policy work.

Print the candidate public-key fingerprint with:

```sh
python3 tools/flash-access/kb7-updater-sign.py fingerprint \
  --public-key /secure/offline/kb7-release-public.pem
```

A verifier must obtain and pin that 64-character fingerprint through a channel
independent of the bundle, signature envelope, and public-key download. Merely
computing the fingerprint from an untrusted key delivered beside the bundle
does not establish publisher identity.

## Signing

```sh
python3 tools/flash-access/kb7-updater-sign.py sign \
  --bundle /owner/path/to/bundle \
  --baseline-a /owner/path/to/fresh-read-a.bin \
  --baseline-b /owner/path/to/fresh-read-b.bin \
  --private-key /secure/offline/kb7-release-private.pem \
  --out /owner/path/kb7-updater-authentication-20260823.json
```

The output reports the bundle ID, signing-key SPKI fingerprint, and unchanged
false authorization flags. Planner rejection, a non-Ed25519 key, unsafe key
permissions, an existing output, or an output inside the bundle stops before
an envelope is published.

## Verification

```sh
python3 tools/flash-access/kb7-updater-sign.py verify \
  --bundle /owner/path/to/bundle \
  --baseline-a /owner/path/to/fresh-read-a.bin \
  --baseline-b /owner/path/to/fresh-read-b.bin \
  --public-key /secure/offline/kb7-release-public.pem \
  --trusted-key-sha256 PINNED_64_HEX_FINGERPRINT \
  --signature /owner/path/kb7-updater-authentication-20260823.json
```

Verification fails on a changed bundle file, baseline or descriptor; a wrong
or unpinned public key; a changed signature or statement; duplicate, unknown,
non-finite, oversized, binary, or symlinked envelope input; or any planner
invariant failure. Success means only `authenticated=true` for the exact
offline artifact.

## Public-tree and release limits

Private keys, generated envelopes, bundles, baselines, payloads, and full
captures remain owner-local and are denied by the public-tree policy by content,
schema/format, filename, or binary type. A future public release may include a
reviewed public key or fingerprint only after the trust-root and rotation policy
is approved. Until then, this is a tested authentication mechanism without a
project identity, not a signed project release and not an updater authorization.

The statement authenticates exact bundle bytes, not a source commit, build
environment, original ELF provenance, release time, release sequence, or
freshness. It supplies no rollback protection: a correctly signed older bundle
remains correctly signed. A real release process must separately bind reviewed
source/build provenance and define version, expiry/revocation, and anti-rollback
policy.
