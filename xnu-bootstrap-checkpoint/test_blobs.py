import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BASE, ENTRY, FIRST, COMMON = 0x880004000, 0x8803f9488, 0x8803fb05c, 0x8803fb290
VECTOR, POOL, RECORD, TRAMP, ARGS, TREE = 0x8803fa000, 0x88017a000, 0x881606000, 0x881604000, 0x881548000, 0x881549000
FB, ROW = 0xb8000000, 5760


class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = None
        if not (HERE / 'blobs.py').exists(): return
        spec = importlib.util.spec_from_file_location('bootstrap_blobs', HERE / 'blobs.py')
        cls.b = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.b)
        cls.kernel = Path(os.environ.get('K70_KERNEL', HERE.parents[1] / 'k70-xnu-kernel/kernel.development.vermeer-build.macho'))
        cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        cls.out = Path(cls.temp.name) / 'blobs'
        cls.header, cls.report = cls.b.build(cls.kernel, cls.out)
        cls.stub = (cls.out / 'checkpoint.bin').read_bytes()
        cls.transition = (cls.out / 'transition.bin').read_bytes()
        cls.vectors = (cls.out / 'vector-patches.bin').read_bytes()
        sys.path.insert(0, str(HERE.parent / 'xnu-preflight'))
        from payload import materialize
        _, cls.original = materialize(cls.kernel.read_bytes())
        cls.changed = bytearray(cls.original)
        cls.changed[COMMON-BASE:COMMON-BASE+len(cls.stub)] = cls.stub
        for i in range(16): cls.changed[VECTOR-BASE+128*i:VECTOR-BASE+128*i+4] = cls.vectors[4*i:4*i+4]

    def setUp(self):
        self.assertIsNotNone(self.b, 'original bootstrap checkpoint builder missing')

    def test_original_prefix_branch_and_patch_scopes(self):
        r = self.report
        self.assertTrue(r['original_first_cpu_prefix_preserved'])
        self.assertEqual(r['original_prefix_sha256'], hashlib.sha256(self.original[FIRST-BASE:COMMON-BASE]).hexdigest())
        self.assertEqual(self.changed[FIRST-BASE:COMMON-BASE], self.original[FIRST-BASE:COMMON-BASE])
        self.assertEqual(self.changed[ENTRY-BASE:ENTRY-BASE+4], struct.pack('<I', 0x140006f5))
        self.assertLessEqual(len(self.stub), 4096-0x290)
        self.assertEqual(r['code_pages'], [0x8803f9000, 0x8803fb000, TRAMP, VECTOR])
        self.assertFalse(r['bootstrap_map_contained']); self.assertFalse(r['bootstrap_map_will_be_enabled'])
        self.assertEqual(r['instrumented_mapped_sha256'], hashlib.sha256(self.changed).hexdigest())
        for i in range(16):
            instruction = struct.unpack_from('<I', self.vectors, 4*i)[0]
            self.assertEqual(instruction & 0xfc000000, 0x14000000)
            delta = instruction & 0x3ffffff
            if delta & 0x2000000: delta -= 1 << 26
            self.assertEqual(VECTOR + 128*i + delta*4, COMMON + r['checkpoint_symbols']['exception_vector_%d' % i])

    def test_expected_pool_bounds_and_descriptor_profile(self):
        t = self.b.expected_tables()
        self.assertEqual(len(t), 65536)
        words = struct.unpack('<8192Q', t)
        self.assertEqual(sum(x != 0 for x in words), 258)
        self.assertEqual(words[34], POOL+0x2003); self.assertEqual(words[704], POOL+0x3003)
        self.assertEqual(words[1024], 0x880000601); self.assertEqual(words[1151], 0x88fe00601)
        self.assertEqual(words[1592:1720], words[1024:1152])
        self.assertEqual(words[1720], 0)

    def test_wrong_kernel_refused_before_output(self):
        bad = Path(self.temp.name) / 'bad'; bad.write_bytes(b'wrong')
        out = Path(self.temp.name) / 'bad-output'
        with self.assertRaises(ValueError): self.b.build(bad, out)
        self.assertFalse(out.exists())

    def execute(self, *, full=False, corrupt=False, vector=None, draw=True):
        try: import unicorn as U
        except ImportError:
            sys.path.insert(0, str(HERE.parents[1] / 'k70-arm64-qa')); import unicorn as U
        from unicorn import arm64_const as A
        sys.path.insert(0, str(HERE.parent / 'xnu-handoff')); import handoff
        tree = handoff.make_tree(BASE, 0x10000000, b'P'*64)
        layout = handoff.plan_layout(0x1544000, handoff.KERNEL['vm_base'], 0x3f5488, len(tree))
        args = handoff.make_args(layout, len(tree), handoff.GOP, '-v')
        u = U.Uc(U.UC_ARCH_ARM64, U.UC_MODE_ARM)
        u.mem_map(BASE, 0x1700000); u.mem_map(FB, 0x1194000)
        u.mem_write(BASE, bytes(self.changed)); u.mem_write(TRAMP, self.transition)
        u.mem_write(ARGS, args); u.mem_write(TREE, tree)
        state = dict(sctlr=0x1005 if full else 0, vbar=VECTOR, sel=0,
                     sp={0:0,1:0}, cache=0, original=False, reached=False, pool_writes=0, writes=0)
        special = {(3,0,4,2,2):4, (3,3,0,0,1):0x40004,
                   (3,3,13,0,3):0, (3,3,13,0,2):0,
                   (3,0,5,2,0):0x96000021, (3,0,4,0,1):FIRST, (3,0,6,0,0):0x881549154}
        def mrs(uc, reg, cp, _):
            key = (cp.op0,cp.op1,cp.crn,cp.crm,cp.op2)
            if key == (3,0,1,0,0): v = state['sctlr']
            elif key == (3,0,12,0,0): v = state['vbar']
            else:
                if key not in special: raise AssertionError(('MRS',key))
                v = special[key]
            uc.reg_write(reg,v); return True
        def msr(uc, reg, cp, _):
            key = (cp.op0,cp.op1,cp.crn,cp.crm,cp.op2); value=uc.reg_read(reg)
            if key == (3,0,1,0,0): state['sctlr']=value
            elif key == (3,0,12,0,0): state['vbar']=value
            elif key in [(2,0,1,0,4),(3,3,13,0,3),(3,3,13,0,2)]: special[key]=value
            else: raise AssertionError(('MSR',key))
            return True
        u.hook_add(U.UC_HOOK_INSN,mrs,aux1=A.UC_ARM64_INS_MRS)
        u.hook_add(U.UC_HOOK_INSN,msr,aux1=A.UC_ARM64_INS_MSR)
        u.hook_add(U.UC_HOOK_INSN,lambda *a:True,aux1=A.UC_ARM64_INS_SYS)
        def skip(uc,address,size,_): uc.reg_write(A.UC_ARM64_REG_PC,address+4)
        def select(sel):
            def hook(uc,address,size,_):
                state['sp'][state['sel']]=uc.reg_read(A.UC_ARM64_REG_SP)
                state['sel']=sel;uc.reg_write(A.UC_ARM64_REG_SP,state['sp'][sel])
                uc.reg_write(A.UC_ARM64_REG_PC,address+4)
            return hook
        for address, hook in [(FIRST+4,skip),(FIRST+0x48,select(1)),(FIRST+0x60,select(0))]:
            u.hook_add(U.UC_HOOK_CODE,hook,begin=address,end=address)
        def memory(uc,access,address,size,value,_):
            if not state['sctlr']&1: self.assertEqual(address%size,0,hex(address))
            if access==U.UC_MEM_WRITE:
                if POOL<=address and address+size<=POOL+65536: state['pool_writes']+=1
                elif RECORD<=address and address+size<=RECORD+4096: pass
                else:
                    self.assertGreaterEqual(address,FB);self.assertLessEqual(address+size,FB+1328*ROW)
                state['writes']+=1
        u.hook_add(U.UC_HOOK_MEM_READ|U.UC_HOOK_MEM_WRITE,memory)
        def original(uc,address,size,_): state['original']=True
        u.hook_add(U.UC_HOOK_CODE,original,begin=FIRST,end=FIRST)
        def boundary(uc,address,size,_):
            state['reached']=True
            if corrupt: uc.mem_write(POOL+34*8,bytes(8))
        u.hook_add(U.UC_HOOK_CODE,boundary,begin=COMMON,end=COMMON)
        halt = COMMON + self.report['checkpoint_symbols']['kernel_checkpoint_halt']
        paint = COMMON + self.report['checkpoint_symbols']['checkpoint_paint']
        stop_at = halt if draw else paint
        u.hook_add(U.UC_HOOK_CODE,lambda uc,*a:uc.emu_stop(),begin=stop_at,end=stop_at)
        if full:
            symbols=self.report['transition_symbols']
            at=TRAMP+symbols['transition_mask_interrupts']
            u.hook_add(U.UC_HOOK_CODE,skip,begin=at,end=at)
            at=TRAMP+symbols['transition_clean_loop']
            def cache(uc,address,size,_):
                state['cache']+=1
                if state['cache']==2:uc.reg_write(A.UC_ARM64_REG_X6,BASE+0x10000000-64)
            u.hook_add(U.UC_HOOK_CODE,cache,begin=at,end=at)
        for i,v in enumerate([ARGS,ENTRY,BASE,0x10000000,FB,0x1194000]):
            u.reg_write(A.UC_ARM64_REG_X0+i,v)
        start=TRAMP if full else ENTRY
        if vector is not None:
            start=VECTOR+128*vector
            u.reg_write(A.UC_ARM64_REG_SP,0xfffffff007c04000)
        u.emu_start(start,0,count=20000000)
        self.assertEqual(u.reg_read(A.UC_ARM64_REG_PC),stop_at)
        record=struct.unpack('<18Q',u.mem_read(RECORD,144))
        colors=[struct.unpack('<I',u.mem_read(FB+r*ROW,4))[0] for r in [0,64,128,256,384,448]]
        return record,colors,state,bytes(u.mem_read(POOL,65536)),u

    def test_real_original_prefix_builds_expected_pool_and_five_bands(self):
        r,colors,s,pool,u=self.execute(full=True)
        self.assertTrue(s['original']);self.assertTrue(s['reached'])
        self.assertEqual(s['pool_writes'],8192+258);self.assertEqual(pool,self.b.expected_tables())
        self.assertEqual(r[1:3],(0,0))
        self.assertEqual(colors,[0xffa000ff,0xffffa000,0xff0070ff,0xffffffff,0xff00ff00,0])
        self.assertEqual(r[11:],(ARGS,0,0xfffffff007004000,BASE,0x10000000,POOL,0))
        self.assertEqual(r[9:11],(0xfffffff007bfc000,0xfffffff0079e5e34))
        self.assertEqual(r[4]&0x1005,0);self.assertEqual(r[5],VECTOR);self.assertEqual(s['cache'],2)
        if os.environ.get('K70_QA_OUT'):
            import zlib
            folder=Path(os.environ['K70_QA_OUT']);folder.mkdir(parents=True,exist_ok=True)
            data=bytes(u.mem_read(FB,ROW*1360));raw=b''.join(b'\0'+b''.join(data[p+2:p+3]+data[p+1:p+2]+data[p:p+1] for p in range(y*ROW,(y+1)*ROW,4)) for y in range(1360))
            def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
            (folder/'host-diagnostic-render.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1440,1360,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
        self.assertNotEqual(bytes(u.mem_read(FB+512*ROW,ROW*42)),bytes(ROW*42))

    def test_corrupted_constructed_table_is_rejected_before_paint(self):
        r,_,s,_,_=self.execute(corrupt=True,draw=False)
        self.assertEqual(r[1:3],(2,2));self.assertTrue(s['original'])

    def test_early_vector_records_exception_without_stack(self):
        for vector in range(16):
            r,_,s,_,_=self.execute(vector=vector,draw=False)
            self.assertEqual(r[1:3],(1,vector))
            self.assertEqual(r[6:9],(0x96000021,FIRST,0x881549154))
            self.assertFalse(s['original'])

    def test_exception_path_draws_red_and_diagnostic_rows(self):
        r,colors,_,_,u=self.execute(vector=4)
        self.assertEqual(r[1],1);self.assertEqual(colors[2:5],[0xffff0000]*3)
        self.assertNotEqual(bytes(u.mem_read(FB+512*ROW,ROW*42)),bytes(ROW*42))


if __name__=='__main__':unittest.main()

