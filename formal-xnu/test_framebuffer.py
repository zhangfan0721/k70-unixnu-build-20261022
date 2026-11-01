"""Exercise the actual mapping guard with absent, aliased and partial mappings."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PROBE = C.CFUNCTYPE(C.c_int, C.c_uint64, C.POINTER(C.c_uint64), C.c_void_p)


class FramebufferGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / 'guard.c').write_text('#include "FramebufferGuard.h"\n'
            'int validate(uint64_t va, uint64_t pa, unsigned w, unsigned h, '
            'unsigned stride, unsigned depth, k70_probe probe) {\n'
            ' return k70_framebuffer_valid(va, pa, w, h, stride, depth, probe, 0); }\n')
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-fPIC', '-I', str(HERE), str(root/'guard.c'), '-o', str(root/'guard.so')], check=True)
        cls.lib = C.CDLL(str(root/'guard.so'))
        cls.lib.validate.argtypes = [C.c_uint64, C.c_uint64, C.c_uint, C.c_uint,
                                    C.c_uint, C.c_uint, PROBE]
        cls.lib.validate.restype = C.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check(self, *, va=0xfffffff100000000, pa=0xb8000000, width=1440,
              height=3200, stride=5760, depth=32, hole=None, alias=False):
        seen = []
        @PROBE
        def probe(address, physical, _):
            seen.append(address)
            if hole is not None and address & ~4095 == hole & ~4095:
                return 0
            physical[0] = pa + address - va + (4096 if alias else 0)
            return 1
        result = self.lib.validate(va, pa, width, height, stride, depth, probe)
        return result, seen

    def test_accepts_complete_writable_identity_and_virtual_mappings(self):
        for va in (0xb8000000, 0xfffffff100000000):
            result, seen = self.check(va=va)
            self.assertEqual(result, 1)
            self.assertGreater(len(seen), 4000)
            self.assertIn(va + 5760*3200 - 1, seen)

    def test_rejects_unmapped_middle_before_rendering(self):
        self.assertEqual(self.check(hole=0xfffffff100100000)[0], 0)

    def test_rejects_valid_translation_to_wrong_physical_memory(self):
        self.assertEqual(self.check(alias=True)[0], 0)

    def test_rejects_bad_geometry_and_unaligned_rows(self):
        for changes in ({'depth':16}, {'width':8193}, {'height':0}, {'stride':5756},
                        {'stride':5761}, {'va':0xfffffffffffff000}, {'pa':0}):
            self.assertEqual(self.check(**changes)[0], 0, changes)

    def test_rejects_span_outside_known_display_reservation(self):
        self.assertEqual(self.check(pa=0xb9000000, height=8192)[0], 0)


if __name__ == '__main__':
    unittest.main()
