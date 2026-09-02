#!/usr/bin/env python3
"""Catch direct or plainly encoded prohibited/binary material in a public tree.

This is a publication accident detector, not a proof against deliberate data
concealment. Human provenance review remains mandatory.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
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
    "kb7-isp-write.py",
    "bundle.json",
    "simulation.json",
    "kb7-updater-authentication-v1.json",
    ".kb7-usb-updater-journal-v1.json",
    "updater-journal.json",
    ".kb7-usb-updater-scratch-journal-v1.json",
    ".kb7-usb-updater-scratch-journal-v2.json",
    ".kb7-usb-updater-scratch-journal-v3.json",
    "updater-scratch-journal.json",
    "kb7-loader-reentry-proof-journal.json",
    ".kb7-isp-scratch-restart-state.json",
    "scratch-restart-state.json",
    ".kb7-isp-write2-state.json",
    "kb7-isp-write2-state.json",
    ".kb7-isp-erase-granularity-state.json",
    "kb7-isp-erase-granularity-state.json",
}
DENIED_NAME_PATTERNS = {
    "*updater-authentication*.json",
    "*updater-auth*.json",
    "*updater-scratch-journal*",
    "*loader-reentry-proof-journal*",
    "*loader-reentry-journal*",
    ".kb7-updater-journal.*",
    "*isp-write2-state*",
    "*isp-erase-granularity-state*",
    "*scratch-restart-state*",
}
DENIED_JSON_SCHEMAS = {
    "kb7-isp-scratch-restart-state-v1",
    "kb7-usb-updater-journal-v1",
    "kb7-usb-updater-scratch-journal-v1",
    "kb7-usb-updater-scratch-journal-v2",
    "kb7-usb-updater-scratch-journal-v3",
    "kb7-loader-reentry-proof-journal-v1",
    "kb7-loader-reentry-proof-journal-v2",
    "kb7-isp-write2-state-v1",
    "kb7-isp-write2-state-v2",
    "kb7-isp-write2-state-v3",
    "kb7-isp-erase-granularity-state-v1",
}
DENIED_JSON_RESULT_SCHEMAS = {
    "kb7-fixed-isp-read-reliability-v1",
}
DENIED_JSON_FORMATS = {
    "KB7 offline updater detached authentication v1",
    "KB7 V1.22 fixed loader-reentry proof campaign v1",
}
DENIED_TEXT = (
    "Ghidra " + "decompiler output",
    "Turtle Beach " + "Swarm II Installer",
    "AP_AT423_" + "V1.15.bin",
    "ISPTool" + "Main.dll",
    "nor_write_" + "emitter.py",
    "kb7-REPAIR-" + "full32M.bin",
    "private " + "repo",
    "private " + "workspace",
    "private " + "RE " + "archive",
    "$HOME/" + "dev/kb7",
    str(Path("/") / "root" / ".codex" / "attachments"),
    "-----BEGIN " + "PRIVATE KEY-----",
    "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----",
    "-----BEGIN " + "PUBLIC KEY-----",
)
MAGICS = {
    b"\x7fELF": "ELF",
    b"MZ": "PE/DOS executable",
    b"PK\x03\x04": "ZIP archive",
    b"7z\xbc\xaf\x27\x1c": "7-Zip archive",
}
ENCODED_BLOCKS = {
    "large base64-like block": re.compile(r"(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{4}){128,}(?:==|=)?"),
    "large hexadecimal block": re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{1024,}(?![0-9A-Fa-f])"),
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
        if (path.name in DENIED_NAMES or
                any(fnmatch.fnmatchcase(path.name.lower(), pattern)
                    for pattern in DENIED_NAME_PATTERNS)):
            failures.append(f"prohibited artifact filename: {relative}")
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
        if path.suffix.lower() == ".json":
            try:
                structured = json.loads(text)
            except (json.JSONDecodeError, UnicodeDecodeError):
                structured = None
            if (isinstance(structured, dict) and
                    structured.get("schema") in DENIED_JSON_SCHEMAS):
                failures.append(f"owner-local updater journal: {relative}")
            if (isinstance(structured, dict) and
                    structured.get("schema") in DENIED_JSON_RESULT_SCHEMAS):
                failures.append(f"owner-local diagnostic result: {relative}")
            if (isinstance(structured, dict) and
                    structured.get("format") in DENIED_JSON_FORMATS):
                failures.append(f"owner-local updater metadata: {relative}")
        for marker in DENIED_TEXT:
            if marker in text:
                failures.append(f"prohibited content marker {marker!r}: {relative}")
        for description, pattern in ENCODED_BLOCKS.items():
            if pattern.search(text):
                failures.append(f"{description}: {relative}")
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
