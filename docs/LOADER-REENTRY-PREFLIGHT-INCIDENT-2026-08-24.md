# Loader-reentry proof preflight incident

Date: 2026-08-24

## Result

The first committed hardware action for the fixed loader-reentry campaign was
the executor's read-only preflight. It did not reach boundary zero. The old
executor reported two complete full-chip read progress passes and then returned
exit 3 with only the aggregate message `preflight transport, verification, or
close failed`. Its durable journal remained at `preflight_started`.

That result did not issue a flash program or erase command. The preflight
backend was mutation-incapable and admitted only loader identity and full-chip
read operations. No proof-install operation was attempted.

The old diagnostic discarded the phase and underlying exception, so the exact
failure cannot be recovered from the console transcript. The host kernel log
contains no device reset, disconnect or re-enumeration between the initial
`10f5:5037` enumeration and the later deliberate shutdown. This makes a
host-side strict-close or driver-reattachment result the leading hypothesis,
but it does not prove that hypothesis; a userspace read or exact-comparison
failure also need not appear in the kernel log.

## Independent flash evidence

After the stop, the owner held `MCU_RST`, used the already proven external SPI
setup at 1 MHz and made two independent complete 32-MiB reads. Both reads:

- had SHA-256
  `2b1472f47e957c6d6cd9e47911f454fabf50c5d6988d90884b5d6193d61fe02f`;
- compared byte-for-byte equal to one another; and
- compared byte-for-byte equal to the reviewed stock baseline.

No SPI write was needed. After the programmer was disconnected and the board
was cold-booted, `10f5:5038` returned and the owner confirmed normal keyboard
operation. The first HID enumeration attempt had one transient configuration-
descriptor timeout; the host retried immediately and bound every HID
interface. There is no evidence of persistent USB or flash damage.

## Corrective change

Proof mutation is relocked while this incident is investigated. The revised
executor permits only its exact read-only preflight and now:

- reports the failing phase as backend open, loader identity, first read,
  second read, exact read-pair verification, exact baseline verification,
  identity binding, strict close or final local publication;
- includes a bounded one-line underlying exception in the owner-local output;
- distinguishes transport/identity/close stops from read-pair or exact-baseline
  verification failures. The former require no more USB in that powered
  session and a power cycle before a new journal; SPI is optional. The latter
  require independent SPI verification, with a write only if that independent
  read actually differs from baseline;
- uses a proof-local strict-close implementation; and
- if driver reattachment returns only `NOT_FOUND` or `BUSY`, accepts the close
  only when a direct host-side query proves a kernel driver is already active.

Program, erase, re-entry validation and finalization remain hard-disabled in
this revision. A later read-only preflight may identify the old failure class
or show that the driver-state recheck resolves it. Neither outcome authorizes
the proof install; mutation requires a separate review and authorization
change.

## Proof boundary

This incident proves that the attempted preflight left this unit's flash
byte-exact stock, as independently read through external SPI. It does not prove
which old preflight phase failed, that every read-only USB anomaly is harmless,
or that the custom proof image can boot and re-enter `10f5:5037`.
