from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import json
from pathlib import Path

from kb7studio.profile_binary import compile_profile_binary

ROOT = Path(__file__).resolve().parents[2]


class CHostServerTests(unittest.TestCase):
    def test_atomic_write_fallback_read_select_and_reset(self) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("host C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="kb7-c-host-server-") as temporary:
            executable = Path(temporary) / "host-server-test"
            subprocess.run([
                compiler, "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fno-builtin",
                "-DKB7_HOST_TEST", "-I", str(ROOT / "replacement_fw/include"),
                str(ROOT / "replacement_fw/tests/host_server_host.c"),
                str(ROOT / "replacement_fw/core1/host_server.c"),
                str(ROOT / "replacement_fw/core1/storage.c"),
                str(ROOT / "replacement_fw/core1/profile_blob.c"),
                str(ROOT / "replacement_fw/ui/screen_parser.c"),
                str(ROOT / "replacement_fw/drivers/input_profiles.c"),
                str(ROOT / "replacement_fw/drivers/input_pipeline.c"),
                str(ROOT / "replacement_fw/drivers/keymap.c"),
                str(ROOT / "replacement_fw/drivers/hall_policy.c"),
                str(ROOT / "replacement_fw/common/host_protocol.c"),
                str(ROOT / "replacement_fw/common/crc32.c"),
                str(ROOT / "replacement_fw/common/memory.c"),
                "-o", str(executable),
            ], check=True)
            profile_document = json.loads(
                (ROOT / "pc_app/samples/offline-example-profile.json").read_text())
            profile_document["lighting"]["per_key"] = {}
            profile_path = Path(temporary) / "profile.kbp"
            profile_path.write_bytes(compile_profile_binary(profile_document))
            result = subprocess.run([str(executable), str(profile_path)], check=False)
            if result.returncode == 77:
                self.skipTest("fixed-address host test mappings are unavailable")
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
