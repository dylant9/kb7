# KB7 offline keyboard profile (`kb7-profile-v1`)

## Purpose

`kb7-profile-v1` is the editable project artifact used by KB7 Studio. It keeps
the display document, RGB design, Hall-switch policy, and intended analog-axis
mapping together without implying live device access.

The browser exports JSON and the Python `profile-check` command validates and
canonicalizes it. Only the embedded `screen_document` currently compiles to the
firmware-consumed `KBS1` binary. Lighting, switch, and analog sections are
staged control intent for the host/firmware integration that follows hardware
validation.

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

`name` is non-empty UTF-8 text of at most 64 bytes. `screen_document` must pass
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

The UI defaults to 3.2 mm as a configurable offline modeling range. Firmware owns actuation
policy on the SNC; MCU2 supplies normalized Hall samples.

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

After deadzone removal, the simulator normalizes magnitude to saturation,
applies the selected curve, then maps it to `-32767..32767`. Opposing keys
cancel. The Arrow preset uses four logical directional keys exercised by the
1,519-packet replay: Left `0x27`, Up `0x3a`, Down `0x3b`, Right `0x4f`.

## Capability record

The canonical validator writes this exact record:

```json
{
  "hall_keymap": "device-mapping-not-included",
  "rgb_position_mapping": "pending_hardware",
  "analog_hid_output": "planned_unverified",
  "device_io": false
}
```

Consumers must not upgrade any of these claims merely because a profile parses.
Hardware integration evidence and a redistributable mapping are required to
change either pending state.
