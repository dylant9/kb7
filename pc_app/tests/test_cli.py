from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb7studio import cli

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def invoke(self, arguments: list[str]) -> tuple[int, str]:
        errors = io.StringIO()
        output = io.StringIO()
        with patch("sys.argv", ["kb7studio", *arguments]), \
                contextlib.redirect_stderr(errors), contextlib.redirect_stdout(output):
            return cli.main(), errors.getvalue()

    def test_bad_json_is_a_concise_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bad.json"
            destination = Path(temporary) / "bad.kbs"
            source.write_text("{")
            status, error = self.invoke(["compile", str(source), str(destination)])
            self.assertEqual(status, 2)
            self.assertIn("kb7studio:", error)
            self.assertNotIn("Traceback", error)
            self.assertFalse(destination.exists())

    def test_protocol_plan_rejects_invalid_transfer_id(self) -> None:
        source = ROOT / "samples" / "offline-example.json"
        with tempfile.TemporaryDirectory() as temporary:
            kbs = Path(temporary) / "screen.kbs"
            plan = Path(temporary) / "plan.json"
            self.assertEqual(self.invoke(["compile", str(source), str(kbs)])[0], 0)
            status, error = self.invoke([
                "protocol-plan", str(kbs), str(plan), "--transfer-id", "0",
            ])
            self.assertEqual(status, 2)
            self.assertIn("nonzero 32-bit", error)
            self.assertFalse(plan.exists())

    def test_valid_plan_contains_only_offline_reports(self) -> None:
        source = ROOT / "samples" / "offline-example.json"
        with tempfile.TemporaryDirectory() as temporary:
            kbs = Path(temporary) / "screen.kbs"
            plan = Path(temporary) / "plan.json"
            self.assertEqual(self.invoke(["compile", str(source), str(kbs)])[0], 0)
            self.assertEqual(self.invoke(["protocol-plan", str(kbs), str(plan)])[0], 0)
            document = json.loads(plan.read_text())
            self.assertFalse(document["device_io"])
            self.assertTrue(document["reports_hex"])


if __name__ == "__main__":
    unittest.main()
