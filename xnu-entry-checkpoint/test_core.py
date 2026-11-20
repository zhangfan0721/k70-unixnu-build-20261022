import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BASE, CAP, SPAN = 0x880004000, 0x10000000, 0x1544000
VA = BASE + 0x3f5488
TCR = (2 << 32) | 24
XN = (1 << 53) | (1 << 54)
NORMAL = (3 << 8) | (1 << 10)


class Page(C.Structure):
    _fields_ = [(x, C.c_uint64) for x in ['Physical', 'Flags', 'Level', 'Raw']]


READ = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint64, C.POINTER(C.c_uint64))


class EntryCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = None
        if not (HERE / 'EntryCore.c').exists(): return
        cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        binary = Path(cls.temp.name) / 'entry.so'
        subprocess.run(['cc', '-DK70_HOST', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(HERE.parent / 'xnu-preflight'), str(HERE / 'EntryCore.c'),
                        '-o', str(binary)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(binary))
        cls.lib.K70EntryWalk.argtypes = [C.c_uint64] * 4 + [READ, C.c_void_p, C.POINTER(Page)]
        cls.lib.K70EntryScopes.argtypes = [C.c_uint64] * 5 + [C.POINTER(C.c_uint64)]
        cls.lib.K70ExitDecision.argtypes = [C.c_uint, C.c_int, C.c_int]

    def setUp(self):
        self.assertIsNotNone(self.lib, 'entry policy/page walker not implemented')
        self.tables = {}; self.reads = []
        for level in range(3):
            table = 0xc0000000 + level * 4096
            index = (VA >> (39 - 9 * level)) & 511
            self.tables[table + index * 8] = table + 4096 | 3
        self.leaf = 0xc0003000 + ((VA >> 12) & 511) * 8
        self.tables[self.leaf] = (VA & ~4095) | NORMAL | XN | 3
        def read(_, address, value):
            self.reads.append(address)
            if address not in self.tables: return 0
            value[0] = self.tables[address]; return 1
        self.reader = READ(read)

    def walk(self, tcr=TCR, ttbr=0xc0000000, mair=0xff, va=VA):
        result = Page(*([0xa5] * 4))
        status = self.lib.K70EntryWalk(tcr, ttbr, mair, va, self.reader, None, C.byref(result))
        return status, result

    def test_4k_leaf_retains_high_physical_bits_and_permissions(self):
        ok, p = self.walk(); self.assertEqual(ok, 1)
        self.assertEqual((p.Physical, p.Flags, p.Level), (VA, 1 | 4, 3))
        self.assertEqual(len(self.reads), 4)
        self.tables[self.leaf] = (VA & ~4095) | NORMAL | (1 << 7) | 3
        ok, p = self.walk(); self.assertEqual(ok, 1)
        self.assertEqual(p.Flags, 1 | 2)

    def test_l1_l2_blocks_resolve_offsets(self):
        for level in [1, 2]:
            table = 0xc0000000 + level * 4096
            at = table + ((VA >> (39 - 9 * level)) & 511) * 8
            old = self.tables[at]
            self.tables[at] = (VA & - (1 << (39 - 9 * level))) | NORMAL | XN | 1
            ok, p = self.walk(); self.assertEqual(ok, 1)
            self.assertEqual((p.Physical, p.Level), (VA, level))
            self.tables[at] = old

    def test_bad_profiles_reject_without_reading(self):
        for tcr, ttbr, va in [(TCR | 1 << 14, 0xc0000000, VA),
                             (TCR ^ 1, 0xc0000000, VA), (24, 0xc0000000, VA),
                             (TCR | 1 << 59, 0xc0000000, VA),
                             (TCR, 0, VA), (TCR, 1 << 44, VA),
                             (TCR, 0xc0000000, 1 << 40)]:
            self.reads.clear(); ok, p = self.walk(tcr=tcr, ttbr=ttbr, va=va)
            self.assertEqual(ok, 0); self.assertEqual(self.reads, [])
            self.assertEqual(bytes(p), bytes(Page(*([0xa5] * 4))))

    def test_invalid_or_restricted_descriptors_fail_closed(self):
        root = 0xc0000000 + ((VA >> 39) & 511) * 8
        original = dict(self.tables)
        for at, value in [(root, 0), (root, NORMAL | 1),
                          (root, original[root] | 1 << 59), (root, original[root] | 1 << 62),
                          (root, (1 << 44) | 3), (self.leaf, original[self.leaf] & ~(1 << 10)),
                          (self.leaf, original[self.leaf] | 1 << 6),
                          (self.leaf, original[self.leaf] ^ 1 << 53),
                          (self.leaf, original[self.leaf] & ~(3 << 8))]:
            self.tables = dict(original); self.tables[at] = value
            ok, _ = self.walk(); self.assertEqual(ok, 0, hex(value))
        self.tables = original
        self.assertEqual(self.walk(mair=0x44)[0], 0)

    def test_unreadable_table_and_misaligned_block_fail(self):
        del self.tables[self.leaf]; self.assertEqual(self.walk()[0], 0)
        at = 0xc0002000 + ((VA >> 21) & 511) * 8
        self.tables[at] = (VA & - (1 << 21)) | 0x1000 | NORMAL | XN | 1
        self.assertEqual(self.walk()[0], 0)

    def test_scopes_are_exactly_three_owned_pages(self):
        pages = (C.c_uint64 * 3)()
        self.assertEqual(self.lib.K70EntryScopes(BASE, CAP, SPAN, 512, 512, pages), 1)
        self.assertEqual(list(pages), [0x8803f9000, 0x8803fb000, 0x881604000])
        for values in [(BASE & 0xffffffff, CAP, SPAN, 512, 512),
                       (BASE, SPAN, SPAN, 512, 512), (BASE, CAP, SPAN + 4, 512, 512),
                       (BASE, CAP, SPAN, 0, 512), (BASE, CAP, SPAN, 4005, 512),
                       (BASE, CAP, SPAN, 512, 4097)]:
            before = bytes(pages)
            self.assertEqual(self.lib.K70EntryScopes(*values, pages), 0)
            self.assertEqual(bytes(pages), before)

    def test_ebs_phase_decisions_never_return_after_attempt(self):
        # RETURN=0, RETRY=1, ENTER=2, HALT=3. exitcode0success/1stale/2other.
        f = self.lib.K70ExitDecision
        self.assertEqual(f(0, 0, 2), 0)
        for attempt in [1, 2]: self.assertEqual(f(attempt, 0, 2), 3)
        self.assertEqual(f(0, 1, 0), 2)
        self.assertEqual(f(0, 1, 1), 1); self.assertEqual(f(1, 1, 1), 1)
        self.assertEqual(f(2, 1, 1), 3)
        for attempt in [0, 1, 2]: self.assertEqual(f(attempt, 1, 2), 3)
        self.assertEqual(f(3, 1, 0), 3)

    def test_cache_line_profile_stays_inside_owned_pages(self):
        self.assertTrue(hasattr(self.lib, 'K70EntryCacheProfile'), 'cache publication profile missing')
        f = self.lib.K70EntryCacheProfile; f.argtypes = [C.c_uint64]
        for d in range(16):
            for i in range(16):
                self.assertEqual(f((d << 16) | i), int(2 <= d <= 10 and 2 <= i <= 10))


if __name__ == '__main__': unittest.main()
