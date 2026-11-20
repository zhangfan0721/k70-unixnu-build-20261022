import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'restore_pinned_kernel.py'
BUNDLE = HERE.parent / 'pinned-inputs/40518851995'
KERNEL = 'kernel.development.vermeer-build.macho'
PIN = '5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8'
sha = lambda b: hashlib.sha256(b).hexdigest()
module = None
if SOURCE.exists():
    spec = importlib.util.spec_from_file_location('pinned_restore', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def fixture(changes=None, extras=()):
    kernel = b'fixture-kernel'
    items = {
        KERNEL: kernel,
        'SHA256SUMS': (sha(kernel) + '  ' + KERNEL + '\n').encode(),
        'build-report.json': b'{}',
        'crypto-hmac.json': b'{}',
        'symbols.txt': b'fixture-symbols',
    }
    for name, value in (changes or {}).items():
        if value is None:
            items.pop(name)
        else:
            items[name] = value
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for name, value in list(items.items()) + list(extras):
            archive.writestr(name, value)
    return out.getvalue(), sha(kernel)


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'pinned kernel restorer missing')

    def validate(self, raw, kernel_sha):
        return module.validate_archive(raw, sha(raw), kernel_sha)

    def test_valid_archive_returns_exact_bytes(self):
        raw, kernel_sha = fixture()
        files = self.validate(raw, kernel_sha)
        self.assertEqual(len(files), 5)
        self.assertEqual(files[KERNEL], b'fixture-kernel')

    def test_corruption_rejected_by_zip_hash(self):
        raw, kernel_sha = fixture()
        changed = raw[:-1] + bytes([raw[-1] ^ 1])
        with self.assertRaisesRegex(ValueError, 'archive SHA'):
            module.validate_archive(changed, sha(raw), kernel_sha)

    def test_wrong_kernel_hash_rejected(self):
        raw, _ = fixture()
        with self.assertRaisesRegex(ValueError, 'kernel SHA'):
            self.validate(raw, '0' * 64)

    def test_manifest_must_bind_same_kernel(self):
        raw, kernel_sha = fixture({'SHA256SUMS': b'not the pinned manifest\n'})
        with self.assertRaisesRegex(ValueError, 'manifest'):
            self.validate(raw, kernel_sha)

    def test_traversal_is_rejected(self):
        raw, kernel_sha = fixture(extras=[('../escape', b'bad')])
        with self.assertRaises(ValueError):
            self.validate(raw, kernel_sha)

    def test_duplicate_member_is_rejected(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            raw, kernel_sha = fixture(extras=[(KERNEL, b'duplicate')])
        with self.assertRaises(ValueError):
            self.validate(raw, kernel_sha)

    def test_symlink_member_is_rejected(self):
        raw, kernel_sha = fixture()
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as original, zipfile.ZipFile(out, 'w') as archive:
            for item in original.infolist():
                if item.filename == 'symbols.txt':
                    item.create_system = 3
                    item.external_attr = 0o120777 << 16
                archive.writestr(item, original.read(item))
        with self.assertRaisesRegex(ValueError, 'regular'):
            self.validate(out.getvalue(), kernel_sha)

    def test_oversized_declared_expansion_rejected(self):
        raw, kernel_sha = fixture()
        data = bytearray(raw)
        central = data.index(b'PK\x01\x02')
        struct.pack_into('<I', data, central + 24, 32 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, 'size'):
            self.validate(bytes(data), kernel_sha)

    def test_missing_member_is_rejected(self):
        raw, kernel_sha = fixture({'symbols.txt': None})
        with self.assertRaises(ValueError):
            self.validate(raw, kernel_sha)

    def test_extra_member_is_rejected(self):
        raw, kernel_sha = fixture(extras=[('extra', b'bad')])
        with self.assertRaises(ValueError):
            self.validate(raw, kernel_sha)

    def test_encrypted_member_is_rejected(self):
        raw, kernel_sha = fixture()
        data = bytearray(raw)
        central = data.index(b'PK\x01\x02')
        struct.pack_into('<H', data, central + 8, 1)
        with self.assertRaisesRegex(ValueError, 'encrypted'):
            self.validate(bytes(data), kernel_sha)

    def test_truncated_archive_is_rejected(self):
        raw, kernel_sha = fixture()
        with self.assertRaises(ValueError):
            self.validate(raw[:30], kernel_sha)

    def test_actual_preserved_bundle_restores_pinned_kernel(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'kernel-input'
            report = module.restore(BUNDLE, output)
            self.assertEqual(sha((output / KERNEL).read_bytes()), PIN)
            self.assertEqual(report['kernel_sha256'], PIN)
            self.assertEqual(report['restored_files'], 5)
            self.assertEqual(report['source_run_id'], 40518851995)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'existing'
            output.mkdir()
            (output / 'keep').write_bytes(b'user-data')
            with self.assertRaises(FileExistsError):
                module.restore(BUNDLE, output)
            self.assertEqual((output / 'keep').read_bytes(), b'user-data')

    def test_bad_evidence_prevents_any_output(self):
        import shutil
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / 'bundle'
            bundle.mkdir()
            shutil.copyfile(BUNDLE / 'platform.zip', bundle / 'platform.zip')
            (bundle / 'evidence.zip').write_bytes(b'corrupt')
            output = Path(root) / 'kernel-input'
            with self.assertRaisesRegex(ValueError, 'evidence SHA'):
                module.restore(bundle, output)
            self.assertFalse(output.exists())

    def test_cli_cannot_override_pinned_hash(self):
        result = subprocess.run([sys.executable, str(SOURCE), '--output', 'unused',
                                 '--expected-sha', '0' * 64], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'unrecognized arguments', result.stderr)


if __name__ == '__main__':
    unittest.main()
