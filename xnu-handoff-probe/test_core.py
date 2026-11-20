import ctypes as C
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BASE, WINDOW, SPAN = 0x880004000, 0x10000000, 0x1544000


class Layout(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ['Base', 'Capacity', 'Args', 'Tree', 'TreeVa', 'Top', 'TreeBytes']]


class RuntimeCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = None
        if not (HERE / 'HandoffCore.c').exists(): return
        cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        binary = Path(cls.temp.name) / 'core.so'
        subprocess.run(['cc', '-DK70_HOST', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-fPIC', '-I', str(HERE.parent / 'xnu-preflight'),
                        str(HERE / 'HandoffCore.c'), '-o', str(binary)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(binary))
        cls.lib.K70HandoffPlan.argtypes = [C.c_uint64] * 4 + [C.POINTER(Layout)]
        cls.lib.K70CheckBootArgs.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(Layout)]
        cls.lib.K70SeedMetadata.argtypes = [C.c_void_p, C.c_size_t]
        cls.lib.K70CheckTree.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_size_t, C.c_void_p]
        spec = importlib.util.spec_from_file_location('host_handoff', HERE.parent / 'xnu-handoff/handoff.py')
        cls.host = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.host)

    def setUp(self):
        self.assertIsNotNone(self.lib, 'runtime handoff core not implemented')
        self.seed = b'S' * 64
        self.tree = self.host.make_tree(BASE, WINDOW, self.seed)
        self.slot = self.tree.index(self.seed)
        self.template = self.tree[:self.slot] + bytes(64) + self.tree[self.slot + 64:]
        self.layout = Layout()
        self.assertEqual(self.lib.K70HandoffPlan(BASE, WINDOW, SPAN, len(self.tree), C.byref(self.layout)), 1)
        host_layout = self.host.plan_layout(SPAN, self.host.KERNEL['vm_base'], 0x3f5488, len(self.tree))
        self.args = self.host.make_args(host_layout, len(self.tree), self.host.GOP, '-v')

    def check_args(self, data, layout=None):
        return self.lib.K70CheckBootArgs(C.create_string_buffer(bytes(data)), len(data),
                                         C.byref(self.layout if layout is None else layout))

    def test_plan_matches_independent_host_and_keeps_high_bits(self):
        self.assertEqual(self.layout.Args, 0x881548000)
        self.assertEqual(self.layout.Tree, 0x881549000)
        self.assertEqual(self.layout.TreeVa, 0xfffffff008549000)
        self.assertEqual(self.layout.Top, 0x88154c000)
        self.assertEqual(self.layout.Capacity, WINDOW)
        self.assertEqual(self.check_args(self.args), 1)

    def test_bad_plan_leaves_output_untouched(self):
        for args in [(BASE & 0xffffffff, WINDOW, SPAN, 1724), (BASE, SPAN, SPAN, 1724),
                     (BASE, WINDOW + 4096, SPAN, 1724), (BASE, WINDOW, SPAN + 4096, 1724),
                     (BASE, WINDOW, SPAN, 0), (BASE, WINDOW, SPAN, 65537),
                     (0xffffffffffffc000, WINDOW, SPAN, 1724)]:
            p = Layout(*([0xa5a5a5a5a5a5a5a5] * 7)); before = bytes(p)
            self.assertEqual(self.lib.K70HandoffPlan(*args, C.byref(p)), 0)
            self.assertEqual(bytes(p), before)

    def test_arg_truncation_padding_ranges_video_and_command_fail(self):
        for offset in [0, 2, 4, 8, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38,
                       0x40, 0x48, 0x50, 0x58, 0x5c, 0x60, 0x68,
                       0x6c, 0x46b, 0x46c, 0x470, 0x478]:
            b = bytearray(self.args); b[offset] ^= 1
            with self.subTest(offset=offset): self.assertEqual(self.check_args(b), 0)
        self.assertEqual(self.check_args(self.args[:-1]), 0)
        self.assertEqual(self.check_args(self.args + b'\0'), 0)

    def test_untrusted_layout_cannot_bless_changed_pointer(self):
        b = bytearray(self.args); p = Layout.from_buffer_copy(self.layout)
        p.TreeVa = p.Tree
        struct.pack_into('<Q', b, 0x60, p.TreeVa)
        self.assertEqual(self.check_args(b, p), 0)

    def test_seed_metadata_shape_and_nonzero_required(self):
        good = struct.pack('<8sII64s', b'K70SEED1', 1, 64, self.seed)
        good += hashlib.sha256(good).digest()
        self.assertEqual(self.lib.K70SeedMetadata(C.create_string_buffer(good), len(good)), 1)
        for offset in [0, 8, 12]:
            b = bytearray(good); b[offset] ^= 1
            self.assertEqual(self.lib.K70SeedMetadata(C.create_string_buffer(bytes(b)), len(b)), 0)
        zero = good[:16] + bytes(64) + good[80:]
        for b in [good[:-1], good + b'\0', bytes(112), zero]:
            self.assertEqual(self.lib.K70SeedMetadata(C.create_string_buffer(b), len(b)), 0)

    def test_tree_match_only_exempts_seed_slot(self):
        def check(data, slot=None, seed=None):
            return self.lib.K70CheckTree(C.create_string_buffer(bytes(data)),
                C.create_string_buffer(self.template), len(data), self.slot if slot is None else slot,
                C.create_string_buffer(self.seed if seed is None else seed))
        self.assertEqual(check(self.tree), 1)
        for at in [0, self.slot - 1, self.slot, self.slot + 63, self.slot + 64, len(self.tree) - 1]:
            b = bytearray(self.tree); b[at] ^= 1
            self.assertEqual(check(b), 0)
        self.assertEqual(check(self.tree, len(self.tree) - 32), 0)
        self.assertEqual(check(self.tree, seed=bytes(64)), 0)


if __name__ == '__main__': unittest.main()
