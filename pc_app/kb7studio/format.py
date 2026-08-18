"""Compiler/parser for the versioned KB7 declarative screen format."""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAGIC = 0x3153424B
VERSION = 1
HEADER = struct.Struct("<IHHIIHHHHIIIIII")
SCREEN = struct.Struct("<HHHHIHH")
WIDGET = struct.Struct("<HBBhhhhHHhhhHBBHIIHH")
MAX_SCREENS = 16
MAX_WIDGETS = 128
MAX_BINARY_SIZE = 0x200000 - 64  # KBS1 payload capacity of one firmware slot.

WIDGET_TYPES = {"label": 1, "button": 2, "slider": 3, "toggle": 4, "gauge": 5}
ACTIONS = {
    "none": 0x00, "navigate": 0x01, "rgb_color": 0x10, "rgb_effect": 0x11,
    "brightness": 0x12, "profile": 0x20, "actuation": 0x21,
    "rapid_trigger": 0x22, "hid_key": 0x30, "media_key": 0x31,
    "host_event": 0x40,
}
REVERSE_WIDGET_TYPES = {value: key for key, value in WIDGET_TYPES.items()}
REVERSE_ACTIONS = {value: key for key, value in ACTIONS.items()}
KEYBOARD_USAGE_BITS = 152


class ScreenFormatError(ValueError):
    pass


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def rgb565(value: str | int) -> int:
    if isinstance(value, bool):
        raise ScreenFormatError("RGB565 color cannot be boolean")
    if isinstance(value, int):
        if 0 <= value <= 0xFFFF:
            return value
        raise ScreenFormatError("RGB565 integer is out of range")
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise ScreenFormatError(f"invalid color {value!r}; use #rrggbb")
    try:
        red, green, blue = int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    except ValueError as exc:
        raise ScreenFormatError(f"invalid color {value!r}") from exc
    return ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)


def rgb888(value: int) -> str:
    red = ((value >> 11) & 0x1F) * 255 // 31
    green = ((value >> 5) & 0x3F) * 255 // 63
    blue = (value & 0x1F) * 255 // 31
    return f"#{red:02x}{green:02x}{blue:02x}"


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ScreenFormatError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _append_string(pool: bytearray, value: Any, name: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ScreenFormatError(f"{name} must be text")
    encoded = value.encode("utf-8")
    if len(encoded) > 0xFFFF:
        raise ScreenFormatError(f"{name} is too long")
    offset = len(pool)
    pool.extend(encoded)
    return offset, len(encoded)


def _validate_action_fields(action: int, target: int, arg0: int, arg1: int,
                            minimum: int, maximum: int) -> None:
    if action != ACTIONS["navigate"] and target != 0:
        raise ScreenFormatError("only navigate may set target_screen")
    if action in (ACTIONS["none"], ACTIONS["navigate"]):
        valid = arg0 == 0 and arg1 == 0
    elif action == ACTIONS["rgb_color"]:
        valid = arg0 == 0 and arg1 <= 0xFFFFFF
    elif action == ACTIONS["rgb_effect"]:
        valid = arg0 <= 4 and arg1 == 0
    elif action == ACTIONS["profile"]:
        valid = arg0 <= 3 and arg1 == 0
    elif action == ACTIONS["brightness"]:
        valid = minimum >= 0 and maximum <= 100 and arg0 == 0 and arg1 == 0
    elif action == ACTIONS["actuation"]:
        valid = minimum >= 0 and maximum <= 0xFF and arg0 == 0 and arg1 == 0
    elif action == ACTIONS["rapid_trigger"]:
        valid = minimum >= 0 and maximum <= 1 and arg0 <= 0xFF and arg1 <= 0xFF
    elif action == ACTIONS["hid_key"]:
        valid = arg0 != 0 and (arg0 < KEYBOARD_USAGE_BITS or 0xE0 <= arg0 <= 0xE7) and arg1 == 0
    elif action == ACTIONS["media_key"]:
        valid = arg0 != 0 and arg1 == 0
    else:  # host_event
        valid = True
    if not valid:
        raise ScreenFormatError("action arguments or value range are invalid")


def compile_document(document: dict[str, Any]) -> bytes:
    if not isinstance(document, dict) or document.get("format") != "kb7-screen-v1":
        raise ScreenFormatError("document format must be 'kb7-screen-v1'")
    screens = document.get("screens")
    if not isinstance(screens, list) or not 1 <= len(screens) <= MAX_SCREENS:
        raise ScreenFormatError(f"screens must contain 1..{MAX_SCREENS} entries")
    boot = _integer(document.get("boot_screen"), "boot_screen", 0, 0xFFFF)
    header_flags = _integer(document.get("flags", 0), "flags", 0, 0xFFFF)
    if header_flags != 0:
        raise ScreenFormatError("header flags must be zero in version 1")
    strings = bytearray()
    screen_blobs: list[bytes] = []
    widget_blobs: list[bytes] = []
    screen_ids: set[int] = set()
    widget_ids: set[int] = set()
    navigation_targets: list[int] = []
    first_widget = 0
    for screen_index, screen in enumerate(screens):
        if not isinstance(screen, dict):
            raise ScreenFormatError(f"screen[{screen_index}] must be an object")
        screen_id = _integer(screen.get("id"), "screen.id", 0, 0xFFFF)
        if screen_id in screen_ids:
            raise ScreenFormatError(f"duplicate screen id {screen_id}")
        screen_ids.add(screen_id)
        name_offset, name_length = _append_string(strings, screen.get("name", ""), "screen.name")
        widgets = screen.get("widgets", [])
        if not isinstance(widgets, list):
            raise ScreenFormatError("screen.widgets must be a list")
        if len(widget_blobs) + len(widgets) > MAX_WIDGETS:
            raise ScreenFormatError(f"more than {MAX_WIDGETS} widgets")
        screen_flags = _integer(screen.get("flags", 0), "screen.flags", 0, 0xFFFF)
        if screen_flags != 0:
            raise ScreenFormatError("screen flags must be zero in version 1")
        screen_blobs.append(SCREEN.pack(
            screen_id, first_widget, len(widgets), rgb565(screen.get("background", "#08111f")),
            name_offset, name_length, screen_flags,
        ))
        for widget_index, widget in enumerate(widgets):
            if not isinstance(widget, dict):
                raise ScreenFormatError(f"widget[{widget_index}] must be an object")
            widget_id = _integer(widget.get("id"), "widget.id", 0, 0xFFFF)
            if widget_id in widget_ids:
                raise ScreenFormatError(f"duplicate widget id {widget_id}")
            widget_ids.add(widget_id)
            kind_name = widget.get("type")
            if kind_name not in WIDGET_TYPES:
                raise ScreenFormatError(f"unsupported widget type {kind_name!r}")
            x = _integer(widget.get("x", 0), "widget.x", 0, 479)
            y = _integer(widget.get("y", 0), "widget.y", 0, 799)
            width = _integer(widget.get("width", 120), "widget.width", 1, 480)
            height = _integer(widget.get("height", 52), "widget.height", 1, 800)
            if x + width > 480 or y + height > 800:
                raise ScreenFormatError(f"widget {widget_id} lies outside 480x800")
            text_offset, text_length = _append_string(strings, widget.get("text", ""), "widget.text")
            action = widget.get("action", {})
            if action is None:
                action = {}
            if not isinstance(action, dict) or action.get("type", "none") not in ACTIONS:
                raise ScreenFormatError(f"widget {widget_id} has invalid action")
            minimum = _integer(widget.get("minimum", 0), "widget.minimum", -32768, 32767)
            maximum = _integer(widget.get("maximum", 100), "widget.maximum", -32768, 32767)
            value = _integer(widget.get("value", minimum), "widget.value", -32768, 32767)
            if minimum > maximum or not minimum <= value <= maximum:
                raise ScreenFormatError(f"widget {widget_id} has invalid value range")
            widget_flags = _integer(widget.get("flags", 0), "widget.flags", 0, 255)
            if widget_flags != 0:
                raise ScreenFormatError("widget flags must be zero in version 1")
            target_screen = _integer(action.get("target_screen", 0), "action.target_screen", 0, 0xFFFF)
            action_code = ACTIONS[action.get("type", "none")]
            action_flags = _integer(action.get("flags", 0), "action.flags", 0, 255)
            if action_flags != 0:
                raise ScreenFormatError("action flags must be zero in version 1")
            arg0 = _integer(action.get("arg0", 0), "action.arg0", 0, 0xFFFF)
            arg1 = _integer(action.get("arg1", 0), "action.arg1", 0, 0xFFFFFFFF)
            _validate_action_fields(action_code, target_screen, arg0, arg1, minimum, maximum)
            if action.get("type", "none") == "navigate":
                navigation_targets.append(target_screen)
            widget_blobs.append(WIDGET.pack(
                widget_id, WIDGET_TYPES[kind_name], widget_flags,
                x, y, width, height, rgb565(widget.get("foreground", "#f5f7ff")),
                rgb565(widget.get("background", "#17243a")), minimum, maximum, value,
                target_screen,
                action_code, action_flags, arg0, arg1,
                text_offset, text_length, 0,
            ))
        first_widget += len(widgets)
    if boot not in screen_ids:
        raise ScreenFormatError("boot_screen does not name a screen")
    if any(target not in screen_ids for target in navigation_targets):
        raise ScreenFormatError("navigation target does not name a screen")
    screens_offset = HEADER.size
    widgets_offset = screens_offset + len(screen_blobs) * SCREEN.size
    strings_offset = widgets_offset + len(widget_blobs) * WIDGET.size
    body = b"".join(screen_blobs + widget_blobs) + bytes(strings)
    total_length = HEADER.size + len(body)
    if total_length > MAX_BINARY_SIZE:
        raise ScreenFormatError("compiled KBS1 exceeds the firmware screen-slot capacity")
    header = HEADER.pack(
        MAGIC, VERSION, HEADER.size, total_length, crc32(body), len(screen_blobs), boot,
        len(widget_blobs), 0,
        screens_offset, widgets_offset, strings_offset, len(strings), 0, 0,
    )
    return header + body


def parse_binary(blob: bytes) -> dict[str, Any]:
    if len(blob) > MAX_BINARY_SIZE:
        raise ScreenFormatError("KBS1 exceeds the firmware screen-slot capacity")
    if len(blob) < HEADER.size:
        raise ScreenFormatError("truncated header")
    fields = HEADER.unpack_from(blob)
    (magic, version, header_length, total, body_crc, screen_count, boot, widget_count,
     flags, screens_offset, widgets_offset, strings_offset, strings_length, features,
     reserved) = fields
    if magic != MAGIC:
        raise ScreenFormatError("bad magic")
    if version != VERSION or header_length != HEADER.size:
        raise ScreenFormatError("unsupported version/header")
    if total != len(blob):
        raise ScreenFormatError("total length mismatch")
    if not 1 <= screen_count <= MAX_SCREENS or widget_count > MAX_WIDGETS:
        raise ScreenFormatError("object count limit exceeded")
    if screens_offset != HEADER.size or widgets_offset != screens_offset + screen_count * SCREEN.size:
        raise ScreenFormatError("non-canonical record layout")
    if strings_offset != widgets_offset + widget_count * WIDGET.size or strings_offset + strings_length != total:
        raise ScreenFormatError("invalid string layout")
    if flags != 0 or features != 0 or reserved != 0:
        raise ScreenFormatError("reserved header fields must be zero")
    if crc32(blob[header_length:]) != body_crc:
        raise ScreenFormatError("body CRC mismatch")
    strings = blob[strings_offset:]
    try:
        strings.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScreenFormatError("invalid UTF-8 string pool") from exc

    def text(offset: int, length: int) -> str:
        if offset > len(strings) or length > len(strings) - offset:
            raise ScreenFormatError("string range outside pool")
        try:
            return strings[offset:offset + length].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ScreenFormatError("invalid UTF-8") from exc

    raw_widgets = []
    widget_ids: set[int] = set()
    for index in range(widget_count):
        item = WIDGET.unpack_from(blob, widgets_offset + index * WIDGET.size)
        (widget_id, widget_type, widget_flags, x, y, width, height, foreground, background,
         minimum, maximum, value, target, action, action_flags, arg0, arg1, text_offset,
         text_length, widget_reserved) = item
        if widget_type not in REVERSE_WIDGET_TYPES or action not in REVERSE_ACTIONS:
            raise ScreenFormatError("unknown widget/action opcode")
        if widget_flags != 0 or action_flags != 0 or widget_reserved != 0:
            raise ScreenFormatError("widget flags/reserved fields must be zero")
        if widget_id in widget_ids:
            raise ScreenFormatError("duplicate widget id")
        widget_ids.add(widget_id)
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 480 or y + height > 800:
            raise ScreenFormatError("widget geometry outside display")
        if minimum > maximum or not minimum <= value <= maximum:
            raise ScreenFormatError("widget value outside range")
        _validate_action_fields(action, target, arg0, arg1, minimum, maximum)
        raw_widgets.append({
            "id": widget_id, "type": REVERSE_WIDGET_TYPES[widget_type], "flags": widget_flags,
            "x": x, "y": y, "width": width, "height": height,
            "foreground": rgb888(foreground), "background": rgb888(background),
            "minimum": minimum, "maximum": maximum, "value": value,
            "text": text(text_offset, text_length),
            "action": {"type": REVERSE_ACTIONS[action], "flags": action_flags,
                       "target_screen": target, "arg0": arg0, "arg1": arg1},
        })
    screens = []
    screen_ids = set()
    next_widget = 0
    for index in range(screen_count):
        screen_id, first, count, background, name_offset, name_length, screen_flags = SCREEN.unpack_from(
            blob, screens_offset + index * SCREEN.size)
        if (screen_flags != 0 or screen_id in screen_ids or first != next_widget or
                first + count > len(raw_widgets)):
            raise ScreenFormatError("invalid/duplicate screen record")
        screen_ids.add(screen_id)
        screens.append({"id": screen_id, "name": text(name_offset, name_length),
                        "background": rgb888(background), "flags": screen_flags,
                        "widgets": raw_widgets[first:first + count]})
        next_widget += count
    if next_widget != len(raw_widgets) or boot not in screen_ids:
        raise ScreenFormatError("invalid boot screen or widget partition")
    for widget in raw_widgets:
        action = widget["action"]
        if action["type"] == "navigate" and action["target_screen"] not in screen_ids:
            raise ScreenFormatError("navigation target does not name a screen")
    return {"format": "kb7-screen-v1", "boot_screen": boot, "flags": flags, "screens": screens}


def compile_file(source: Path, destination: Path) -> None:
    document = json.loads(source.read_text(encoding="utf-8"))
    destination.write_bytes(compile_document(document))
