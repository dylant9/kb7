# KB7 offline keyboard profile (`kb7-profile-v1`)

## Purpose

`kb7-profile-v1` is the editable project artifact used by Offline Control Studio. It keeps
the display document, RGB design, Hall-switch policy, and intended analog-axis
mapping together without implying live device access.

The browser exports JSON and the Python `profile-check` command validates and
canonicalizes it. `profile-compile` now compiles the lighting, switch and analog
sections into the firmware-consumed `KBP1` container. The embedded
`screen_document` remains a separate `KBS1` object. The compiler deliberately
rejects per-key RGB until logical keys have been physically correlated with LED
controller channels.

## Top-level object

```json
{
  "format": "kb7-profile-v1",
  "name": "Neon Control",
  "screen_document": {"format": "kb7-screen-v1"},
  "lighting": {},
  "switches": {},
  "analog": {},
  "capabilities": {}
}
```

`name` is non-empty UTF-8 text of at most 63 bytes. `screen_document` must pass
the complete `KBS1` compiler validation.

## Lighting

```json
{
  "enabled": true,
  "effect": "aurora",
  "brightness": 68,
  "speed": 42,
  "direction": "east",
  "primary": "#42efff",
  "secondary": "#9d5cff",
  "reactive": "#b5ffcb",
  "per_key": {"W": "#b5ffcb"}
}
```

- `effect`: `static`, `gradient`, `aurora`, `reactive`, or `heatmap`.
- `brightness` and `speed`: integer percent in `0..100`.
- `direction`: `east`, `west`, `north`, `south`, or `radial`.
- colors: strict `#rrggbb` strings.
- `per_key`: zero or more logical key names mapped to colors.

`per_key` is currently a logical preview. The clean-room RGB driver can address
stable positions `0..111` and knows which 101 positions are populated, but the
physical key legends for those positions are still `pending_hardware`.

## Hall switches

```json
{
  "travel_mm": 3.2,
  "actuation_mm": 1.6,
  "rapid_trigger": true,
  "rapid_press_delta_mm": 0.15,
  "rapid_release_delta_mm": 0.15,
  "per_key": {
    "W": {"actuation_mm": 1.0, "rapid_trigger": true}
  }
}
```

- travel is accepted in `0.5..6.0 mm`;
- actuation is accepted in `0.1..travel_mm`;
- Rapid Trigger deltas are accepted in `0.05..1.5 mm`; and
- per-key entries may only name supported logical ANSI keys or Fn
  candidate.

The UI accepts a wider simulation range, but `KBP1` compilation currently
requires 3.2 mm because the recovered firmware model has 33 levels (`0..32`,
0.1 mm each). Firmware owns actuation policy on the SNC; MCU2 supplies 82 raw
Hall samples, which the input pipeline converts with the recovered monotonic
lookup table.

`KBP1` stores travel values in 0.1 mm units. Compilation uses decimal round-half-
up quantization: for example 0.05→0.1, 0.15→0.2, and 0.25→0.3 mm. This avoids
language-dependent binary-float/banker's-rounding behavior.

## Analog axes

```json
{
  "enabled": true,
  "output": "gamepad_left_stick",
  "curve": "linear",
  "deadzone_mm": 0.12,
  "saturation_mm": 3.2,
  "smoothing": 2,
  "invert_x": false,
  "invert_y": false,
  "digital_passthrough": true,
  "bindings": {
    "x_negative": "LEFT",
    "x_positive": "RIGHT",
    "y_negative": "UP",
    "y_positive": "DOWN"
  }
}
```

- `output`: `gamepad_left_stick`, `gamepad_right_stick`, or
  `gamepad_triggers`;
- `curve`: `linear`, `exponential`, or `s_curve`;
- `smoothing`: integer `0..10`;
- deadzone must be below saturation, and saturation cannot exceed configured
  switch travel; and
- all four bindings must be distinct logical keys.

After deadzone removal, both simulator and firmware normalize magnitude to saturation,
applies the selected curve, then maps it to `-32767..32767`. Opposing keys
cancel. The Arrow preset uses the recovered logical routing table: Left
`0x27`, Up `0x3a`, Down `0x3b`, Right `0x4f`. Physical-layout validation remains
a hardware gate.

Firmware emits the result as HID report `0x07` (buttons, hat, four signed
16-bit axes and two triggers). The independent `0x06` report remains a 64-byte
paged Hall telemetry report.

## `KBP1` binary container

`KBP1` is a fixed-layout, little-endian format designed for strict validation
without dynamic allocation:

- 48-byte header: magic `KBP1`, version/header/total lengths, body CRC-32,
  profile count `1..5`, active slot, fixed record size, flags and zero reserved
  bytes;
- one to five 1,792-byte records;
- each record contains a NUL-terminated UTF-8 name, layout/mode, global
  lighting state, 85 four-byte Hall records, four by 85 four-byte action
  records, and the analog configuration; and
- exact total length, canonical offsets, enum/range values, reserved bits,
  UTF-8, CRC, actions and the complete runtime profile are validated before a
  flash slot can become `VALID`.

The A/B profile slots are `0x01c00000` and `0x01c38000`, each `0x38000` bytes.
They were relocated after full-chip reads proved that the earlier tail assignment
overlapped stock configuration/upload partitions.
Selection validates both the slot header and complete payload CRC, then the
runtime parser falls back to the older generation if the newest payload is
corrupt or semantically invalid.

### Layout and action-table authoring

A singular `kb7-profile-v1` may include an optional `firmware` object. It is
preserved by `profile-check` and consumed by `profile-compile`:

```json
{
  "layout_variant": 1,
  "initial_mode": "game",
  "actions": {
    "game": {
      "A": {"type": "keyboard", "usage": "B"},
      "logical:80": {"type": "consumer", "usage": 233}
    },
    "easy_shift": {"A": {"type": "none"}}
  }
}
```

`layout_variant` is `0..3`; recovered variants `0`, `2`, and `3` use the
80-selector route while `1` uses the alternate 82-selector route. Initial mode
is `primary`, `game`, or `easy_shift`. Action-table modes are those three plus
`fn1`. Action types are `transparent`, `none`, `keyboard`, `consumer`, and
`momentary_fn1`. Keyboard usages may be a known key name or a numeric HID usage;
consumer usages are nonzero 16-bit integers. `logical:0` through `logical:84`
provide explicit access to recovered selectors whose physical legends remain
unverified. Primary Fn is always validated as momentary FN1 and cannot be
rebound to a host usage.

To emit multiple runtime slots, `profile-compile` also accepts the following
set envelope. This block is deliberately schematic: the abbreviated profile
entries are **not** valid standalone input. Replace each entry with a complete
`kb7-profile-v1` document such as `pc_app/samples/offline-example-profile.json`.

```json
{
  "format": "kb7-profile-set-v1",
  "active_profile": 1,
  "profiles": [
    {"format": "kb7-profile-v1", "name": "Primary"},
    {"format": "kb7-profile-v1", "name": "Game"}
  ]
}
```

Each nested profile contains the complete screen/lighting/switch/analog fields
described above. The set contains one to five profiles and the active index must
name one of them. The browser edits a singular profile; the versioned set and
full layer table are deliberately available through JSON and the offline CLI.

```sh
PYTHONPATH=pc_app python3 -m kb7studio.cli profile-compile \
  pc_app/samples/offline-example-profile.json example.kbp
PYTHONPATH=pc_app python3 -m kb7studio.cli profile-inspect example.kbp
PYTHONPATH=pc_app python3 -m kb7studio.cli protocol-plan \
  --store profile example.kbp profile-transfer.json
```

## Capability record

The canonical validator writes this exact record:

```json
{
  "hall_keymap": "implemented-hardware-unverified",
  "rgb_position_mapping": "pending_hardware",
  "analog_hid_output": "implemented-hardware-unverified",
  "device_io": false
}
```

The capability record describes the offline editor's hardware claims and is
kept conservative. The firmware contains a recovered logical routing/usage
model and an implemented gamepad report, but neither has been validated on the
physical board. Consumers must not upgrade these claims merely because a
profile parses.
