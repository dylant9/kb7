# Offline control host protocol

## Transport and compatibility

The project-defined wire model uses a 64-byte HID report with ID `0x5c`. The
firmware now implements the bidirectional endpoint/EP0 transport and a bounded
Core0→application mailbox. The public defaults still assign no USB VID/PID and
therefore do not attach or touch USB MMIO. A hardware profile must supply a
legally assigned identity and explicitly assert that the recovered controller
profile has passed board validation. The delivered PC app remains strictly
offline.

Compatibility choice:

- keep keyboard reports separate from the control plane;
- give analog/diagnostic data a separately declared schema and identifier;
- use explicit version, sequence, status, and CRC fields in control messages.

## 64-byte report

| Byte | Size | Field |
|---:|---:|---|
| 0 | 1 | report ID `5c` |
| 1 | 1 | protocol version `1` |
| 2 | 1 | kind: command=1, response=2, event=3 |
| 3 | 1 | opcode |
| 4 | 1 | flags |
| 5 | 1 | status |
| 6 | 2 | sequence, little-endian |
| 8 | 4 | transfer ID |
| 12 | 4 | byte offset |
| 16 | 4 | total object length |
| 20 | 4 | CRC-32 of the complete 36-byte padded payload field |
| 24 | 36 | payload |
| 60 | 4 | CRC-32 of bytes 1..59 |

Every malformed size/ID/version/CRC is rejected before opcode dispatch. Responses
mirror opcode, sequence and transfer ID. The response offset is the next expected
byte, enabling deterministic retry.

The region-1 application retains a command response while Core 0 reports its eight-entry IN queue
as busy or unavailable, and it does not consume the next mailbox command until
that response has been accepted into the IN queue. Keyboard, consumer and
gamepad state use the same retry path and coalesce to the newest state, so a
release/neutral state supersedes an unsent press. Consumer pulses retain their
required restore/release packet. Analog and widget-event telemetry is explicitly
latest-value/coalesced and is scheduled only when no control or response is
pending.

Core 0 also publishes a monotonic data-queue epoch whenever bus reset or USB
configuration changes discard endpoint state. The region-1 application observes that epoch and
replays its latest keyboard, consumer, gamepad, and analog state, including a
key or axis held unchanged across re-enumeration.

Acceptance into the Core-0 queue is the firmware-side delivery boundary; there
is no USB-level acknowledgement back to the region-1 application. A detach or bus reset after that
point can discard a queued response, so host software must timeout and retry the
same command. Ordered transfer responses report the next expected offset, making
WRITE retries deterministic; after a possibly completed COMMIT, the host should
READ the active store to resolve the result.

## Opcodes

| Opcode | Command |
|---:|---|
| 0x01 | query firmware/protocol version |
| 0x02 | query capabilities: geometry, limits, KBS1/KBP1 versions, both slot sizes, profile record/max size, feature flags |
| 0x10 | BEGIN transfer; total length and whole-object CRC in payload[0..3] |
| 0x11 | WRITE next chunk; offset must equal next expected offset |
| 0x12 | COMMIT; exact length and whole CRC must match, then atomic slot finalize |
| 0x13 | ABORT; discard only inactive transaction |
| 0x14 | READ active store in chunks |
| 0x15 | SELECT active screen for this runtime (`offset=u16 screen ID`) |
| 0x16 | FACTORY RESET both custom screen and profile stores; requires flags `a5`, transfer ID `0x4b423752`, payload prefix `RESETKB7` |
| 0x40 | device→host widget event; flags are down=0, move=1, up=2 |
| 0x41 | device→host action-bar edge; payload key index/state and flags state |
| 0x7e | reserved; returns `UNSUPPORTED` because no autonomous ROM/loader reset is proven |

Statuses: `0 OK`, `1 BAD_VERSION`, `2 BAD_CRC`, `3 BAD_LENGTH`, `4 BAD_STATE`,
`5 RANGE`, `6 STORAGE`, `7 UNSUPPORTED`.

The 0x02 response payload is: width/height (`u16,u16`), max screens/widgets
(`u8,u8`), screen-slot bytes (`u32`), KBS1 version, KBP1 version, max profile
count and protocol version (`u8` each), KBP1 record bytes (`u16`), profile-slot
bytes, maximum KBP1 object bytes and feature flags (`u32` each). Feature bits
0..4 advertise screen store, profile store, runtime screen selection, gamepad and
Hall telemetry respectively.

## Transfer state machine

```text
idle --BEGIN(valid size/id/crc)--> receiving
receiving --WRITE(exact next offset)--> receiving
receiving --COMMIT(exact length+CRC)--> verify inactive slot
verify --header state VALID (one-way bit clear)--> idle/new active generation
receiving --ABORT/reset/timeout--> idle/old slot untouched
any bad offset/id --> error response, state unchanged
```

For BEGIN/WRITE/COMMIT/ABORT/READ, flags select store `0=KBS1 screen` or
`1=KBP1 input/lighting profile`; the store selector must remain identical for
the complete transaction. COMMIT parses the selected complete object before setting the slot VALID and
then reads back and revalidates the finalized slot. READ returns up to 36 bytes
from the fully validated active slot and reports the next offset and total size.
SELECT is deliberately a screen-only runtime operation in v1; it does not
mutate flash. FACTORY RESET invalidates both screen headers and both profile
headers after its confirmation token.

Chunks are strictly ordered. A duplicate receives `BAD_STATE` plus the expected
offset; the host can resume from that offset. Transfer IDs prevent delayed packets
from an earlier session corrupting a new one. The firmware never erases the active
slot. Power loss at erase/header/payload checkpoints retains the previous valid
generation, verified in `test_storage.py`.

An active transfer expires after 5,000 ms without a successful BEGIN/WRITE
completion, using wrap-safe runtime milliseconds. ABORT must match the active
transfer ID and store; after expiry, a new BEGIN is accepted. BEGIN erases only
the inactive header sector. Later sectors are erased lazily as ordered WRITE
chunks reach them, bounding a command to at most one sector erase instead of
blocking input processing for a whole 2 MiB slot erase.

COMMIT makes the new object persistent and selects its generation for the next
boot. Firmware v1 does not hot-reload a committed screen/profile; reboot after a
successful COMMIT to apply it. Runtime SELECT remains the exception and changes
the current screen without mutating flash.

## Widget events

For opcode `0x40`, sequence carries widget ID, `total_length` carries screen ID,
`offset` carries the signed/current value's low 16 bits, and optional event data
uses payload. Host events are advisory; device actions never wait for host ACK.

## Offline tooling

`kb7studio.protocol.transfer_reports()` produces the exact reports and accepts
a screen/profile store selector. The
`OfflineReceiver` uses the device's separate screen/profile capacities and the
same strict `KBS1`/`KBP1` validators at COMMIT while exercising ACK/order/CRC
behavior. CLI `protocol-plan` writes
hex reports to JSON and accepts `--store screen|profile`; it never opens a
device.
