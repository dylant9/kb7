"""Command-line entry point for Offline Control Studio (strictly offline)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .format import ScreenFormatError, compile_document, parse_binary
from .profile import ProfileFormatError, canonical_profile
from .profile_binary import compile_profile_binary, parse_profile_binary
from .protocol import ProtocolError, STORE_PROFILE, STORE_SCREEN, transfer_reports


def command_compile(args: argparse.Namespace) -> None:
    document = json.loads(args.source.read_text(encoding="utf-8"))
    artifact = compile_document(document)
    args.output.write_bytes(artifact)
    print(json.dumps({"output": str(args.output), "length": len(artifact)}, indent=2))


def command_inspect(args: argparse.Namespace) -> None:
    print(json.dumps(parse_binary(args.source.read_bytes()), indent=2))


def command_protocol_plan(args: argparse.Namespace) -> None:
    payload = args.source.read_bytes()
    store = STORE_PROFILE if args.store == "profile" else STORE_SCREEN
    if store == STORE_PROFILE:
        parse_profile_binary(payload)
    else:
        parse_binary(payload)
    reports = transfer_reports(payload, args.transfer_id, store)
    result = {
        "format": "KB7 offline HID transfer plan",
        "device_io": False,
        "store": args.store,
        "source": str(args.source),
        "report_count": len(reports),
        "reports_hex": [report.pack().hex() for report in reports],
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "report_count": len(reports)}, indent=2))


def command_profile_check(args: argparse.Namespace) -> None:
    document = json.loads(args.source.read_text(encoding="utf-8"))
    canonical = canonical_profile(document)
    encoded = json.dumps(canonical, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
        print(json.dumps({"output": str(args.output), "valid": True}, indent=2))
    else:
        print(encoded, end="")


def command_profile_compile(args: argparse.Namespace) -> None:
    document = json.loads(args.source.read_text(encoding="utf-8"))
    artifact = compile_profile_binary(document)
    args.output.write_bytes(artifact)
    print(json.dumps({"output": str(args.output), "length": len(artifact)}, indent=2))


def command_profile_inspect(args: argparse.Namespace) -> None:
    print(json.dumps(parse_profile_binary(args.source.read_bytes()), indent=2))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="kb7studio", description=__doc__)
    subcommands = result.add_subparsers(dest="command", required=True)
    compile_parser = subcommands.add_parser("compile", help="compile JSON to .kbs")
    compile_parser.add_argument("source", type=Path)
    compile_parser.add_argument("output", type=Path)
    compile_parser.set_defaults(function=command_compile)
    inspect_parser = subcommands.add_parser("inspect", help="validate/decompile .kbs")
    inspect_parser.add_argument("source", type=Path)
    inspect_parser.set_defaults(function=command_inspect)
    plan_parser = subcommands.add_parser("protocol-plan", help="emit offline 64-byte HID frames")
    plan_parser.add_argument("source", type=Path)
    plan_parser.add_argument("output", type=Path)
    plan_parser.add_argument("--transfer-id", type=int, default=1)
    plan_parser.add_argument("--store", choices=("screen", "profile"), default="screen")
    plan_parser.set_defaults(function=command_protocol_plan)
    profile_parser = subcommands.add_parser(
        "profile-check", help="validate and canonicalize an offline keyboard profile"
    )
    profile_parser.add_argument("source", type=Path)
    profile_parser.add_argument("--output", type=Path)
    profile_parser.set_defaults(function=command_profile_check)
    profile_compile = subcommands.add_parser(
        "profile-compile", help="compile a JSON profile or 1..5 profile set to firmware KBP1"
    )
    profile_compile.add_argument("source", type=Path)
    profile_compile.add_argument("output", type=Path)
    profile_compile.set_defaults(function=command_profile_compile)
    profile_inspect = subcommands.add_parser(
        "profile-inspect", help="validate and describe a firmware KBP1 profile"
    )
    profile_inspect.add_argument("source", type=Path)
    profile_inspect.set_defaults(function=command_profile_inspect)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        args.function(args)
        return 0
    except (OSError, json.JSONDecodeError, ScreenFormatError,
            ProfileFormatError, ProtocolError) as error:
        print(f"kb7studio: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
