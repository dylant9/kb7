#!/usr/bin/env python3
"""Create or verify detached authentication for an offline KB7 bundle.

This tool has no USB or execution path.  A valid signature authenticates one
exact, independently reverified offline bundle; it does not authorize flashing
and does not change the bundle's fail-closed safety flags.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType


FORMAT = "KB7 offline updater detached authentication v1"
SCHEMA = 1
ALGORITHM = "Ed25519"
DOMAIN = b"KB7 offline updater detached authentication v1\0"
MAX_KEY_BYTES = 64 * 1024
MAX_ENVELOPE_BYTES = 64 * 1024
SIGNATURE_BYTES = 64
BUNDLE_FILES = (
    "bundle.json",
    "simulation.json",
    "core0-sector-image.bin",
    "core1-sector-image.bin",
    "poison-blocks.bin",
)


class AuthenticationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuthenticationError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def duplicate_rejecting_object(
        pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_json_constant(value: str) -> object:
    raise AuthenticationError(f"non-finite JSON number is not permitted: {value}")


def read_regular(path: Path, *, maximum: int | None = None) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise AuthenticationError(f"missing file: {path}") from error
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(),
            f"not a regular non-symlink file: {path}")
    if maximum is not None:
        require(info.st_size <= maximum,
                f"{path.name} exceeds the {maximum}-byte limit")
    try:
        return path.read_bytes()
    except OSError as error:
        raise AuthenticationError(f"cannot read {path}: {error}") from error


def load_planner() -> ModuleType:
    path = Path(__file__).resolve().with_name("kb7-updater-plan.py")
    name = "kb7_updater_plan_for_authentication"
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification is not None and specification.loader is not None,
            "cannot load the offline updater planner")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def run_openssl(arguments: list[str]) -> bytes:
    try:
        result = subprocess.run(
            ["openssl", *arguments], stdin=subprocess.DEVNULL,
            capture_output=True, check=False)
    except FileNotFoundError as error:
        raise AuthenticationError("OpenSSL is required but was not found") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        if detail:
            detail = detail.splitlines()[-1]
        raise AuthenticationError(
            f"OpenSSL command failed ({result.returncode})"
            + (f": {detail}" if detail else ""))
    return result.stdout


def require_private_key(path: Path) -> None:
    read_regular(path, maximum=MAX_KEY_BYTES)
    info = path.lstat()
    require((stat.S_IMODE(info.st_mode) &
             (stat.S_IRWXG | stat.S_IRWXO)) == 0,
            "private key permissions must deny all group and other access")


def public_spki_der(path: Path, *, private: bool) -> bytes:
    read_regular(path, maximum=MAX_KEY_BYTES)
    arguments = ["pkey"]
    if not private:
        arguments.append("-pubin")
    arguments.extend(["-in", str(path), "-pubout", "-outform", "DER"])
    der = run_openssl(arguments)
    require(len(der) == 44 and der.startswith(bytes.fromhex("302a300506032b6570032100")),
            "key is not an Ed25519 public key")
    return der


def key_fingerprint(path: Path) -> str:
    return sha256(public_spki_der(path, private=False))


def strict_json(path: Path) -> dict[str, object]:
    raw = read_regular(path, maximum=MAX_ENVELOPE_BYTES)
    try:
        value = json.loads(raw, object_pairs_hook=duplicate_rejecting_object,
                           parse_constant=reject_json_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AuthenticationError("authentication envelope is not strict JSON") from error
    require(isinstance(value, dict), "authentication envelope is not an object")
    return value


def statement_for(bundle: Path, descriptor: dict[str, object],
                  signing_key_sha256: str) -> dict[str, object]:
    require(re.fullmatch(r"[0-9a-f]{64}", signing_key_sha256) is not None,
            "signing-key fingerprint is not a lowercase SHA-256 value")
    records: list[dict[str, object]] = []
    for name in BUNDLE_FILES:
        data = read_regular(bundle / name)
        records.append({"name": name, "length": len(data), "sha256": sha256(data)})
    expected_descriptor_fields = (
        "format", "schema", "bundle_id", "baseline_sha256",
        "target_full_sha256", "pair_id",
    )
    require(all(field in descriptor for field in expected_descriptor_fields),
            "verified bundle descriptor is incomplete")
    return {
        "format": FORMAT,
        "schema": SCHEMA,
        "algorithm": ALGORITHM,
        "bundle_format": descriptor["format"],
        "bundle_schema": descriptor["schema"],
        "bundle_id": descriptor["bundle_id"],
        "baseline_sha256": descriptor["baseline_sha256"],
        "target_full_sha256": descriptor["target_full_sha256"],
        "pair_id": descriptor["pair_id"],
        "files": records,
        "signing_key_spki_sha256": signing_key_sha256,
        "policy": {
            "bundle_unsigned": True,
            "device_io": False,
            "offline_only": True,
            "execution_authorized": False,
            "flash_approved": False,
            "signature_is_install_authorization": False,
        },
    }


def signed_bytes(statement: dict[str, object]) -> bytes:
    return DOMAIN + canonical_bytes(statement)


def sign_bytes(private_key: Path, message: bytes) -> bytes:
    require_private_key(private_key)
    with tempfile.TemporaryDirectory(prefix="kb7-updater-auth-") as temporary:
        root = Path(temporary)
        message_path = root / "statement.bin"
        signature_path = root / "signature.bin"
        message_path.write_bytes(message)
        run_openssl([
            "pkeyutl", "-sign", "-rawin", "-inkey", str(private_key),
            "-in", str(message_path), "-out", str(signature_path),
        ])
        signature = read_regular(signature_path, maximum=SIGNATURE_BYTES)
    require(len(signature) == SIGNATURE_BYTES,
            "OpenSSL returned an invalid Ed25519 signature length")
    return signature


def verify_bytes(public_key: Path, message: bytes, signature: bytes) -> None:
    require(len(signature) == SIGNATURE_BYTES,
            "invalid Ed25519 signature length")
    read_regular(public_key, maximum=MAX_KEY_BYTES)
    with tempfile.TemporaryDirectory(prefix="kb7-updater-auth-") as temporary:
        root = Path(temporary)
        message_path = root / "statement.bin"
        signature_path = root / "signature.bin"
        message_path.write_bytes(message)
        signature_path.write_bytes(signature)
        run_openssl([
            "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey",
            str(public_key), "-in", str(message_path), "-sigfile",
            str(signature_path),
        ])


def output_path(path: Path, bundle: Path) -> Path:
    require(path.name not in {"", ".", ".."}, "invalid output filename")
    supplied_parent = path.parent.absolute()
    try:
        supplied_info = supplied_parent.lstat()
        parent = supplied_parent.resolve(strict=True)
    except FileNotFoundError as error:
        raise AuthenticationError("output parent directory does not exist") from error
    require(stat.S_ISDIR(supplied_info.st_mode) and not supplied_parent.is_symlink() and
            supplied_parent == parent,
            "output parent is not a regular non-symlink directory")
    resolved = parent / path.name
    bundle_resolved = bundle.resolve(strict=True)
    require(bundle_resolved != resolved and bundle_resolved not in resolved.parents,
            "authentication envelope must be stored outside the bundle")
    try:
        resolved.lstat()
    except FileNotFoundError:
        return resolved
    raise AuthenticationError("refusing to overwrite an existing output file")


def write_atomic_new(path: Path, data: bytes) -> None:
    descriptor = -1
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        require(not path.exists() and not path.is_symlink(),
                "refusing to overwrite an existing output file")
        try:
            os.link(temporary_path, path)
        except FileExistsError as error:
            raise AuthenticationError(
                "refusing to overwrite an existing output file") from error
        temporary_path.unlink()
        temporary_path = None
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def validated_descriptor(planner: ModuleType, bundle: Path,
                         baseline_a: Path, baseline_b: Path) -> dict[str, object]:
    planner.verify_bundle(bundle, baseline_a, baseline_b)
    descriptor = planner.load_descriptor(bundle)
    require(descriptor.get("offline_only") is True and
            descriptor.get("device_io") is False and
            descriptor.get("unsigned") is True and
            descriptor.get("execution_authorized") is False and
            descriptor.get("flash_approved") is False,
            "verified bundle does not retain its fail-closed policy")
    return descriptor


def sign_bundle(bundle: Path, baseline_a: Path, baseline_b: Path,
                private_key: Path, destination: Path,
                *, planner: ModuleType | None = None) -> dict[str, object]:
    planner = load_planner() if planner is None else planner
    descriptor = validated_descriptor(planner, bundle, baseline_a, baseline_b)
    require_private_key(private_key)
    fingerprint = sha256(public_spki_der(private_key, private=True))
    statement = statement_for(bundle, descriptor, fingerprint)
    signature = sign_bytes(private_key, signed_bytes(statement))
    envelope = {
        "format": FORMAT,
        "schema": SCHEMA,
        "algorithm": ALGORITHM,
        "statement": statement,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
    target = output_path(destination, bundle)
    write_atomic_new(
        target, (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "algorithm": ALGORITHM,
        "bundle_id": descriptor["bundle_id"],
        "execution_authorized": False,
        "flash_approved": False,
        "offline_only": True,
        "signature": str(target),
        "signing_key_spki_sha256": fingerprint,
    }


def verify_bundle_authentication(
        bundle: Path, baseline_a: Path, baseline_b: Path, public_key: Path,
        trusted_key_sha256: str, envelope_path: Path,
        *, planner: ModuleType | None = None) -> dict[str, object]:
    require(re.fullmatch(r"[0-9a-f]{64}", trusted_key_sha256) is not None,
            "trusted-key fingerprint must be exactly 64 lowercase hexadecimal characters")
    planner = load_planner() if planner is None else planner
    descriptor = validated_descriptor(planner, bundle, baseline_a, baseline_b)
    actual_fingerprint = key_fingerprint(public_key)
    require(actual_fingerprint == trusted_key_sha256,
            "public key does not match the separately trusted fingerprint")
    envelope = strict_json(envelope_path)
    require(set(envelope) == {
        "format", "schema", "algorithm", "statement", "signature_base64",
    }, "authentication envelope has missing or unknown fields")
    require(envelope.get("format") == FORMAT and
            type(envelope.get("schema")) is int and envelope.get("schema") == SCHEMA and
            envelope.get("algorithm") == ALGORITHM,
            "unsupported authentication envelope")
    expected_statement = statement_for(bundle, descriptor, actual_fingerprint)
    require(envelope.get("statement") == expected_statement,
            "authenticated statement does not exactly match the verified bundle")
    encoded = envelope.get("signature_base64")
    require(isinstance(encoded, str), "authentication signature is not text")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise AuthenticationError("authentication signature is not strict base64") from error
    verify_bytes(public_key, signed_bytes(expected_statement), signature)
    return {
        "algorithm": ALGORITHM,
        "authenticated": True,
        "bundle_id": descriptor["bundle_id"],
        "execution_authorized": False,
        "flash_approved": False,
        "offline_only": True,
        "signing_key_spki_sha256": actual_fingerprint,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sign_parser = subparsers.add_parser(
        "sign", help="authenticate one independently reverified offline bundle")
    sign_parser.add_argument("--bundle", required=True, type=Path)
    sign_parser.add_argument("--baseline-a", required=True, type=Path)
    sign_parser.add_argument("--baseline-b", required=True, type=Path)
    sign_parser.add_argument("--private-key", required=True, type=Path)
    sign_parser.add_argument("--out", required=True, type=Path)

    verify_parser = subparsers.add_parser(
        "verify", help="reverify a bundle and its detached authentication")
    verify_parser.add_argument("--bundle", required=True, type=Path)
    verify_parser.add_argument("--baseline-a", required=True, type=Path)
    verify_parser.add_argument("--baseline-b", required=True, type=Path)
    verify_parser.add_argument("--public-key", required=True, type=Path)
    verify_parser.add_argument("--trusted-key-sha256", required=True)
    verify_parser.add_argument("--signature", required=True, type=Path)

    fingerprint_parser = subparsers.add_parser(
        "fingerprint", help="print an Ed25519 public-key SPKI fingerprint")
    fingerprint_parser.add_argument("--public-key", required=True, type=Path)

    args = parser.parse_args()
    try:
        if args.command == "sign":
            result = sign_bundle(
                args.bundle, args.baseline_a, args.baseline_b,
                args.private_key, args.out)
        elif args.command == "verify":
            result = verify_bundle_authentication(
                args.bundle, args.baseline_a, args.baseline_b, args.public_key,
                args.trusted_key_sha256, args.signature)
        else:
            result = {
                "algorithm": ALGORITHM,
                "signing_key_spki_sha256": key_fingerprint(args.public_key),
            }
        print(json.dumps(result, indent=2, sort_keys=True))
    except (AuthenticationError, OSError, ValueError) as error:
        print(f"updater authentication error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
