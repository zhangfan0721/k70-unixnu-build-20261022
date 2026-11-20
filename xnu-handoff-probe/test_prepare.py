import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get('K70_UEFI_SOURCE', HERE.parents[1] / 'k70-uefi-source'))
DTB = Path(os.environ.get('K70_DTB', HERE.parents[1] / 'k70-device-source/scripts/data/vermeer.dtb'))
KERNEL = Path(os.environ.get('K70_KERNEL', HERE.parents[1] / 'k70-xnu-kernel/kernel.development.vermeer-build.macho'))


class HandoffPackageTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / 'prepare.py').exists(), 'handoff package generator not implemented')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['Platforms/Xiaomi/vermeerPkg', 'Resources/Configs/vermeer.toml']:
            src, dst = SOURCE / name, self.root / name; dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir(): shutil.copytree(src, dst)
            else: shutil.copy2(src, dst)
        self.kernel = self.root / 'kernel'; self.kernel.write_bytes(KERNEL.read_bytes())

    def run_prepare(self):
        return subprocess.run([sys.executable, str(HERE / 'prepare.py'), '--uefi', str(self.root),
            '--dtb', str(DTB), '--kernel', str(self.kernel), '--payload', str(self.root / 'payload.bin')],
            capture_output=True, text=True)

    def test_only_copied_package_gets_full_window_and_seed_reader(self):
        original = self.root / 'Platforms/Xiaomi/vermeerPkg'
        before = {str(p.relative_to(original)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in original.rglob('*') if p.is_file()}
        result = self.run_prepare(); self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['mode'], 'handoff-data-no-jump')
        self.assertEqual(report['handoff']['window_bytes'], 0x10000000)
        self.assertFalse(report['hardware_tested']); self.assertFalse(report['kernel_executed'])
        self.assertEqual(report['probe_memory_map_sha256'], 'dd220c7e8f907b460e0ce1de582f00bd3b5b30bc0fc669cf230952e97282b22c')
        self.assertEqual((self.root / 'payload.bin').stat().st_size, 21434928)
        app = self.root / 'Platforms/Xiaomi/vermeerProbePkg/Probe'
        source = (app / 'Preflight.c').read_text()
        self.assertIn('EFI_SIZE_TO_PAGES(K70_HANDOFF_WINDOW)', source)
        self.assertIn('(UINTN)PayloadBytes - K70_SEED_TRAILER_BYTES', source)
        self.assertIn('K70PrepareHandoff', source)
        self.assertIn('FreePages(Destination, Pages)', source)
        self.assertNotIn('PREFLIGHT PASS - KERNEL JUMP DISABLED', source)
        header = (app / 'HandoffTemplates.h').read_text()
        def array(name):
            body = re.search(name + r'\[\d+\] = \{([^}]+)\}', header).group(1)
            return bytes(int(x.strip(), 16) for x in body.split(',') if x.strip())
        args, tree = array('mHandoffArgs'), array('mHandoffTreeTemplate')
        offset = report['handoff']['seed_offset']
        self.assertEqual(len(args), 1152); self.assertEqual(len(tree), 1724)
        self.assertEqual(tree[offset:offset + 64], bytes(64))
        self.assertEqual(hashlib.sha256(args).hexdigest(), report['handoff']['args_sha256'])
        self.assertEqual(hashlib.sha256(tree).hexdigest(), report['handoff']['zero_seed_tree_sha256'])
        after = {str(p.relative_to(original)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in original.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_wrong_kernel_creates_no_output(self):
        self.kernel.write_bytes(b'wrong')
        result = self.run_prepare(); self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'Platforms/Xiaomi/vermeerProbePkg').exists())
        self.assertFalse((self.root / 'payload.bin').exists())


if __name__ == '__main__': unittest.main()
