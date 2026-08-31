# Loader-reentry proof preflight validation

Date: 2026-08-24

## Result

The revised fixed-campaign executor completed its committed read-only
preflight on the V1.22 development unit. It opened `10f5:5037`, bound USB
topology `3-2.2` at session address 9, took two complete 32-MiB reads through
the loader, verified both reads byte-for-byte against the reviewed stock
baseline, and completed the revised strict close. The durable journal reached
`boundary_verified` at boundary zero.

The observed identities were:

- campaign SHA-256
  `3fa076a69bb04ab2ef11c9369d80976e293d1d57a52ddeb63f9d8d71b004d82f`;
- baseline SHA-256
  `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`;
- proof full-image SHA-256
  `d08e8e32af512abf0d2a73248f88d08a5520348af64ad699a67194ee3db40bac`;
- executor source SHA-256
  `e43f65a91755458b257230be042029fd0a7bf75eb7f9629a6986a5757f678dd3`;
- loader-window SHA-256
  `9cc33333a88641b633bb5a4c0d55425c757e0fbdbe70eb99e9a9e40b76378a56`;
  and
- loader fingerprint SHA-256
  `99e75493ef2f627b072560ef7ee45f3c01648eca715ce03a4001727eace9e7c6`.

The executor explicitly had proof mutation disabled during this run. No
program or erase CDB was authorized or sent. Local-only inspection confirmed
the exact boundary-zero journal. The owner then power-cycled normally,
observed `10f5:5038`, and confirmed normal keyboard operation. No external-SPI
read or write was required after this successful preflight.

## Relationship to the first incident

The first preflight attempt used an older aggregate error path and stopped
before boundary zero. Two later external-SPI reads proved that attempt had
left flash byte-exact stock. The revised preflight's success shows that the
phase-reporting transport and revised strict-close policy work on this unit.
It makes the old close/driver-reattachment behavior the leading explanation,
but cannot recover the discarded old exception and therefore does not prove
the historical root cause.

## Authorization result

The successful diagnostic closes the read-only blocker that caused proof
mutation to be relocked. A separately hash-pinned follow-up revision therefore
authorizes only this exact 168-operation proof-install/exact-stock-restore
campaign. That revision changes the executor source identity, so this
validation journal cannot authorize its writes: a new private journal and a
fresh exact preflight are required under the write-enabled revision.

The general paired-firmware executor remains mutation-locked. This result does
not prove the custom Core-0 image boots, that it returns to the preserved
loader, that the proof image reads back exactly, or that stock restoration
succeeds. Those remain the bounded hardware campaign's stop-gated objectives,
with external SPI as the final recovery path.
