"""Independent binary checks for the fixed, non-executable K70 candidate."""
import copy
import importlib.util
from pathlib import Path
import struct
import unittest

HERE = Path(__file__).resolve().parent
VM = 0xFFFFFFF007004000
BASE = 0x880004000
SPAN = 0x1544000
ENTRY = 0x3F5488


def node(name, properties=(), children=()):
    props = [('name', name.encode() + b'\0'), *properties]
    return struct.pack('<II', len(props), len(children)) + b''.join(
        struct.pack('<32sI', key.encode(), len(value)) + value + bytes(-len(value) % 4)
        for key, value in props) + b''.join(children)


class HandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = HERE / 'handoff.py'
        cls.h = None
        if path.exists():
            spec = importlib.util.spec_from_file_location('handoff', path)
            cls.h = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.h)

    def setUp(self):
        self.assertIsNotNone(self.h, 'handoff serializer is not implemented')
        self.tree = self.h.make_tree(BASE, 0x10000000, b'S' * 64)
        self.layout = self.h.plan_layout(SPAN, VM, ENTRY, len(self.tree))
        self.args = self.h.make_args(self.layout, len(self.tree), self.h.GOP, '-v')
        self.kernel = dict(self.h.KERNEL)

    def test_actual_abi_offsets_and_high_addresses(self):
        self.assertEqual(len(self.args), 0x480)
        self.assertEqual(struct.unpack_from('<HH', self.args), (2, 2))
        self.assertEqual(struct.unpack_from('<4Q', self.args, 8),
                         (VM, BASE, 0x10000000, self.layout['top_pa']))
        self.assertEqual(struct.unpack_from('<Q', self.args, 0x60)[0],
                         VM + self.layout['tree_pa'] - BASE)
        self.assertEqual(self.args[0x6c:0x6f], b'-v\0')
        self.assertEqual(struct.unpack_from('<Q', self.args, 0x470)[0], 0)
        self.assertEqual(struct.unpack_from('<Q', self.args, 0x478)[0], 0x10000000)
        self.assertEqual(self.layout['args_pa'], BASE + SPAN)
        self.assertEqual(self.layout['tree_pa'], BASE + SPAN + 4096)
        self.assertEqual(self.layout['entry_pa'], 0x8803F9488)

    def test_video_is_byte_stride_not_pixel_stride(self):
        self.assertEqual(struct.unpack_from('<6Q', self.args, 0x28),
                         (0xB8000000, 1, 5760, 1440, 3200, 32))

    def test_tree_board_scope_and_little_endian_values(self):
        t = self.h.parse_tree(self.tree)
        self.assertEqual(t['/cpus/cpu0']['compatible'], b'arm,cortex-a510\0')
        self.assertEqual(struct.unpack('<I', t['/cpus/cpu0']['timebase-frequency'])[0], 19200000)
        self.assertEqual(struct.unpack('<Q', t['/chosen']['dram-base'])[0], BASE)
        self.assertEqual(struct.unpack('<Q', t['/chosen']['dram-size'])[0], 0x10000000)
        self.assertEqual(struct.unpack('<4Q', t['/arm-io/intc']['reg']),
                         (0x100000, 0x10000, 0x180000, 0x200000))
        self.assertEqual(set(p for p in t if p.startswith('/cpus/')), {'/cpus/cpu0'})
        self.assertNotIn('/psci', t)
        self.assertFalse(any('ufshc' in p for p in t))
        self.assertNotIn('RAMDisk', t['/chosen/memory-map'])

    def test_verified_candidate_never_claims_runtime_ownership(self):
        report = self.h.verify_candidate(self.args, self.tree, self.kernel)
        self.assertFalse(report['execution_ready'])
        self.assertFalse(report['allocation_verified'])
        self.assertEqual(report['window_bytes'], 0x10000000)
        self.assertLessEqual(report['top_pa'], BASE + 0x10000000 - 0x200000)

    def test_wrong_abi_padding_flags_size_and_command_rejected(self):
        for offset in [0, 2, 4, 0x5c, 0x46c, 0x470, 0x478, 0x6c]:
            with self.subTest(offset=offset):
                b = bytearray(self.args); b[offset] ^= 1
                with self.assertRaises(ValueError):
                    self.h.verify_candidate(b, self.tree, self.kernel)
        for b in [self.args[:-1], self.args + b'\0']:
            with self.assertRaises(ValueError):
                self.h.verify_candidate(b, self.tree, self.kernel)

    def test_tree_pointer_physical_instead_of_virtual_rejected(self):
        b = bytearray(self.args)
        struct.pack_into('<Q', b, 0x60, self.layout['tree_pa'])
        with self.assertRaises(ValueError):
            self.h.verify_candidate(b, self.tree, self.kernel)

    def test_conflicting_ranges_and_kernel_profile_rejected(self):
        for offset, value in [(0x10, BASE & 0xffffffff), (0x18, 12 << 30),
                              (0x20, BASE + SPAN - 4096), (0x68, len(self.tree) + 4)]:
            b = bytearray(self.args)
            struct.pack_into('<I' if offset == 0x68 else '<Q', b, offset, value)
            with self.assertRaises(ValueError):
                self.h.verify_candidate(b, self.tree, self.kernel)
        for field in ['kernel_sha256', 'span', 'entry_offset', 'vm_base']:
            k = copy.copy(self.kernel); k[field] = 'bad' if field == 'kernel_sha256' else k[field] + 4
            with self.assertRaises(ValueError):
                self.h.verify_candidate(self.args, self.tree, k)

    def test_window_range_alignment_wrap_and_capacity(self):
        cases = [dict(base=BASE + 4096), dict(base=0xffffffffffffc000),
                 dict(window=0x20000000), dict(window=0x1000000), dict(window=0x10000001)]
        for kw in cases:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.h.plan_layout(SPAN, VM, ENTRY, len(self.tree), **kw)
        with self.assertRaises(ValueError):
            self.h.plan_layout(SPAN, VM, ENTRY, 0x10001)

    def test_invalid_video_and_command_rejected(self):
        for field, value in [('width', 0), ('stride', 100), ('height', 1 << 64),
                             ('size', 4096), ('base', (1 << 64) - 4), ('format', 0)]:
            v = dict(self.h.GOP); v[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.h.make_args(self.layout, len(self.tree), v, '-v')
        for text in ['x' * 1024, '中文', '-v\0bad', 'amfi_get_out_of_my_way=1']:
            with self.assertRaises(ValueError):
                self.h.make_args(self.layout, len(self.tree), self.h.GOP, text)

    def test_tree_truncation_padding_trailing_data_rejected(self):
        for b in [self.tree[:n] for n in [0, 7, 24, 44, len(self.tree) - 1]] + [self.tree + b'\0']:
            with self.assertRaises(ValueError): self.h.parse_tree(b)
        b = bytearray(node('x')); b[-1] = 1
        with self.assertRaises(ValueError): self.h.parse_tree(b)

    def test_tree_duplicates_depth_and_bad_names_rejected(self):
        bad = [node('device-tree', [('name', b'device-tree\0')]),
               node('device-tree', children=[node('x'), node('x')]),
               node('bad/name'), struct.pack('<II', 0xffffffff, 0),
               node('device-tree', [('x' * 32, b'x')])]
        deep = node('leaf')
        for _ in range(18): deep = node('a', children=[deep])
        bad.append(deep)
        for b in bad:
            with self.assertRaises(ValueError): self.h.parse_tree(b)

    def test_profile_mutation_and_seed_rejected(self):
        for b in [self.tree.replace(b'cortex-a510', b'cortex-a715'),
                  self.tree.replace(struct.pack('<Q', BASE), struct.pack('<Q', 0x80000000), 1)]:
            with self.assertRaises(ValueError): self.h.verify_candidate(self.args, b, self.kernel)
        for seed in [b'', bytes(64), b'S' * 63, b'S' * 65]:
            with self.assertRaises(ValueError): self.h.make_tree(BASE, 0x10000000, seed)

    def test_wrong_kernel_fails_before_candidate_build(self):
        with self.assertRaises(ValueError): self.h.build_candidate(b'wrong kernel', b'S' * 64)


if __name__ == '__main__':
    unittest.main()
