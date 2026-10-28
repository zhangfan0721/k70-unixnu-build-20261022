"""Exercise generated firmware configuration against the real pinned K70 source."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("K70_UEFI_SOURCE", HERE.parent.parent / "k70-uefi-source"))
DTB = Path(os.environ.get("K70_DTB", HERE.parent.parent / "k70-device-source/scripts/data/vermeer.dtb"))


class ProbePackageTests(unittest.TestCase):
    def test_generator_is_available(self):
        self.assertTrue((HERE / "prepare.py").is_file(), "UEFI probe generator is not implemented")

    def setUp(self):
        if self._testMethodName == "test_generator_is_available":
            return
        if not (HERE / "prepare.py").is_file():
            self.skipTest("Generator is not implemented yet")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for item in ["Platforms/Xiaomi/vermeerPkg", "Resources/Configs/vermeer.toml"]:
            src, dst = SOURCE / item, self.root / item
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    def prepare(self):
        return subprocess.run([sys.executable, str(HERE / "prepare.py"), "--uefi", str(self.root), "--dtb", str(DTB)], text=True, capture_output=True)

    def test_generates_probe_without_changing_original_board(self):
        original = self.root / "Platforms/Xiaomi/vermeerPkg"
        before = {p.relative_to(original): hashlib.sha256(p.read_bytes()).hexdigest() for p in original.rglob("*") if p.is_file()}
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = {p.relative_to(original): hashlib.sha256(p.read_bytes()).hexdigest() for p in original.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        probe = self.root / "Platforms/Xiaomi/vermeerProbePkg"
        dsc = (probe / "vermeerProbe.dsc").read_text()
        fdf = (probe / "vermeerProbe.fdf").read_text()
        device = (probe / "DeviceBuild.py").read_text()
        self.assertIn("Build/vermeerProbePkg", dsc)
        self.assertIn("vermeerProbePkg/vermeerProbe.fdf", dsc)
        self.assertIn("vermeerProbePkg/vermeerProbe.dsc", device)
        self.assertIn("vermeerProbePkg/Probe/VermeerProbe.inf", fdf)
        self.assertIn("VERMEER_VENDOR_HW                = 0", dsc)
        self.assertIn("VERMEER_CHINESE_UI             = 0", dsc)
        for p in probe.rglob("*"):
            if p.suffix.lower() not in (".dsc", ".fdf", ".inc", ".py"):
                continue
            text = p.read_text()
            active = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
            for unwanted in ["UniXNUPkg/", "DarwinBootPkg/", "UniXNULib|", "vermeerPkg/", "DiskIoDxe.inf", "PartitionDxe.inf", "Fat.inf", "UsbMassStorageDxe.inf", "UFSDxe.inf", "SdccDxe.inf"]:
                self.assertNotIn(unwanted, active, f"Unexpected module/path in {p.relative_to(probe)}")
        self.assertEqual((self.root / "Resources/Configs/vermeerProbe.toml").read_bytes(), (SOURCE / "Resources/Configs/vermeer.toml").read_bytes())
        self.assertEqual((self.root / "Resources/DTBs/vermeerProbe.dtb").read_bytes(), DTB.read_bytes())

    def test_refuses_unknown_source_before_creating_output(self):
        source = self.root / "Platforms/Xiaomi/vermeerPkg/vermeer.dsc"
        source.write_bytes(source.read_bytes() + b"\n# unsupported edit\n")
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source hash mismatch", result.stderr)
        self.assertFalse((self.root / "Platforms/Xiaomi/vermeerProbePkg").exists())

    def test_preserves_required_capsule_architecture_provider(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        probe = self.root / "Platforms/Xiaomi/vermeerProbePkg"
        module = "INF MdeModulePkg/Universal/CapsuleRuntimeDxe/CapsuleRuntimeDxe.inf"
        for name in ["Include/DXE.inc", "Include/APRIORI.inc"]:
            active = "\n".join(line for line in (probe / name).read_text().splitlines() if not line.lstrip().startswith("#"))
            self.assertIn(module, active, "DxeCore requires Capsule Arch before BDS entry")

    def test_conventional_ram_stays_inside_verified_k70_system_ram(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.root / "Platforms/Xiaomi/vermeerProbePkg/Library/MemoryMapLib/MemoryMapLib.c"
        entries = re.findall(r'\{"[^"]+",\s*(0x[\dA-Fa-f]+),\s*(0x[\dA-Fa-f]+),\s*AddMem,\s*SYS_MEM,\s*SYS_MEM_CAP,\s*Conv,', source.read_text())
        self.assertEqual(len(entries), 5)
        # Device /proc/iomem, cross-checked against its runtime DT (2026-10-28).
        # These are containment limits, not a request to add all available RAM.
        verified = [(0xA4A81000, 0xD4D00000), (0xE7CB0000, 0xFF800000),
                    (0x880000000, 0x8B9D00000)]
        for base, size in entries:
            start, length = int(base, 16), int(size, 16)
            self.assertGreater(length, 0)
            self.assertTrue(any(low <= start and start + length <= high for low, high in verified),
                            f"Unverified conventional RAM: {start:#x}..{start+length:#x}")
        self.assertIn(("0xE7CB0000", "0x17B50000"), entries)
        self.assertIn(("0x880000000", "0x39D00000"), entries)

    def test_probe_does_not_expand_ram_from_unverified_boot_dtb(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        probe = self.root / "Platforms/Xiaomi/vermeerProbePkg"
        for name in ["Include/DXE.inc", "Include/APRIORI.inc"]:
            active = "\n".join(line for line in (probe / name).read_text().splitlines() if not line.lstrip().startswith("#"))
            self.assertNotIn("VermeerBootMemoryDxe.inf", active)

    def test_refuses_unknown_memory_map_before_creating_output(self):
        source = self.root / "Platforms/Xiaomi/vermeerPkg/Library/MemoryMapLib/MemoryMapLib.c"
        source.write_bytes(source.read_bytes() + b"\n// unsupported map edit\n")
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Source hash mismatch", result.stderr)
        self.assertFalse((self.root / "Platforms/Xiaomi/vermeerProbePkg").exists())

    def test_refuses_existing_output_without_overwriting(self):
        destination = self.root / "Platforms/Xiaomi/vermeerProbePkg"
        destination.mkdir()
        marker = destination / "keep.txt"
        marker.write_text("preserve")
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
