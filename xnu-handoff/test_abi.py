import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]


class SourceAbiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = None
        if (HERE / 'audit_abi.py').exists():
            spec = importlib.util.spec_from_file_location('audit_abi', HERE / 'audit_abi.py')
            cls.a = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.a)

    def setUp(self):
        self.assertIsNotNone(self.a, 'pinned ABI oracle is not implemented')

    def test_compile_actual_apple_header_layout(self):
        header = WORK / 'k70-xnu-source/pexpert/pexpert/arm64/boot.h'
        result = self.a.audit_header(header)
        self.assertEqual(result['size'], 0x480)
        self.assertEqual(result['offsets']['physBase'], 0x10)
        self.assertEqual(result['offsets']['Video'], 0x28)
        self.assertEqual(result['offsets']['deviceTreeP'], 0x60)
        self.assertEqual(result['offsets']['CommandLine'], 0x6c)
        self.assertEqual(result['offsets']['bootFlags'], 0x470)
        self.assertEqual(result['offsets']['memSizeActual'], 0x478)
        self.assertEqual(result['header_git_blob'], 'eab75014f92bb6475bdd4225b6e074ad82652ae5')

    def test_modified_header_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'boot.h'; path.write_text('struct boot_args { int x; };')
            with self.assertRaises(ValueError): self.a.audit_header(path)

    def test_real_entry_branches_to_first_cpu_without_losing_x0(self):
        kernel = WORK / 'k70-xnu-kernel/kernel.development.vermeer-build.macho'
        result = self.a.audit_entry(kernel)
        self.assertEqual(result['entry_va'], 0xFFFFFFF0073F9488)
        self.assertEqual(result['branch_target_va'], 0xFFFFFFF0073FB05C)
        self.assertEqual(result['physical_entry'], 0x8803F9488)
        self.assertEqual(result['entry_symbol'], '__start')
        self.assertEqual(result['target_symbol'], '_start_first_cpu')
        self.assertTrue(result['x0_preserved_by_entry_branch'])
        self.assertFalse(result['kernel_executed'])

    def test_wrong_kernel_entry_audit_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'kernel'; path.write_bytes(b'not the kernel')
            with self.assertRaises(ValueError): self.a.audit_entry(path)


if __name__ == '__main__':
    unittest.main()
