"""Validation and canonicalization for offline KB7 keyboard profiles.

The profile is intentionally declarative.  It describes desired lighting,
Hall-switch policy, and analog-axis behavior without opening or writing a
device.  Hardware-facing adapters can consume the artifact after their
respective mappings and transports have passed physical validation.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

from .format import ScreenFormatError, compile_document, parse_binary

PROFILE_FORMAT = "kb7-profile-v1"
MAX_PROFILE_NAME_BYTES = 63  # KBP1 reserves byte 64 for a NUL terminator.

LIGHTING_EFFECTS = {"static", "gradient", "aurora", "reactive", "heatmap"}
LIGHTING_DIRECTIONS = {"east", "west", "north", "south", "radial"}
ANALOG_OUTPUTS = {"gamepad_left_stick", "gamepad_right_stick", "gamepad_triggers"}
ANALOG_CURVES = {"linear", "exponential", "s_curve"}
AXIS_BINDINGS = ("x_negative", "x_positive", "y_negative", "y_positive")
FIRMWARE_MODES = ("primary", "game", "easy_shift", "fn1")
FIRMWARE_INITIAL_MODES = {"primary", "game", "easy_shift"}
FIRMWARE_ACTIONS = {"transparent", "none", "keyboard", "consumer", "momentary_fn1"}

# Logical key names used by the offline editor. The recovered selector/routing
# tables are present in the firmware; physical layout-variant validation remains
# a hardware gate.
KNOWN_KEYS = frozenset({
    "ESC", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "GRAVE", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "MINUS", "EQUAL", "BACKSPACE",
    "TAB", "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "LEFTBRACE", "RIGHTBRACE", "BACKSLASH",
    "CAPSLOCK", "A", "S", "D", "F", "G", "H", "J", "K", "L", "SEMICOLON", "APOSTROPHE", "ENTER",
    "LEFTSHIFT", "Z", "X", "C", "V", "B", "N", "M", "COMMA", "DOT", "SLASH", "RIGHTSHIFT",
    "LEFTCTRL", "LEFTMETA", "LEFTALT", "SPACE", "RIGHTALT", "FN", "COMPOSE", "RIGHTCTRL",
    "LEFT", "UP", "DOWN", "RIGHT",
})


class ProfileFormatError(ValueError):
    """Raised when a KB7 profile is unsafe, inconsistent, or malformed."""


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileFormatError(f"{name} must be an object")
    return value


def _text(value: Any, name: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileFormatError(f"{name} must be non-empty text")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ProfileFormatError(f"{name} is longer than {maximum_bytes} UTF-8 bytes")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ProfileFormatError(f"{name} must be true or false")
    return value


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileFormatError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ProfileFormatError(f"{name} must be in {minimum:g}..{maximum:g}")
    return result


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ProfileFormatError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _choice(value: Any, name: str, choices: set[str]) -> str:
    if value not in choices:
        raise ProfileFormatError(f"{name} must be one of {', '.join(sorted(choices))}")
    return value


def _color(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        raise ProfileFormatError(f"{name} must use #rrggbb")
    try:
        int(value[1:], 16)
    except ValueError as exc:
        raise ProfileFormatError(f"{name} must use #rrggbb") from exc
    return value.lower()


def _key(value: Any, name: str) -> str:
    if value not in KNOWN_KEYS:
        raise ProfileFormatError(f"{name} names an unknown or unverified Hall key")
    return value


def _canonical_lighting(value: Any) -> dict[str, Any]:
    lighting = _object(value, "lighting")
    per_key = _object(lighting.get("per_key", {}), "lighting.per_key")
    if len(per_key) > len(KNOWN_KEYS):
        raise ProfileFormatError("lighting.per_key contains too many entries")
    canonical_keys: dict[str, str] = {}
    for key_name, color in sorted(per_key.items()):
        canonical_keys[_key(key_name, "lighting.per_key key")] = _color(
            color, f"lighting.per_key.{key_name}")
    return {
        "enabled": _boolean(lighting.get("enabled", True), "lighting.enabled"),
        "effect": _choice(lighting.get("effect", "aurora"), "lighting.effect", LIGHTING_EFFECTS),
        "brightness": _integer(lighting.get("brightness", 68), "lighting.brightness", 0, 100),
        "speed": _integer(lighting.get("speed", 42), "lighting.speed", 0, 100),
        "direction": _choice(lighting.get("direction", "east"), "lighting.direction", LIGHTING_DIRECTIONS),
        "primary": _color(lighting.get("primary", "#42efff"), "lighting.primary"),
        "secondary": _color(lighting.get("secondary", "#9d5cff"), "lighting.secondary"),
        "reactive": _color(lighting.get("reactive", "#b5ffcb"), "lighting.reactive"),
        "per_key": canonical_keys,
    }


def _canonical_switches(value: Any) -> dict[str, Any]:
    switches = _object(value, "switches")
    travel = _number(switches.get("travel_mm", 3.2), "switches.travel_mm", 0.5, 6.0)
    actuation = _number(switches.get("actuation_mm", 1.6), "switches.actuation_mm", 0.1, travel)
    per_key = _object(switches.get("per_key", {}), "switches.per_key")
    canonical_keys: dict[str, dict[str, Any]] = {}
    for key_name, override_value in sorted(per_key.items()):
        key_name = _key(key_name, "switches.per_key key")
        override = _object(override_value, f"switches.per_key.{key_name}")
        canonical_keys[key_name] = {
            "actuation_mm": round(_number(
                override.get("actuation_mm", actuation),
                f"switches.per_key.{key_name}.actuation_mm", 0.1, travel,
            ), 2),
            "rapid_trigger": _boolean(
                override.get("rapid_trigger", switches.get("rapid_trigger", True)),
                f"switches.per_key.{key_name}.rapid_trigger",
            ),
        }
    return {
        "travel_mm": round(travel, 2),
        "actuation_mm": round(actuation, 2),
        "rapid_trigger": _boolean(switches.get("rapid_trigger", True), "switches.rapid_trigger"),
        "rapid_press_delta_mm": round(_number(
            switches.get("rapid_press_delta_mm", 0.15), "switches.rapid_press_delta_mm", 0.05, 1.5,
        ), 2),
        "rapid_release_delta_mm": round(_number(
            switches.get("rapid_release_delta_mm", 0.15), "switches.rapid_release_delta_mm", 0.05, 1.5,
        ), 2),
        "per_key": canonical_keys,
    }


def _canonical_analog(value: Any, travel_mm: float) -> dict[str, Any]:
    analog = _object(value, "analog")
    bindings = _object(analog.get("bindings"), "analog.bindings")
    if set(bindings) != set(AXIS_BINDINGS):
        raise ProfileFormatError("analog.bindings must define x_negative/x_positive/y_negative/y_positive")
    canonical_bindings = {name: _key(bindings[name], f"analog.bindings.{name}") for name in AXIS_BINDINGS}
    if len(set(canonical_bindings.values())) != len(canonical_bindings):
        raise ProfileFormatError("analog axis bindings must use four distinct Hall keys")
    deadzone = _number(analog.get("deadzone_mm", 0.12), "analog.deadzone_mm", 0.0, travel_mm - 0.1)
    saturation = _number(analog.get("saturation_mm", travel_mm), "analog.saturation_mm", 0.1, travel_mm)
    if deadzone >= saturation:
        raise ProfileFormatError("analog.deadzone_mm must be below analog.saturation_mm")
    return {
        "enabled": _boolean(analog.get("enabled", True), "analog.enabled"),
        "output": _choice(analog.get("output", "gamepad_left_stick"), "analog.output", ANALOG_OUTPUTS),
        "curve": _choice(analog.get("curve", "linear"), "analog.curve", ANALOG_CURVES),
        "deadzone_mm": round(deadzone, 2),
        "saturation_mm": round(saturation, 2),
        "smoothing": _integer(analog.get("smoothing", 2), "analog.smoothing", 0, 10),
        "invert_x": _boolean(analog.get("invert_x", False), "analog.invert_x"),
        "invert_y": _boolean(analog.get("invert_y", False), "analog.invert_y"),
        "digital_passthrough": _boolean(
            analog.get("digital_passthrough", True), "analog.digital_passthrough"
        ),
        "bindings": canonical_bindings,
    }


def _firmware_key(value: Any) -> str:
    if isinstance(value, str) and value in KNOWN_KEYS:
        return value
    if isinstance(value, str) and value.startswith("logical:"):
        try:
            logical = int(value[8:], 10)
        except ValueError as exc:
            raise ProfileFormatError(f"invalid firmware logical key {value!r}") from exc
        if 0 <= logical < 85 and value == f"logical:{logical}":
            return value
    raise ProfileFormatError(f"unknown firmware logical key {value!r}")


def _canonical_firmware(value: Any) -> dict[str, Any]:
    firmware = _object(value, "firmware")
    if set(firmware) - {"layout_variant", "initial_mode", "actions"}:
        raise ProfileFormatError("firmware contains unknown fields")
    layout = _integer(firmware.get("layout_variant", 0),
                      "firmware.layout_variant", 0, 3)
    initial = firmware.get("initial_mode", "primary")
    if not isinstance(initial, str) or initial not in FIRMWARE_INITIAL_MODES:
        raise ProfileFormatError("firmware.initial_mode must be primary/game/easy_shift")
    actions = _object(firmware.get("actions", {}), "firmware.actions")
    if set(actions) - set(FIRMWARE_MODES):
        raise ProfileFormatError("firmware.actions contains an unknown mode")
    canonical_actions: dict[str, dict[str, dict[str, Any]]] = {}
    for mode in FIRMWARE_MODES:
        if mode not in actions:
            continue
        overrides = _object(actions[mode], f"firmware.actions.{mode}")
        canonical_overrides: dict[str, dict[str, Any]] = {}
        for raw_key, raw_action in sorted(overrides.items()):
            key_name = _firmware_key(raw_key)
            action = _object(raw_action, f"firmware.actions.{mode}.{key_name}")
            action_type = action.get("type")
            if not isinstance(action_type, str) or action_type not in FIRMWARE_ACTIONS:
                raise ProfileFormatError(f"invalid firmware action type for {key_name}")
            allowed = {"type", "usage"} if action_type in {"keyboard", "consumer"} else {"type"}
            if set(action) - allowed:
                raise ProfileFormatError(f"firmware action for {key_name} has unknown fields")
            is_fn = key_name in {"FN", "logical:78"}
            result: dict[str, Any] = {"type": action_type}
            if action_type == "keyboard":
                usage = action.get("usage")
                if isinstance(usage, str):
                    if usage not in KNOWN_KEYS or usage == "FN":
                        raise ProfileFormatError("firmware keyboard usage name is invalid")
                elif (isinstance(usage, bool) or not isinstance(usage, int) or
                      not (0 < usage < 152 or 0xE0 <= usage <= 0xE7)):
                    raise ProfileFormatError("firmware keyboard usage integer is invalid")
                if is_fn:
                    raise ProfileFormatError("Fn cannot emit a keyboard usage")
                result["usage"] = usage
            elif action_type == "consumer":
                usage = action.get("usage")
                if (isinstance(usage, bool) or not isinstance(usage, int) or
                        not 0 < usage <= 0xFFFF or is_fn):
                    raise ProfileFormatError("firmware consumer usage is invalid")
                result["usage"] = usage
            elif action_type == "momentary_fn1" and not is_fn:
                raise ProfileFormatError("momentary_fn1 is only valid on Fn")
            if mode == "primary" and is_fn and action_type != "momentary_fn1":
                raise ProfileFormatError("firmware primary Fn action must remain momentary_fn1")
            canonical_overrides[key_name] = result
        canonical_actions[mode] = canonical_overrides
    return {"layout_variant": layout, "initial_mode": initial,
            "actions": canonical_actions}


def canonical_profile(document: dict[str, Any]) -> dict[str, Any]:
    """Return a validated, deterministic profile representation."""

    profile = _object(document, "profile")
    if profile.get("format") != PROFILE_FORMAT:
        raise ProfileFormatError(f"profile.format must be {PROFILE_FORMAT!r}")
    name = _text(profile.get("name"), "profile.name", MAX_PROFILE_NAME_BYTES)
    screen_document = copy.deepcopy(_object(profile.get("screen_document"), "screen_document"))
    try:
        screen_document = parse_binary(compile_document(screen_document))
    except ScreenFormatError as exc:
        raise ProfileFormatError(f"screen_document: {exc}") from exc
    lighting = _canonical_lighting(profile.get("lighting"))
    switches = _canonical_switches(profile.get("switches"))
    analog = _canonical_analog(profile.get("analog"), switches["travel_mm"])
    result = {
        "format": PROFILE_FORMAT,
        "name": name,
        "screen_document": screen_document,
        "lighting": lighting,
        "switches": switches,
        "analog": analog,
        "capabilities": {
            "hall_keymap": "implemented-hardware-unverified",
            "rgb_position_mapping": "pending_hardware",
            "analog_hid_output": "implemented-hardware-unverified",
            "device_io": False,
        },
    }
    if "firmware" in profile:
        result["firmware"] = _canonical_firmware(profile["firmware"])
    return result


def validate_profile(document: dict[str, Any]) -> None:
    canonical_profile(document)


def load_profile(path: Path) -> dict[str, Any]:
    import json

    return canonical_profile(json.loads(path.read_text(encoding="utf-8")))
