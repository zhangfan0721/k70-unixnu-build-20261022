import importlib.util
from pathlib import Path
import struct
import unittest

HERE=Path(__file__).resolve().parent
POOL=0x88017a000
REGS=dict(tcr=0x22a51a251a,ttbr0=POOL,ttbr1=POOL+4096,mair=0x0c0804ff00bb44ff,sctlr=0x3454593d)


class MmuPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=None
        if (HERE/'model.py').exists():
            s=importlib.util.spec_from_file_location('mmu_model',HERE/'model.py')
            cls.m=importlib.util.module_from_spec(s);s.loader.exec_module(cls.m)

    def setUp(self):
        self.assertIsNotNone(self.m,'MMU ownership/translation model missing')
        self.table=bytearray(65536);self.reads=[]
        struct.pack_into('<Q',self.table,34*8,POOL+0x2003)
        struct.pack_into('<Q',self.table,704*8,POOL+0x3003)
        for i in range(128):
            for at in [1024+i,1592+i]:
                struct.pack_into('<Q',self.table,at*8,(0x880000000+i*0x200000)|0x601)
        def read(at):
            self.reads.append(at)
            self.assertGreaterEqual(at,POOL);self.assertLessEqual(at+8,POOL+65536)
            return struct.unpack_from('<Q',self.table,at-POOL)[0]
        self.read=read

    def test_guard_owns_initial_maps_and_identifies_unmapped_tail(self):
        r=self.m.guard_layout(0x880004000,0x10000000,0x880000000,0x4000)
        self.assertEqual((r['owned_start'],r['owned_end']),(0x880000000,0x890004000))
        self.assertEqual((r['mapped_start'],r['mapped_end']),(0x880000000,0x890000000))
        self.assertEqual(r['unmapped_tail_bytes'],0x4000);self.assertTrue(r['maps_contained'])

    def test_guard_layout_rejects_wrong_or_overflowing_profile(self):
        for args in [(0x880004000,0x10000000,0x880004000,0x4000),
                     (0x880004000,0x10000000,0x880000000,0x3000),
                     (0x880004000,0x10004000,0x880000000,0x4000),
                     ((1<<64)-4096,8192,0x880000000,0x4000)]:
            with self.assertRaises(ValueError):self.m.guard_layout(*args)

    def test_actual_physical_and_kva_tables_translate_same_bytes(self):
        for pa in [0x880000000,0x880004000,0x8803f9488,0x881548000,0x880bfbff0,0x88fffffff]:
            kva=0xfffffff007000000+pa-0x880000000
            self.assertEqual(self.m.walk(pa,REGS,self.read),pa)
            self.assertEqual(self.m.walk(kva,REGS,self.read),pa)
        self.assertEqual(self.m.walk(0xab000008803f9488,REGS,self.read),0x8803f9488)

    def test_tail_gop_and_noncanonical_virtual_addresses_fault(self):
        for va in [0x890000000,0x890003fff,0xb8000000,0x7fffffff007004000,1<<64,-1]:
            self.assertIsNone(self.m.walk(va,REGS,self.read))

    def test_unknown_translation_profiles_do_not_read_tables(self):
        for key,value in [('tcr',0x280803518),('ttbr0',POOL+0x4000),('ttbr1',1<<44),('mair',0xff)]:
            r=dict(REGS);r[key]=value;self.reads.clear()
            self.assertIsNone(self.m.walk(0x880004000,r,self.read))
            self.assertEqual(self.reads,[])

    def test_bad_table_addresses_and_permissions_fail_closed(self):
        at=34*8;original=struct.unpack_from('<Q',self.table,at)[0]
        for value in [(1<<44)|3,0x880000003,original|(1<<59),0]:
            struct.pack_into('<Q',self.table,at,value)
            self.assertIsNone(self.m.walk(0x880004000,REGS,self.read))
        struct.pack_into('<Q',self.table,at,original)
        struct.pack_into('<Q',self.table,1024*8,0x880000681)
        self.assertEqual(self.m.walk(0x880004000,REGS,self.read),0x880004000)
        self.assertIsNone(self.m.walk(0x880004000,REGS,self.read,write=True))
        struct.pack_into('<Q',self.table,1024*8,0x880000601|(1<<53)|(1<<54))
        self.assertIsNone(self.m.walk(0x880004000,REGS,self.read,execute=True))

    def test_unreadable_leaf_and_unaligned_block_refuse(self):
        struct.pack_into('<Q',self.table,1024*8,0x880001601)
        self.assertIsNone(self.m.walk(0x880004000,REGS,self.read))
        def missing(at):return None
        self.assertIsNone(self.m.walk(0x880004000,REGS,missing))


if __name__=='__main__':unittest.main()

