# KB7 Studio host protocol

## Transport and compatibility

The project-defined wire model uses a 64-byte HID-shaped message and reserves
logical report ID `0x5c`. The public tree assigns no USB VID/PID and contains no
live USB transport. A future adapter may bind the message to an independently
licensed transport after hardware and identity review. The delivered PC app is
strictly offline.

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

## Opcodes

| Opcode | Command |
|---:|---|
| 0x01 | query firmware/protocol version |
| 0x02 | query capabilities: 480×800, format version, slot/storage sizes, widget limits |
| 0x10 | BEGIN transfer; total length and whole-object CRC in payload[0..3] |
| 0x11 | WRITE next chunk; offset must equal next expected offset |
| 0x12 | COMMIT; exact length and whole CRC must match, then atomic slot finalize |
| 0x13 | ABORT; discard only inactive transaction |
| 0x14 | READ active store in chunks |
| 0x15 | SELECT active/boot screen |
| 0x16 | FACTORY RESET custom screen store; built-in screen remains |
| 0x40 | device→host widget event |
| 0x7e | enter loader; additionally requires a second confirmation token/session |

Statuses: `0 OK`, `1 BAD_VERSION`, `2 BAD_CRC`, `3 BAD_LENGTH`, `4 BAD_STATE`,
`5 RANGE`, `6 STORAGE`, `7 UNSUPPORTED`.

## Transfer state machine

```text
idle --BEGIN(valid size/id/crc)--> receiving
receiving --WRITE(exact next offset)--> receiving
receiving --COMMIT(exact length+CRC)--> verify inactive slot
verify --header state VALID (one-way bit clear)--> idle/new active generation
receiving --ABORT/reset/timeout--> idle/old slot untouched
any bad offset/id --> error response, state unchanged
```

Chunks are strictly ordered. A duplicate receives `BAD_STATE` plus the expected
offset; the host can resume from that offset. Transfer IDs prevent delayed packets
from an earlier session corrupting a new one. The firmware never erases the active
slot. Power loss at erase/header/payload checkpoints retains the previous valid
generation, verified in `test_storage.py`.

## Widget events

For opcode `0x40`, sequence carries widget ID, `total_length` carries screen ID,
`offset` carries the signed/current value's low 16 bits, and optional event data
uses payload. Host events are advisory; device actions never wait for host ACK.

## Offline tooling

`kb7studio.protocol.transfer_reports()` produces the exact reports and
`OfflineReceiver` exercises ACK/order/CRC behavior. CLI `protocol-plan` writes
hex reports to JSON; it never opens a device.
