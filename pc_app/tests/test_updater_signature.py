from __future__ import annotations

import base64
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "flash-access" / "kb7-updater-sign.py"
SPEC = importlib.util.spec_from_file_location("kb7_updater_sign_tested", TOOL)
assert SPEC is not None and SPEC.loader is not None
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)


class UpdaterSignatureTests(unittest.TestCase):
    def make_key_pair(self, root: Path, name: str = "release") -> tuple[Path, Path]:
        private = root / f"{name}-private.pem"
        public = root / f"{name}-public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(private)],
            check=True, capture_output=True)
        private.chmod(0o600)
        subprocess.run(
            ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
            check=True, capture_output=True)
        return private, public

    def make_bundle(self, root: Path) -> tuple[Path, dict[str, object]]:
        bundle = root / "bundle"
        bundle.mkdir()
        contents = {
            "bundle.json": b'{"offline":"fixture"}\n',
            "simulation.json": b'{"simulation":"fixture"}\n',
            "core0-sector-image.bin": b"core0-fixture",
            "core1-sector-image.bin": b"core1-fixture",
            "poison-blocks.bin": b"poison-fixture",
        }
        for name, data in contents.items():
            (bundle / name).write_bytes(data)
        descriptor: dict[str, object] = {
            "format": "KB7 V1.22 manifest-preserving paired bundle v1",
            "schema": 1,
            "bundle_id": "1" * 64,
            "baseline_sha256": "2" * 64,
            "target_full_sha256": "3" * 64,
            "pair_id": "4" * 32,
            "offline_only": True,
            "device_io": False,
            "unsigned": True,
            "execution_authorized": False,
            "flash_approved": False,
        }
        return bundle, descriptor

    def planner(self, descriptor: dict[str, object]) -> types.SimpleNamespace:
        return types.SimpleNamespace(
            verify_bundle=mock.Mock(return_value={"invariants_passed": ["fixture"]}),
            load_descriptor=mock.Mock(return_value=descriptor),
        )

    def test_sign_and_verify_require_full_planner_reverification_and_trust_pin(
            self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, descriptor = self.make_bundle(root)
            private, public = self.make_key_pair(root)
            baseline_a = root / "baseline-a.bin"
            baseline_b = root / "baseline-b.bin"
            baseline_a.write_bytes(b"fixture-a")
            baseline_b.write_bytes(b"fixture-b")
            envelope = root / "release-auth.json"
            sign_planner = self.planner(descriptor)
            bundle_before = {
                path.name: path.read_bytes() for path in bundle.iterdir()
            }

            signed = AUTH.sign_bundle(
                bundle, baseline_a, baseline_b, private, envelope,
                planner=sign_planner)

            self.assertEqual(sign_planner.verify_bundle.call_count, 1)
            self.assertEqual(sign_planner.load_descriptor.call_count, 1)
            self.assertEqual(
                {path.name: path.read_bytes() for path in bundle.iterdir()},
                bundle_before)
            self.assertFalse(signed["execution_authorized"])
            self.assertFalse(signed["flash_approved"])
            self.assertEqual(stat.S_IMODE(envelope.stat().st_mode), 0o600)
            fingerprint = AUTH.key_fingerprint(public)
            self.assertEqual(signed["signing_key_spki_sha256"], fingerprint)
            verify_planner = self.planner(descriptor)

            verified = AUTH.verify_bundle_authentication(
                bundle, baseline_a, baseline_b, public, fingerprint, envelope,
                planner=verify_planner)

            self.assertTrue(verified["authenticated"])
            self.assertFalse(verified["execution_authorized"])
            self.assertFalse(verified["flash_approved"])
            self.assertEqual(verify_planner.verify_bundle.call_count, 1)
            document = json.loads(envelope.read_text(encoding="utf-8"))
            self.assertEqual([item["name"] for item in document["statement"]["files"]],
                             list(AUTH.BUNDLE_FILES))
            self.assertEqual(document["statement"]["policy"], {
                "bundle_unsigned": True,
                "device_io": False,
                "offline_only": True,
                "execution_authorized": False,
                "flash_approved": False,
                "signature_is_install_authorization": False,
            })

    def test_wrong_trust_pin_key_signature_and_bundle_tampering_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, descriptor = self.make_bundle(root)
            private, public = self.make_key_pair(root, "right")
            _other_private, other_public = self.make_key_pair(root, "wrong")
            baseline_a = root / "a"
            baseline_b = root / "b"
            baseline_a.write_bytes(b"a")
            baseline_b.write_bytes(b"b")
            envelope = root / "auth.json"
            AUTH.sign_bundle(bundle, baseline_a, baseline_b, private, envelope,
                             planner=self.planner(descriptor))
            fingerprint = AUTH.key_fingerprint(public)

            with self.assertRaisesRegex(AUTH.AuthenticationError, "trusted fingerprint"):
                AUTH.verify_bundle_authentication(
                    bundle, baseline_a, baseline_b, public, "0" * 64, envelope,
                    planner=self.planner(descriptor))
            with self.assertRaisesRegex(AUTH.AuthenticationError, "trusted fingerprint"):
                AUTH.verify_bundle_authentication(
                    bundle, baseline_a, baseline_b, other_public, fingerprint, envelope,
                    planner=self.planner(descriptor))

            document = json.loads(envelope.read_text(encoding="utf-8"))
            changed_signature = bytearray(base64.b64decode(
                document["signature_base64"], validate=True))
            changed_signature[0] ^= 1
            document["signature_base64"] = base64.b64encode(
                changed_signature).decode("ascii")
            envelope.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(AUTH.AuthenticationError):
                AUTH.verify_bundle_authentication(
                    bundle, baseline_a, baseline_b, public, fingerprint, envelope,
                    planner=self.planner(descriptor))

            AUTH.sign_bundle(
                bundle, baseline_a, baseline_b, private, root / "auth-2.json",
                planner=self.planner(descriptor))
            (bundle / "simulation.json").write_bytes(b"changed")
            with self.assertRaisesRegex(AUTH.AuthenticationError,
                                        "does not exactly match"):
                AUTH.verify_bundle_authentication(
                    bundle, baseline_a, baseline_b, public, fingerprint,
                    root / "auth-2.json", planner=self.planner(descriptor))

    def test_strict_envelope_rejects_unknown_duplicate_nonfinite_and_symlink(
            self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unknown = root / "unknown.json"
            unknown.write_text('{"extra":1}\n', encoding="utf-8")
            with self.assertRaisesRegex(AUTH.AuthenticationError, "unknown fields"):
                bundle, descriptor = self.make_bundle(root)
                _private, public = self.make_key_pair(root)
                AUTH.verify_bundle_authentication(
                    bundle, root / "a", root / "b", public,
                    AUTH.key_fingerprint(public), unknown,
                    planner=self.planner(descriptor))

            duplicate = root / "duplicate.json"
            duplicate.write_text('{"format":"a","format":"b"}\n', encoding="utf-8")
            with self.assertRaisesRegex(AUTH.AuthenticationError, "duplicate JSON key"):
                AUTH.strict_json(duplicate)
            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"value":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(AUTH.AuthenticationError, "non-finite"):
                AUTH.strict_json(nonfinite)
            link = root / "linked.json"
            link.symlink_to(duplicate)
            with self.assertRaisesRegex(AUTH.AuthenticationError, "non-symlink"):
                AUTH.strict_json(link)

    def test_private_key_permissions_output_location_and_overwrite_are_locked(
            self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, descriptor = self.make_bundle(root)
            private, _public = self.make_key_pair(root)
            private.chmod(0o640)
            with self.assertRaisesRegex(AUTH.AuthenticationError, "permissions"):
                AUTH.sign_bundle(bundle, root / "a", root / "b", private,
                                 root / "auth.json", planner=self.planner(descriptor))
            private.chmod(0o600)
            with self.assertRaisesRegex(AUTH.AuthenticationError, "outside the bundle"):
                AUTH.sign_bundle(bundle, root / "a", root / "b", private,
                                 bundle / "auth.json", planner=self.planner(descriptor))
            output = root / "existing.json"
            output.write_text("preserve me", encoding="utf-8")
            with self.assertRaisesRegex(AUTH.AuthenticationError, "overwrite"):
                AUTH.sign_bundle(bundle, root / "a", root / "b", private,
                                 output, planner=self.planner(descriptor))
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve me")
            real_parent = root / "real-output"
            real_parent.mkdir()
            linked_parent = root / "linked-output"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(AUTH.AuthenticationError, "non-symlink"):
                AUTH.sign_bundle(bundle, root / "a", root / "b", private,
                                 linked_parent / "auth.json",
                                 planner=self.planner(descriptor))

    def test_planner_rejection_precedes_signing_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, descriptor = self.make_bundle(root)
            private, _public = self.make_key_pair(root)
            planner = self.planner(descriptor)
            planner.verify_bundle.side_effect = ValueError("invalid bundle")
            output = root / "auth.json"
            with mock.patch.object(AUTH, "sign_bytes") as sign_bytes:
                with self.assertRaisesRegex(ValueError, "invalid bundle"):
                    AUTH.sign_bundle(bundle, root / "a", root / "b", private,
                                     output, planner=planner)
            sign_bytes.assert_not_called()
            self.assertFalse(output.exists())
            invalid_descriptor = dict(descriptor, flash_approved=True)
            with mock.patch.object(AUTH, "sign_bytes") as sign_bytes:
                with self.assertRaisesRegex(AUTH.AuthenticationError,
                                            "fail-closed policy"):
                    AUTH.sign_bundle(
                        bundle, root / "a", root / "b", private,
                        root / "invalid-policy.json",
                        planner=self.planner(invalid_descriptor))
            sign_bytes.assert_not_called()
            _unused_private, public = self.make_key_pair(root, "verification")
            envelope = root / "untrusted.json"
            envelope.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(AUTH, "verify_bytes") as verify_bytes:
                with self.assertRaisesRegex(ValueError, "invalid bundle"):
                    AUTH.verify_bundle_authentication(
                        bundle, root / "a", root / "b", public,
                        AUTH.key_fingerprint(public), envelope, planner=planner)
            verify_bytes.assert_not_called()

    def test_non_ed25519_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / "rsa-private.pem"
            public = root / "rsa-public.pem"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt",
                 "rsa_keygen_bits:2048", "-out", str(private)],
                check=True, capture_output=True)
            private.chmod(0o600)
            subprocess.run(
                ["openssl", "pkey", "-in", str(private), "-pubout",
                 "-out", str(public)], check=True, capture_output=True)
            with self.assertRaisesRegex(AUTH.AuthenticationError, "not an Ed25519"):
                AUTH.key_fingerprint(public)

    def test_cli_has_no_hardware_execution_or_raw_authority(self) -> None:
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        helps = []
        for arguments in (["--help"], ["sign", "--help"],
                          ["verify", "--help"], ["fingerprint", "--help"]):
            result = subprocess.run(
                [sys.executable, str(TOOL), *arguments], text=True,
                capture_output=True, env=environment, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            helps.append(result.stdout)
        surface = "\n".join(helps)
        for forbidden in (
                "--commit", "--execute", "--device", "--offset", "--cdb",
                "--payload", "--force", "--skip", "--operation-index"):
            self.assertNotIn(forbidden, surface)
        self.assertIn("--trusted-key-sha256", surface)


if __name__ == "__main__":
    unittest.main()
