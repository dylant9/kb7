# KB7 declarative screen format (`KBS1`)

## Goals and byte order

The format is compact, deterministic, little-endian, versioned, length-bounded
and CRC-protected. It contains no pointers. Firmware validates every range and
count before rendering, and falls back to a compiled safe screen on any error.
The PC compiler and C parser share golden layout tests. Their acceptance
behavior is also compared over every truncation and a deterministic mutation
corpus in `test_c_parser.py`.

Limits in version 1: 16 screens, 128 widgets, 480×800 geometry, UTF-8 string
pool. The clean-room device font renders ASCII letters/numbers and fallback
glyphs; the PC simulator renders the complete UTF-8 label.

## Header — 48 bytes

| Offset | Type | Field |
|---:|---|---|
| 0x00 | u32 | magic `0x3153424b` (`KBS1`) |
| 0x04 | u16 | version `1` |
| 0x06 | u16 | header length `48` |
| 0x08 | u32 | exact total length |
| 0x0c | u32 | zlib/IEEE CRC-32 of bytes `[header_length,total_length)` |
| 0x10 | u16 | screen count |
| 0x12 | u16 | boot screen ID |
| 0x14 | u16 | total widget count |
| 0x16 | u16 | flags (zero in v1) |
| 0x18 | u32 | screen-record offset |
| 0x1c | u32 | widget-record offset |
| 0x20 | u32 | string-pool offset |
| 0x24 | u32 | string-pool length |
| 0x28 | u32 | format features (must be zero) |
| 0x2c | u32 | reserved (must be zero) |

Canonical layout is header → all screen records → all widget records → string
pool. Non-canonical gaps/overlaps are rejected to keep the parser surface small.

## Screen record — 16 bytes

`u16 id, u16 first_widget, u16 widget_count, u16 background_rgb565,
u32 name_offset, u16 name_length, u16 flags`. Flags are zero in v1.

String offsets are relative to the start of the string pool. Widget ranges index
the global widget array and must fit it exactly.

## Widget record — 40 bytes

| Offset | Type | Field |
|---:|---|---|
| 0x00 | u16 | unique widget ID |
| 0x02 | u8 | type |
| 0x03 | u8 | flags |
| 0x04..0x0b | i16 ×4 | x, y, width, height |
| 0x0c..0x0f | u16 ×2 | foreground/background RGB565 |
| 0x10..0x15 | i16 ×3 | minimum, maximum, value |
| 0x16 | u16 | navigation target screen |
| 0x18 | u8 | action opcode |
| 0x19 | u8 | action flags |
| 0x1a | u16 | action argument 0 |
| 0x1c | u32 | action argument 1 |
| 0x20 | u32 | text offset |
| 0x24 | u16 | text length |
| 0x26 | u16 | reserved zero |

Widget and action flags are zero in v1. Non-navigation actions require a zero
target screen. Argument widths and widget ranges are checked against each
action's behavior (for example brightness 0–100, actuation 0–255, Rapid Trigger
0/1 with byte-sized deltas, and HID bitmap/modifier usages only).

Widget types: `1 label`, `2 button`, `3 slider`, `4 toggle`, `5 gauge`.

## Action opcodes

| Opcode | Name | Arguments/behavior |
|---:|---|---|
| 0x00 | none | no side effect |
| 0x01 | navigate | `target_screen` |
| 0x10 | RGB color | `arg1=0x00RRGGBB`; SNC packet builder updates active LEDs |
| 0x11 | RGB effect | `arg0=0..4`: static, gradient, aurora, reactive, heatmap |
| 0x12 | brightness | current widget value 0..100; RGB and panel backlight |
| 0x20 | profile | `arg0=profile` |
| 0x21 | actuation | current value 0..255 in SNC-local Hall policy |
| 0x22 | Rapid Trigger | value 0/1, `arg0=press delta`, low byte of `arg1=release delta` |
| 0x30 | HID key | `arg0=usage` |
| 0x31 | media key | `arg0=consumer usage` |
| 0x40 | host event | sends widget ID, screen ID, and current value |

Actuation/RT deliberately do not send an invented MCU2 command.

## JSON authoring form

`pc_app/samples/offline-example.json` is canonical. Colors use `#rrggbb`; the
compiler quantizes to RGB565. Unknown fields are ignored only when harmless;
wrong types, duplicate IDs, out-of-bounds geometry, invalid ranges, unknown
widget/action names, and missing boot screens are errors.

```sh
cd pc_app
PYTHONPATH=. python3 -m kb7studio.cli compile samples/offline-example.json example.kbs
PYTHONPATH=. python3 -m kb7studio.cli inspect neon.kbs
```

The browser app implements the same layout and can import/export both forms.

## Fail-safe/version policy

- Wrong magic, header length, version, total length, CRC, count, offset, string
  range, geometry, reserved field, or opcode rejects the whole store.
- No partial rendering of a corrupt tree occurs.
- Unsupported major version rejects and uses the built-in safe screen.
- Future compatible additions require a new feature bit plus a parser that
  explicitly understands it; v1 requires feature bits zero.
- Slot CRC in `STORAGE-MAP.md` independently protects the complete `.kbs` blob.
