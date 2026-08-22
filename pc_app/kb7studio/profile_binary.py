"""Compiler/parser for the firmware's fixed-size KBP1 profile container."""

from __future__ import annotations

import struct
import zlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .profile import ProfileFormatError, canonical_profile

MAGIC = 0x3150424B  # KBP1
VERSION = 1
PROFILE_SET_FORMAT = "kb7-profile-set-v1"
HEADER = struct.Struct("<IHHIIBBHII20s")
RECORD_SIZE = 1792
PROFILE_COUNT_MAX = 5
NAME_BYTES = 64
LOGICAL_KEYS = 85
MODES = 4
FN_LOGICAL_KEY = 0x4E
FN1_MODE = 3
MODE_NAMES = {"primary": 0, "game": 1, "easy_shift": 2, "fn1": 3}
INITIAL_MODES = {"primary": 0, "game": 1, "easy_shift": 2}
ACTION_KINDS = {
    "transparent": 0, "none": 1, "keyboard": 2,
    "consumer": 3, "momentary_fn1": 4,
}

EFFECTS = {"static": 0, "gradient": 1, "aurora": 2, "reactive": 3, "heatmap": 4}
DIRECTIONS = {"east": 0, "west": 1, "north": 2, "south": 3, "radial": 4}
OUTPUTS = {"gamepad_left_stick": 0, "gamepad_right_stick": 1, "gamepad_triggers": 2}
CURVES = {"linear": 0, "exponential": 1, "s_curve": 2}

# Recovered selector-to-usage table. It is an interoperability fact, not copied
# source code, and is shared with replacement_fw/drivers/keymap.c.
DEFAULT_USAGES = bytes.fromhex(
    "29 1f 39 64 3b 21 07 06 3e 25 0c 05 40 27 0f 37 43 2a 28 e4 "
    "3a 2b 04 1d 3c 22 09 19 3f 17 0b 11 41 2d 33 38 44 2f e5 50 "
    "35 14 16 e0 3d 08 0a e2 23 1c 0d 10 42 12 34 e6 45 30 52 "
    "51 1e 1a e1 e3 20 15 1b 2c 24 18 0e 36 26 13 32 65 2e 31 "
    "f1 4f 8a 87 8b 88 89"
)

KEY_USAGES = {
    "ESC": 0x29, "F1": 0x3A, "F2": 0x3B, "F3": 0x3C, "F4": 0x3D,
    "F5": 0x3E, "F6": 0x3F, "F7": 0x40, "F8": 0x41, "F9": 0x42,
    "F10": 0x43, "F11": 0x44, "F12": 0x45, "GRAVE": 0x35,
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "MINUS": 0x2D, "EQUAL": 0x2E, "BACKSPACE": 0x2A, "TAB": 0x2B,
    "Q": 0x14, "W": 0x1A, "E": 0x08, "R": 0x15, "T": 0x17,
    "Y": 0x1C, "U": 0x18, "I": 0x0C, "O": 0x12, "P": 0x13,
    "LEFTBRACE": 0x2F, "RIGHTBRACE": 0x30, "BACKSLASH": 0x31,
    "CAPSLOCK": 0x39, "A": 0x04, "S": 0x16, "D": 0x07, "F": 0x09,
    "G": 0x0A, "H": 0x0B, "J": 0x0D, "K": 0x0E, "L": 0x0F,
    "SEMICOLON": 0x33, "APOSTROPHE": 0x34, "ENTER": 0x28,
    "LEFTSHIFT": 0xE1, "Z": 0x1D, "X": 0x1B, "C": 0x06, "V": 0x19,
    "B": 0x05, "N": 0x11, "M": 0x10, "COMMA": 0x36, "DOT": 0x37,
    "SLASH": 0x38, "RIGHTSHIFT": 0xE5, "LEFTCTRL": 0xE0,
    "LEFTMETA": 0xE3, "LEFTALT": 0xE2, "SPACE": 0x2C, "RIGHTALT": 0xE6,
    "FN": 0xF1, "COMPOSE": 0x65, "RIGHTCTRL": 0xE4, "LEFT": 0x50,
    "UP": 0x52, "DOWN": 0x51, "RIGHT": 0x4F,
}
USAGE_TO_LOGICAL = {usage: logical for logical, usage in enumerate(DEFAULT_USAGES)}


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _color(value: str) -> bytes:
    return bytes.fromhex(value[1:])


def _travel(value: float, name: str, *, allow_zero: bool = False) -> int:
    # KBP1 stores tenths of a millimetre. Decimal(str(...)) makes ties explicit:
    # 0.05 -> 0.1, 0.15 -> 0.2, 0.25 -> 0.3 (round half up).
    result = int((Decimal(str(value)) * 10).quantize(Decimal("1"),
                                                     rounding=ROUND_HALF_UP))
    minimum = 0 if allow_zero else 1
    if not minimum <= result <= 32:
        raise ProfileFormatError(f"{name} cannot be represented by the 0..3.2 mm Hall model")
    return result


def _logical(name: str) -> int:
    usage = KEY_USAGES[name]
    try:
        return USAGE_TO_LOGICAL[usage]
    except KeyError as exc:
        raise ProfileFormatError(f"{name} is not present in the recovered 85-key logical map") from exc


def _logical_reference(value: Any) -> int:
    if not isinstance(value, str):
        raise ProfileFormatError("firmware action keys must be logical key names")
    if value.startswith("logical:"):
        try:
            logical = int(value[8:], 10)
        except ValueError as exc:
            raise ProfileFormatError(f"invalid logical selector {value!r}") from exc
        if not 0 <= logical < LOGICAL_KEYS:
            raise ProfileFormatError(f"logical selector {value!r} is outside 0..84")
        return logical
    try:
        return _logical(value)
    except (KeyError, ProfileFormatError) as exc:
        raise ProfileFormatError(f"unknown firmware action key {value!r}") from exc


def _default_actions() -> bytes:
    records = bytearray()
    for mode in range(MODES):
        for usage in DEFAULT_USAGES:
            if mode != 0:
                records.extend(struct.pack("<HBB", 0, 0, 0))  # transparent
            elif usage == 0xF1:
                records.extend(struct.pack("<HBB", 0, 4, 3))  # momentary FN1
            elif 0 < usage < 152 or 0xE0 <= usage <= 0xE7:
                records.extend(struct.pack("<HBB", usage, 2, 0))
            else:
                records.extend(struct.pack("<HBB", 0, 1, 0))
    return bytes(records)


def _action_record(value: Any, logical: int) -> bytes:
    if not isinstance(value, dict) or "type" not in value:
        raise ProfileFormatError("firmware actions must be objects with a type")
    action_type = value["type"]
    if not isinstance(action_type, str) or action_type not in ACTION_KINDS:
        raise ProfileFormatError(f"unsupported firmware action type {action_type!r}")
    allowed = {"type", "usage"} if action_type in ("keyboard", "consumer") else {"type"}
    if set(value) - allowed:
        raise ProfileFormatError("firmware action has unknown fields")
    kind = ACTION_KINDS[action_type]
    code = 0
    argument = 0
    if action_type == "keyboard":
        usage_value = value.get("usage")
        if isinstance(usage_value, str):
            if usage_value not in KEY_USAGES:
                raise ProfileFormatError(f"unknown keyboard usage name {usage_value!r}")
            code = KEY_USAGES[usage_value]
        elif isinstance(usage_value, int) and not isinstance(usage_value, bool):
            code = usage_value
        else:
            raise ProfileFormatError("keyboard action usage must be a key name or integer")
        if logical == FN_LOGICAL_KEY or not (0 < code < 152 or 0xE0 <= code <= 0xE7):
            raise ProfileFormatError("keyboard action usage/logical key is invalid")
    elif action_type == "consumer":
        usage_value = value.get("usage")
        if (not isinstance(usage_value, int) or isinstance(usage_value, bool) or
                not 0 < usage_value <= 0xFFFF or logical == FN_LOGICAL_KEY):
            raise ProfileFormatError("consumer action usage/logical key is invalid")
        code = usage_value
    elif action_type == "momentary_fn1":
        if logical != FN_LOGICAL_KEY:
            raise ProfileFormatError("momentary_fn1 is only valid on the Fn logical key")
        argument = FN1_MODE
    return struct.pack("<HBB", code, kind, argument)


def _firmware_fields(document: dict[str, Any]) -> tuple[int, int, bytes]:
    firmware = document.get("firmware", {})
    if not isinstance(firmware, dict) or set(firmware) - {
            "layout_variant", "initial_mode", "actions"}:
        raise ProfileFormatError("firmware must contain only layout_variant/initial_mode/actions")
    layout = firmware.get("layout_variant", 0)
    if not isinstance(layout, int) or isinstance(layout, bool) or not 0 <= layout <= 3:
        raise ProfileFormatError("firmware.layout_variant must be an integer in 0..3")
    initial_name = firmware.get("initial_mode", "primary")
    if not isinstance(initial_name, str) or initial_name not in INITIAL_MODES:
        raise ProfileFormatError("firmware.initial_mode must be primary/game/easy_shift")
    actions_value = firmware.get("actions", {})
    if not isinstance(actions_value, dict) or set(actions_value) - set(MODE_NAMES):
        raise ProfileFormatError("firmware.actions contains an unknown mode")
    actions = bytearray(_default_actions())
    for mode_name, overrides in actions_value.items():
        if not isinstance(overrides, dict):
            raise ProfileFormatError(f"firmware.actions.{mode_name} must be an object")
        mode = MODE_NAMES[mode_name]
        seen: set[int] = set()
        for key_name, action in overrides.items():
            logical = _logical_reference(key_name)
            if logical in seen:
                raise ProfileFormatError("firmware action aliases the same logical key twice")
            seen.add(logical)
            record = _action_record(action, logical)
            offset = (mode * LOGICAL_KEYS + logical) * 4
            actions[offset:offset + 4] = record
    primary_fn = struct.unpack_from("<HBB", actions, FN_LOGICAL_KEY * 4)
    if primary_fn != (0, ACTION_KINDS["momentary_fn1"], FN1_MODE):
        raise ProfileFormatError("firmware primary Fn action must remain momentary_fn1")
    return layout, INITIAL_MODES[initial_name], bytes(actions)


def _compile_record(document: dict[str, Any]) -> bytes:
    profile = canonical_profile(document)
    name = profile["name"].encode("utf-8")
    if len(name) >= NAME_BYTES:
        raise ProfileFormatError("profile.name must leave room for a NUL terminator")
    if profile["switches"]["travel_mm"] != 3.2:
        raise ProfileFormatError("firmware KBP1 profiles currently require travel_mm to be 3.2")
    if profile["lighting"]["per_key"]:
        raise ProfileFormatError(
            "per-key RGB cannot be compiled until logical keys are correlated with 112 RGB positions"
        )

    lighting = profile["lighting"]
    lighting_wire = bytes((
        int(lighting["enabled"]), EFFECTS[lighting["effect"]], lighting["brightness"],
        lighting["speed"], DIRECTIONS[lighting["direction"]],
    )) + _color(lighting["primary"]) + _color(lighting["secondary"]) + _color(lighting["reactive"])

    switches = profile["switches"]
    default_hall = (
        _travel(switches["actuation_mm"], "switches.actuation_mm"),
        _travel(switches["rapid_press_delta_mm"], "switches.rapid_press_delta_mm"),
        _travel(switches["rapid_release_delta_mm"], "switches.rapid_release_delta_mm"),
        int(switches["rapid_trigger"]),
    )
    hall = [default_hall for _ in range(LOGICAL_KEYS)]
    for key, override in switches["per_key"].items():
        logical = _logical(key)
        hall[logical] = (
            _travel(override["actuation_mm"], f"switches.per_key.{key}.actuation_mm"),
            default_hall[1], default_hall[2], int(override["rapid_trigger"]),
        )
    hall_wire = b"".join(bytes(record) for record in hall)

    analog = profile["analog"]
    analog_flags = (int(analog["invert_x"]) | (int(analog["invert_y"]) << 1) |
                    (int(analog["digital_passthrough"]) << 2))
    analog_wire = bytes((
        int(analog["enabled"]), OUTPUTS[analog["output"]], CURVES[analog["curve"]],
        _travel(analog["deadzone_mm"], "analog.deadzone_mm", allow_zero=True),
        _travel(analog["saturation_mm"], "analog.saturation_mm"), analog["smoothing"],
        analog_flags,
        *(_logical(analog["bindings"][axis]) for axis in
          ("x_negative", "x_positive", "y_negative", "y_positive")),
        0,
    ))
    layout, initial_mode, actions_wire = _firmware_fields(profile)
    record = (name + b"\0" * (NAME_BYTES - len(name)) +
              bytes((layout, initial_mode)) + lighting_wire +
              hall_wire + actions_wire + analog_wire)
    if len(record) != RECORD_SIZE:
        raise AssertionError(f"internal KBP1 record size mismatch: {len(record)}")
    return record


def compile_profile_binary(document: dict[str, Any]) -> bytes:
    """Compile one profile or a versioned one-to-five profile set to KBP1."""

    if not isinstance(document, dict):
        raise ProfileFormatError("profile input must be an object")
    if document.get("format") == PROFILE_SET_FORMAT:
        if set(document) - {"format", "active_profile", "profiles"}:
            raise ProfileFormatError("profile set has unknown top-level fields")
        profiles = document.get("profiles")
        active = document.get("active_profile")
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= PROFILE_COUNT_MAX:
            raise ProfileFormatError("profile set must contain 1..5 profiles")
        if (not isinstance(active, int) or isinstance(active, bool) or
                not 0 <= active < len(profiles)):
            raise ProfileFormatError("profile set active_profile is out of range")
        records = [_compile_record(profile) for profile in profiles]
    else:
        profiles = [document]
        active = 0
        records = [_compile_record(document)]
    body = b"".join(records)
    header = HEADER.pack(MAGIC, VERSION, HEADER.size, HEADER.size + len(body), _crc32(body),
                         len(records), active, RECORD_SIZE, HEADER.size, 0, b"\0" * 20)
    return header + body


def _validate_record(record: bytes) -> str:
    raw_name = record[:64]
    if b"\0" not in raw_name:
        raise ProfileFormatError("KBP1 profile name is not terminated")
    name, padding = raw_name.split(b"\0", 1)
    if not name or any(padding):
        raise ProfileFormatError("KBP1 profile name/padding is invalid")
    try:
        decoded_name = name.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProfileFormatError("KBP1 profile name is not UTF-8") from exc

    layout, initial_mode = record[64:66]
    if layout > 3 or initial_mode >= 3:
        raise ProfileFormatError("KBP1 layout or initial mode is invalid")
    enabled, effect, brightness, speed, direction = record[66:71]
    if enabled > 1 or effect > 4 or brightness > 100 or speed > 100 or direction > 4:
        raise ProfileFormatError("KBP1 lighting record is invalid")

    for logical in range(LOGICAL_KEYS):
        actuation, press_delta, release_delta, flags = record[80 + logical * 4:84 + logical * 4]
        if (not 1 <= actuation <= 32 or not 1 <= press_delta <= 32 or
                not 1 <= release_delta <= 32 or flags > 1):
            raise ProfileFormatError("KBP1 Hall record is invalid")

    actions_offset = 420
    for mode in range(MODES):
        for logical in range(LOGICAL_KEYS):
            offset = actions_offset + (mode * LOGICAL_KEYS + logical) * 4
            code, kind, argument = struct.unpack_from("<HBB", record, offset)
            if kind in (0, 1):
                valid = code == 0 and argument == 0
            elif kind == 2:
                valid = (logical != FN_LOGICAL_KEY and
                         ((0 < code < 152) or (0xE0 <= code <= 0xE7)) and argument == 0)
            elif kind == 3:
                valid = logical != FN_LOGICAL_KEY and code != 0 and argument == 0
            elif kind == 4:
                valid = (logical == FN_LOGICAL_KEY and code == 0 and
                         argument == FN1_MODE)
            else:
                valid = False
            if not valid:
                raise ProfileFormatError("KBP1 action record is invalid")

    primary_fn = struct.unpack_from("<HBB", record,
                                    actions_offset + FN_LOGICAL_KEY * 4)
    if primary_fn != (0, 4, FN1_MODE):
        raise ProfileFormatError("KBP1 primary Fn action is invalid")

    analog = record[1780:1792]
    if len(analog) != 12:
        raise ProfileFormatError("truncated KBP1 analog record")
    (analog_enabled, output, curve, deadzone, saturation, smoothing, flags,
     x_negative, x_positive, y_negative, y_positive, reserved) = analog
    keys = (x_negative, x_positive, y_negative, y_positive)
    if (analog_enabled > 1 or output > 2 or curve > 2 or deadzone >= saturation or
            saturation > 32 or smoothing > 10 or flags & ~7 or reserved != 0 or
            any(key >= LOGICAL_KEYS for key in keys) or len(set(keys)) != len(keys)):
        raise ProfileFormatError("KBP1 analog record is invalid")
    return decoded_name


def parse_profile_binary(blob: bytes) -> dict[str, Any]:
    """Validate KBP1 framing and return a compact diagnostic description."""

    if len(blob) < HEADER.size:
        raise ProfileFormatError("truncated KBP1 header")
    (magic, version, header_size, total, body_crc, count, active, record_size,
     records_offset, flags, reserved) = HEADER.unpack_from(blob)
    if (magic, version, header_size, records_offset, flags, reserved) != (
            MAGIC, VERSION, HEADER.size, HEADER.size, 0, b"\0" * 20):
        raise ProfileFormatError("invalid or unsupported KBP1 header")
    if not 1 <= count <= PROFILE_COUNT_MAX or active >= count or record_size != RECORD_SIZE:
        raise ProfileFormatError("invalid KBP1 profile count/record size")
    if total != len(blob) or total != HEADER.size + count * RECORD_SIZE:
        raise ProfileFormatError("KBP1 total length mismatch")
    if _crc32(blob[HEADER.size:]) != body_crc:
        raise ProfileFormatError("KBP1 body CRC mismatch")
    names = []
    for slot in range(count):
        offset = HEADER.size + slot * RECORD_SIZE
        names.append(_validate_record(blob[offset:offset + RECORD_SIZE]))
    return {"format": "kb7-profile-binary-v1", "profile_count": count,
            "active_profile": active, "names": names, "body_crc32": body_crc}
