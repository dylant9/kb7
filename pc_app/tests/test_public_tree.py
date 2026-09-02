from __future__ import annotations

import base64
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_public_tree", ROOT / "tools" / "check_public_tree.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublicTreeTests(unittest.TestCase):
    def test_local_paths_and_excluded_analysis_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "notes.md").write_text(
                'cd "$HOME/' + 'dev/kb7"\nsource: ISPTool' + 'Main.dll\n')
            result = MODULE.inspect(root)
            self.assertFalse(result["passed"])
            self.assertEqual(len(result["failures"]), 2)

    def test_large_plainly_encoded_binary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("source-only\n")
            encoded = base64.b64encode(bytes(range(256)) * 8).decode("ascii")
            (root / "payload.txt").write_text(encoded)
            result = MODULE.inspect(root)
            self.assertFalse(result["passed"])
            self.assertTrue(any("base64-like" in failure for failure in result["failures"]))

    def test_owner_local_updater_metadata_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bundle.json").write_text("{}\n")
            (root / "simulation.json").write_text("{}\n")
            (root / ".kb7-usb-updater-journal-v1.json").write_text("{}\n")
            (root / "updater-journal.json").write_text("{}\n")
            (root / ".kb7-isp-scratch-restart-state.json").write_text("{}\n")
            (root / "scratch-restart-state.json").write_text("{}\n")
            (root / "innocent-name.json").write_text(
                '{"schema":"kb7-usb-updater-journal-v1"}\n')
            (root / "other-innocent-name.json").write_text(
                '{"schema":"kb7-isp-scratch-restart-state-v1"}\n')
            result = MODULE.inspect(root)
            self.assertFalse(result["passed"])
            self.assertEqual(sum("prohibited artifact filename" in failure
                                 for failure in result["failures"]), 6)
            self.assertTrue(any("owner-local updater journal" in failure
                                for failure in result["failures"]))

    def test_scratch_executor_journal_names_and_schema_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".kb7-usb-updater-scratch-journal-v1.json").write_text(
                "{}\n")
            (root / ".kb7-usb-updater-scratch-journal-v2.json").write_text(
                "{}\n")
            (root / ".kb7-usb-updater-scratch-journal-v3.json").write_text(
                "{}\n")
            (root / "kb7-updater-scratch-journal-20260823.json").write_text(
                "{}\n")
            (root / ".kb7-updater-scratch-journal.ABC123").write_text(
                "{}\n")
            (root / "renamed.json").write_text(
                '{"schema":"kb7-usb-updater-scratch-journal-v1"}\n')
            (root / "renamed-v2.json").write_text(
                '{"schema":"kb7-usb-updater-scratch-journal-v2"}\n')
            (root / "renamed-v3.json").write_text(
                '{"schema":"kb7-usb-updater-scratch-journal-v3"}\n')

            result = MODULE.inspect(root)

            self.assertFalse(result["passed"])
            self.assertEqual(
                sum("prohibited artifact filename" in failure
                    for failure in result["failures"]),
                5,
            )
            self.assertEqual(
                sum("owner-local updater journal" in failure
                    for failure in result["failures"]),
                3,
            )

    def test_loader_reentry_proof_journal_names_and_schema_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kb7-loader-reentry-proof-journal.json").write_text(
                "{}\n")
            (root / ".kb7-loader-reentry-proof-journal.ABC123").write_text(
                "{}\n")
            (root / "renamed-state.json").write_text(
                '{"schema":"kb7-loader-reentry-proof-journal-v1"}\n')

            result = MODULE.inspect(root)

            self.assertFalse(result["passed"])
            self.assertEqual(
                sum("prohibited artifact filename" in failure
                    for failure in result["failures"]),
                2,
            )
            self.assertEqual(
                sum("owner-local updater journal" in failure
                    for failure in result["failures"]),
                1,
            )

    def test_loader_reentry_private_campaign_format_is_rejected_when_renamed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "renamed-proof-campaign.json").write_text(
                '{"format":"KB7 V1.22 fixed loader-reentry proof campaign v1"}\n')

            result = MODULE.inspect(root)

            self.assertFalse(result["passed"])
            self.assertTrue(any(
                "owner-local updater metadata" in failure
                for failure in result["failures"]))

    def test_isp_read_reliability_result_is_rejected_when_renamed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "innocent-result.json").write_text(
                '{"schema":"kb7-fixed-isp-read-reliability-v1"}\n')

            result = MODULE.inspect(root)

            self.assertFalse(result["passed"])
            self.assertTrue(any(
                "owner-local diagnostic result" in failure
                for failure in result["failures"]))

    def test_updater_authentication_and_private_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kb7-updater-authentication-v1.json").write_text(
                "{}\n", encoding="utf-8")
            (root / "release-updater-auth-20260823.json").write_text(
                "{}\n", encoding="utf-8")
            (root / "renamed.json").write_text(
                '{"format":"KB7 offline updater detached authentication v1"}\n',
                encoding="utf-8")
            (root / "innocent.txt").write_text(
                "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n",
                encoding="utf-8")
            (root / "also-innocent.txt").write_text(
                "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----\nnot-a-real-key\n",
                encoding="utf-8")
            (root / "public-material.txt").write_text(
                "-----BEGIN " + "PUBLIC KEY-----\nnot-a-real-key\n",
                encoding="utf-8")

            result = MODULE.inspect(root)

            self.assertFalse(result["passed"])
            self.assertEqual(
                sum("prohibited artifact filename" in failure
                    for failure in result["failures"]),
                2,
            )
            self.assertEqual(
                sum("owner-local updater metadata" in failure
                    for failure in result["failures"]),
                1,
            )
            self.assertEqual(sum("KEY" in failure
                                 for failure in result["failures"]), 3)


if __name__ == "__main__":
    unittest.main()
