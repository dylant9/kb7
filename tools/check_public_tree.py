#!/usr/bin/env python3
"""Fail closed if a public-source tree contains likely private/binary material."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DENIED_SUFFIXES = {
    ".7z", ".bin", ".dll", ".dump", ".elf", ".exe", ".hex", ".img",
    ".map", ".o", ".pyc", ".rom", ".uf2", ".zip", ".dis",
}
DENIED_PARTS = {
    "__pycache__", "build", "captures", "decompiled", "firmware",
    "ghidra_projects",
}
DENIED_NAMES = {
    "KB7_V1.22-core0.bin",
    "KB7_V1.22-core1.bin",
    "KB7_V1.22-loader.bin",
    "KB7_V1.24-core0.bin",
    "KB7_V1.24-core1.bin",
    "KB7_V1.24-loader.bin",
}
DENIED_TEXT = (
    "Ghidra " + "decompiler output",
    "Turtle Beach " + "Swarm II Installer",
    "AP_AT423_" + "V1.15.bin",
)
MAGICS = {
    b"\x7fELF": "ELF",
    b"MZ": "PE/DOS executable",
    b"PK\x03\x04": "ZIP archive",
    b"7z\xbc\xaf\x27\x1c": "7-Zip archive",
}


def inspect(root: Path) -> dict[str, object]:
    failures: list[str] = []
    checked = 0
    text_bytes = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        if path.is_symlink():
            failures.append(f"symlink: {relative}")
            continue
        if not path.is_file():
            continue
        checked += 1
        if path.name in DENIED_NAMES:
            failures.append(f"known private filename: {relative}")
        if path.suffix.lower() in DENIED_SUFFIXES:
            failures.append(f"denied extension: {relative}")
        if any(part.lower() in DENIED_PARTS for part in relative.parts[:-1]):
            failures.append(f"denied directory: {relative}")
        data = path.read_bytes()
        for magic, description in MAGICS.items():
            if data.startswith(magic):
                failures.append(f"{description} magic: {relative}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            failures.append(f"non-UTF-8/binary file: {relative}")
            continue
        text_bytes += len(data)
        for marker in DENIED_TEXT:
            if marker in text:
                failures.append(f"private marker {marker!r}: {relative}")
    return {
        "root": str(root),
        "files_checked": checked,
        "utf8_bytes_checked": text_bytes,
        "failures": failures,
        "passed": not failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    result = inspect(root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
