# Project-owned input report schemas

These schemas prevent the earlier collision in which ID `0x03` represented two
different lengths. They describe the core1/client model only; the public tree
has no enabled USB controller, descriptor, VID, or PID.

| ID | Fixed size | Meaning |
|---:|---:|---|
| `0x04` | 21 bytes | byte 0 ID, byte 1 modifier bitmap, bytes 2–20 usage bitmap for usages 0–151 |
| `0x05` | 3 bytes | byte 0 ID, bytes 1–2 one little-endian consumer usage; zero releases |
| `0x06` | 64 bytes | byte 0 ID, byte 1 `0xfa`, byte 2 page, byte 3 sample count, bytes 4–63 samples/padding |
| `0x5c` | 64 bytes | versioned vendor-control report in `HOST-PROTOCOL.md` |

The analog stream uses page 0 for samples 0–59 and page 1 for samples 60–81.
Padding is zero. A future USB implementation must declare these exact IDs and
sizes in its report descriptor before enabling transmission.
