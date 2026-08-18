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
    def test_large_plainly_encoded_binary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("source-only\n")
            encoded = base64.b64encode(bytes(range(256)) * 8).decode("ascii")
            (root / "payload.txt").write_text(encoded)
            result = MODULE.inspect(root)
            self.assertFalse(result["passed"])
            self.assertTrue(any("base64-like" in failure for failure in result["failures"]))


if __name__ == "__main__":
    unittest.main()
