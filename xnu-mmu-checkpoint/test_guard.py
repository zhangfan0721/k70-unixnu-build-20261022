import ctypes as C
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class GuardCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib=None
        if not (HERE/'GuardCore.c').exists():return
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        so=Path(cls.temp.name)/'guard.so'
        subprocess.run(['cc','-DK70_HOST','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',
            '-I',str(HERE.parent/'xnu-preflight'),str(HERE/'GuardCore.c'),'-o',str(so)],check=True,capture_output=True)
        cls.lib=C.CDLL(str(so))
        cls.lib.K70DataRange.argtypes=[C.c_void_p,C.c_size_t,C.c_size_t,C.c_uint64,C.c_uint64]
        cls.lib.K70CpuSupportsXnu.argtypes=[C.c_uint64]

    def setUp(self):
        self.assertIsNotNone(self.lib,'owned guard memory-map verifier missing')

    def desc(self,base,pages,kind=2):
        return struct.pack('<IIQQQQ',kind,0,base,0,pages,8)+bytes(8)

    def check(self,data,base=0x880000000,size=0x10004000,stride=48):
        buffer=C.create_string_buffer(data)
        return self.lib.K70DataRange(buffer,len(data),stride,base,size)

    def test_separate_and_merged_loader_data_ownership(self):
        self.assertEqual(self.check(self.desc(0x880000000,4)+self.desc(0x880004000,65536)),1)
        self.assertEqual(self.check(self.desc(0x880000000,65540)),1)

    def test_free_reserved_gap_and_ambiguous_regions_reject(self):
        for data in [self.desc(0x880000000,4,7)+self.desc(0x880004000,65536),
                     self.desc(0x880000000,3)+self.desc(0x880004000,65536),
                     self.desc(0x880000000,65540)+self.desc(0x880000000,4),
                     self.desc(0x880000000,65540)+self.desc(0x880004000,4,7),
                     self.desc(0x880000000,4,0)+self.desc(0x880004000,65536)]:
            self.assertEqual(self.check(data),0)

    def test_shape_overflow_alignment_and_null_reject(self):
        good=self.desc(0x880000000,65540)
        for data,base,size,stride in [(good,0x880000001,4096,48),(good,0x880000000,1,48),
                                      (good,0x880000000,4096,0),(good,0x880000000,4096,39),
                                      (good[:-1],0x880000000,4096,48),
                                      (self.desc(0x880000000,1<<63),0x880000000,4096,48),
                                      (good,(1<<64)-4096,8192,48)]:
            self.assertEqual(self.check(data,base,size,stride),0)
        self.assertEqual(self.lib.K70DataRange(None,48,48,0x880000000,4096),0)

    def test_40bit_and_4k_capabilities_fail_closed(self):
        for pa in range(16):
            for granule in range(16):
                self.assertEqual(self.lib.K70CpuSupportsXnu(pa|(granule<<28)),int(2<=pa<=6 and granule==0))


if __name__=='__main__':unittest.main()

