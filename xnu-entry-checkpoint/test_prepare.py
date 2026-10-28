import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get('K70_UEFI_SOURCE', HERE.parents[1] / 'k70-uefi-source'))
DTB = Path(os.environ.get('K70_DTB', HERE.parents[1] / 'k70-device-source/scripts/data/vermeer.dtb'))
KERNEL = Path(os.environ.get('K70_KERNEL', HERE.parents[1] / 'k70-xnu-kernel/kernel.development.vermeer-build.macho'))


class EntryPackageTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / 'prepare.py').exists(), 'entry integration not implemented')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['Platforms/Xiaomi/vermeerPkg', 'Resources/Configs/vermeer.toml']:
            src, dst = SOURCE / name, self.root / name; dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir(): shutil.copytree(src, dst)
            else: shutil.copy2(src, dst)
        self.kernel = self.root / 'kernel'; self.kernel.write_bytes(KERNEL.read_bytes())

    def run_prepare(self):
        return subprocess.run([sys.executable, str(HERE / 'prepare.py'), '--uefi', str(self.root),
            '--dtb', str(DTB), '--kernel', str(self.kernel), '--payload', str(self.root / 'payload.bin'),
            '--blobs', str(self.root / 'blobs')], capture_output=True, text=True)

    def test_copied_package_binds_checked_blobs_and_post_data_entry(self):
        original = self.root / 'Platforms/Xiaomi/vermeerPkg'
        digest = lambda: {str(p.relative_to(original)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in original.rglob('*') if p.is_file()}
        before = digest(); result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['mode'], 'instrumented-kernel-entry-checkpoint')
        self.assertFalse(report['hardware_tested']); self.assertFalse(report['original_cpu_init_executed'])
        self.assertEqual(report['entry']['original_entry_instruction'], '0x140006f5')
        app = self.root / 'Platforms/Xiaomi/vermeerProbePkg/Probe'
        source = (app / 'Preflight.c').read_text()
        self.assertLess(source.index('Status = K70PrepareHandoff('), source.index('K70EntryCheckpoint(ImageHandle,'))
        self.assertIn('if (!EFI_ERROR(Status))', source)
        self.assertIn('EntryBlobs.h', (app / 'VermeerProbe.inf').read_text())
        self.assertIn('gEfiCpuArchProtocolGuid', (app / 'VermeerProbe.inf').read_text())
        self.assertEqual((app / 'EntryBlobs.h').read_bytes(), (self.root / 'blobs/EntryBlobs.h').read_bytes())
        runtime = (app / 'Entry.c').read_text()
        self.assertIn('CacheMaintenanceLib', (app / 'VermeerProbe.inf').read_text())
        publish = runtime.index('WriteBackDataCacheRange((VOID *)(UINTN)Pages[I], 4096)')
        invalidate = runtime.index('InvalidateInstructionCacheRange((VOID *)(UINTN)Pages[I], 4096)')
        self.assertLess(publish, invalidate)
        self.assertLess(invalidate, runtime.index('Status = gBS->ExitBootServices('))
        self.assertNotIn('HANDOFF DATA PASS - KERNEL JUMP DISABLED', (app / 'Handoff.c').read_text())
        self.assertEqual((self.root / 'payload.bin').stat().st_size, 21434928)
        self.assertEqual(before, digest())

    def test_wrong_kernel_is_rejected_without_generated_package_or_blobs(self):
        self.kernel.write_bytes(b'wrong')
        result = self.run_prepare(); self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'Platforms/Xiaomi/vermeerProbePkg').exists())
        self.assertFalse((self.root / 'blobs').exists())


if __name__ == '__main__': unittest.main()
