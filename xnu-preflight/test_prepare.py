import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_core import pinned_kernel

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("K70_UEFI_SOURCE", HERE.parents[1] / "k70-uefi-source"))
DTB = Path(os.environ.get("K70_DTB", HERE.parents[1] / "k70-device-source/scripts/data/vermeer.dtb"))


class PreflightPackageTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / "prepare.py").exists(), "Preflight generator is not implemented")
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ["Platforms/Xiaomi/vermeerPkg", "Resources/Configs/vermeer.toml"]:
            src, dst = SOURCE / name, self.root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir(): shutil.copytree(src, dst)
            else: shutil.copy2(src, dst)
        self.kernel = self.root / "kernel.macho"
        self.kernel.write_bytes(pinned_kernel())

    def run_prepare(self):
        return subprocess.run([sys.executable, str(HERE / "prepare.py"), "--uefi", str(self.root),
                               "--dtb", str(DTB), "--kernel", str(self.kernel),
                               "--payload", str(self.root / "payload.bin")], capture_output=True, text=True)

    def test_generates_payload_and_retains_the_validated_memory_profile(self):
        original = self.root / "Platforms/Xiaomi/vermeerPkg"
        before = {str(p.relative_to(original)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in original.rglob("*") if p.is_file()}
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["boot_memory_expansion"])
        self.assertEqual(report["probe_memory_map_sha256"],
                         "dd220c7e8f907b460e0ce1de582f00bd3b5b30bc0fc669cf230952e97282b22c")
        self.assertEqual(report["payload"]["span"], 0x1544000)
        self.assertTrue(report["payload"]["jump_disabled"])
        payload = (self.root / "payload.bin").read_bytes()
        self.assertEqual(len(payload), 21434928)
        self.assertEqual(payload[128:], self.kernel.read_bytes())
        after = {str(p.relative_to(original)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in original.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_wrong_kernel_is_rejected_before_creating_a_package(self):
        self.kernel.write_bytes(b"wrong kernel")
        result = self.run_prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256", result.stderr)
        self.assertFalse((self.root / "Platforms/Xiaomi/vermeerProbePkg").exists())
        self.assertFalse((self.root / "payload.bin").exists())


if __name__ == "__main__":
    unittest.main()
