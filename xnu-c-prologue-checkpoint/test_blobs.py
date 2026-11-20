import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
BASE=0x880004000
DIAG=0x881608000


class CPrologueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b=None
        if not (HERE/'blobs.py').exists():return
        spec=importlib.util.spec_from_file_location('mmu_blobs',HERE/'blobs.py')
        cls.b=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.b)
        cls.kernel=Path(os.environ.get('K70_KERNEL',HERE.parents[1]/'k70-xnu-kernel/kernel.development.vermeer-build.macho'))
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.out=Path(cls.temp.name)/'blobs'
        cls.header,cls.report=cls.b.build(cls.kernel,cls.out)
        sys.path.insert(0,str(HERE.parent/'xnu-preflight'))
        from payload import materialize
        _,cls.original=materialize(cls.kernel.read_bytes())

    def setUp(self):self.assertIsNotNone(self.b,'original C-prologue checkpoint builder missing')

    def test_only_three_common_words_and_vectors_change(self):
        r=self.report
        expected=bytearray(self.original)
        patches=(self.out/'code-patches.bin').read_bytes()
        vectors=(self.out/'vector-patches.bin').read_bytes()
        self.assertEqual(r['code_patch_offsets'],[0x3f7290,0x3f733c,0x9e1e70])
        self.assertEqual(patches[4:8],struct.pack('<I',0xd503201f))
        for i,off in enumerate(r['code_patch_offsets']):expected[off:off+4]=patches[i*4:i*4+4]
        for i in range(16):expected[0x3f6000+i*128:0x3f6004+i*128]=vectors[i*4:i*4+4]
        self.assertEqual(r['instrumented_mapped_sha256'],hashlib.sha256(expected).hexdigest())
        self.assertEqual(r['original_prefix_sha256'],hashlib.sha256(expected[0x3f705c:0x3f7290]).hexdigest())
        self.assertEqual(r['original_helper_sha256'],hashlib.sha256(expected[0x3fb2fc:0x3fb30c]).hexdigest())
        self.assertEqual(expected[0x3f5488:0x3f548c],struct.pack('<I',0x140006f5))
        self.assertEqual(expected[0x3f7358:0x3f738c],self.original[0x3f7358:0x3f738c])
        self.assertEqual(r['original_arm_init_sha256'],hashlib.sha256(self.original[0x9e1e34:0x9e1e70]).hexdigest())
        self.assertEqual(expected[0x9e1e34:0x9e1e70],self.original[0x9e1e34:0x9e1e70])
        self.assertEqual(r['original_arm_init_prologue_bytes'],60)
        self.assertEqual(r['guard_global_value'],0)
        self.assertEqual(r['code_pages'],[0x8803f9000,0x8803fb000,0x881604000,0x8803fa000,0x8803ff000,DIAG,0x8809e5000])
        self.assertTrue(r['bootstrap_map_contained']);self.assertTrue(r['bootstrap_map_will_be_enabled'])
        self.assertFalse(r['hardware_tested']);self.assertFalse(r['original_cpu_init_completed'])

    def test_diagnostic_is_separate_and_every_branch_lands(self):
        r=self.report;s=r['checkpoint_symbols']
        blob=(self.out/'checkpoint.bin').read_bytes()
        self.assertLessEqual(len(blob),4096)
        self.assertEqual(s['kernel_checkpoint_begin'],0)
        def target(source,word):
            w=struct.unpack('<I',word)[0];self.assertEqual(w&0xfc000000,0x14000000)
            d=w&0x3ffffff
            return source+4*(d-(1<<26) if d&(1<<25) else d)
        patches=(self.out/'code-patches.bin').read_bytes()
        self.assertEqual(target(BASE+0x3f7290,patches[:4]),DIAG+s['pre_switch_gate'])
        self.assertEqual(target(0xfffffff0079e5e70,patches[8:]),0xfffffff008608000)
        vectors=(self.out/'vector-patches.bin').read_bytes()
        for i in range(16):self.assertEqual(target(BASE+0x3f6000+i*128,vectors[i*4:i*4+4]),DIAG+s['exception_vector_%d'%i])

    def test_wrong_input_fails_before_output(self):
        path=Path(self.temp.name)/'bad';path.write_bytes(b'bad')
        out=Path(self.temp.name)/'bad-output'
        with self.assertRaises(ValueError):self.b.build(path,out)
        self.assertFalse(out.exists())

    def execute(self,*,corrupt=False,bad_readback=False,record_fault=False,record_redirect=False,stack_fault=False,vector=None,exception_after_stack=False,draw=False,wrong_arg=False,bad_cpacr=False,bad_tpidr=False,frame_corrupt=False,wrong_sp=False,wrong_fp=False,wrong_x19=False,guard_corrupt=False,exception_after_c_write=None,cleanup_fault=False,cleanup_redirect=False,huge_ctr=False,cache_field=4):
        import ctypes
        import mmap
        try:import unicorn as U
        except ImportError:
            sys.path.insert(0,str(HERE.parents[1]/'k70-arm64-qa'));import unicorn as U
        from unicorn import arm64_const as A
        sys.path.insert(0,str(HERE.parent/'xnu-mmu-checkpoint'));import model
        sys.path.insert(0,str(HERE.parent/'xnu-handoff'));import handoff
        fb,row=0xb8000000,5760
        guard=0x880000000;size=0x1700000;alias=0xfffffff007000000
        backing=mmap.mmap(-1,size);ptr=ctypes.addressof(ctypes.c_char.from_buffer(backing))
        self.addCleanup(backing.close)
        u=U.Uc(U.UC_ARCH_ARM64,U.UC_MODE_ARM)
        u.mem_map_ptr(guard,size,U.UC_PROT_ALL,ptr);u.mem_map_ptr(alias,size,U.UC_PROT_ALL,ptr)
        u.mem_map(fb,0x1194000)
        changed=bytearray(self.original)
        patches=(self.out/'code-patches.bin').read_bytes();vectors=(self.out/'vector-patches.bin').read_bytes()
        for i,o in enumerate(self.report['code_patch_offsets']):changed[o:o+4]=patches[i*4:i*4+4]
        for i in range(16):changed[0x3f6000+i*128:0x3f6004+i*128]=vectors[i*4:i*4+4]
        u.mem_write(BASE,bytes(changed));u.mem_write(DIAG,(self.out/'checkpoint.bin').read_bytes())
        u.mem_write(0x881604000,(self.out/'transition.bin').read_bytes())
        tree=handoff.make_tree(BASE,0x10000000,b'P'*64)
        layout=handoff.plan_layout(0x1544000,0xfffffff007004000,0x3f5488,len(tree))
        u.mem_write(0x881548000,handoff.make_args(layout,len(tree),handoff.GOP,'-v'));u.mem_write(0x881549000,tree)
        frame_start=0x880bfbf30
        frame_pattern=bytes((i*37+11)%256 for i in range(208))
        u.mem_write(frame_start,frame_pattern)
        sentinel=b'original-stack!!';self.assertEqual(len(sentinel),16)
        u.mem_write(0x880bfbff0,sentinel)
        cache_bytes=4<<cache_field
        s=dict(sctlr=0x30d0180d,vbar=0x8803fa000,tcr=0,ttbr0=0,ttbr1=0,mair=0,frame_cleans=0,
            cpacr=0xdead,tpidr_el1=0xbeef,cpacr_writes=0,tpidr_writes=0,virtual_entry=False,physical_exit=False,
            c_pcs=[],c_writes=[],frame_after=None,frame_halt=False,
            phase='uefi',cache=0,enabled=0,dirty=set(),ats=[],sp={0:0,1:0},sel=0,first=False,helper=False,stack_touched=False,inject_pending=False,injected=False)
        specials={(3,0,4,2,2):4,(3,3,0,0,1):(cache_field<<16)|4,(3,3,13,0,3):0,(3,3,13,0,2):0,
            (3,0,5,2,0):0x96000021,(3,0,4,0,1):0x8803fb354,(3,0,6,0,0):0x881549154,(3,0,7,4,0):0}
        keys={(3,0,1,0,0):'sctlr',(3,0,12,0,0):'vbar',(3,0,2,0,2):'tcr',
              (3,0,2,0,0):'ttbr0',(3,0,2,0,1):'ttbr1',(3,0,10,2,0):'mair',
              (3,0,1,0,2):'cpacr',(3,0,13,0,4):'tpidr_el1'}
        key=lambda cp:(cp.op0,cp.op1,cp.crn,cp.crm,cp.op2)
        def walk(at,**kw):return model.walk(at,s,lambda p:struct.unpack('<Q',u.mem_read(p,8))[0],**kw)
        def mrs(uc,reg,cp,_):
            k=key(cp)
            if k in keys:v=s[keys[k]]
            else:self.assertIn(k,specials,('MRS',k));v=specials[k]
            if huge_ctr and s['phase']=='xnu' and k==(3,3,0,0,1):v=0xf0000
            if bad_readback and s['phase']=='xnu' and k==(3,0,10,2,0):v^=1
            if bad_cpacr and s['phase']=='xnu' and k==(3,0,1,0,2):v^=1
            if bad_tpidr and s['phase']=='xnu' and k==(3,0,13,0,4):v^=1
            uc.reg_write(reg,v);return True
        def msr(uc,reg,cp,_):
            k=key(cp);v=uc.reg_read(reg)
            if k in keys:
                if keys[k]=='sctlr':
                    if s['phase']=='xnu' and not v&1:self.assertFalse(s['dirty'],('dirty before M0',s['dirty']))
                    if v&1 and s['phase']=='off':s['phase']='xnu';s['enabled']+=1
                    elif not v&1:s['phase']='off'
                s[keys[k]]=v
                if keys[k]=='cpacr':s['cpacr_writes']+=1
                if keys[k]=='tpidr_el1':s['tpidr_writes']+=1
            else:self.assertIn(k,[(2,0,1,0,4),(3,3,13,0,3),(3,3,13,0,2)]);specials[k]=v
            return True
        u.hook_add(U.UC_HOOK_INSN,mrs,aux1=A.UC_ARM64_INS_MRS)
        u.hook_add(U.UC_HOOK_INSN,msr,aux1=A.UC_ARM64_INS_MSR)
        # Decode SYS at the instruction boundary: Unicorn's SYS hook models all
        # cache/TLBI/AT operations, so the same decoder works across versions.
        def code(uc,pc,n,_):
            if s['phase']=='xnu':
                expected=pc-alias+guard if pc>=alias else pc
                self.assertEqual(walk(pc,execute=True),expected,('fetch',hex(pc)))
            else:self.assertLess(pc,1<<40,'KVA fetch with MMU off')
            if pc==0xfffffff0079e5e34:
                s['virtual_entry']=True
                if wrong_arg:uc.reg_write(A.UC_ARM64_REG_X0,0x881548000)
            if 0xfffffff0079e5e34<=pc<0xfffffff0079e5e70:
                s['c_pcs'].append(pc)
                if guard_corrupt and pc==0xfffffff0079e5e34:uc.mem_write(0x880b3c268,struct.pack('<Q',0xdeadbeef))
            if pc==0xfffffff0079e5e70:
                self.assertEqual(struct.unpack('<I',uc.mem_read(pc,4))[0]&0xfc000000,0x14000000,'original first BL executed')
                s['frame_after']=bytes(uc.mem_read(frame_start,208))
            self.assertNotEqual(pc,0xfffffff0073f2494,'arm_set_kernel_tbi must not run')
            if pc==0xfffffff008608000:
                if frame_corrupt:uc.mem_write(frame_start+0x70,struct.pack('<Q',0x12345678))
                if wrong_sp:uc.reg_write(A.UC_ARM64_REG_SP,0xfffffff007bfbf20)
                if wrong_fp:uc.reg_write(A.UC_ARM64_REG_X29,0xfffffff007bfbfe0)
                if wrong_x19:uc.reg_write(A.UC_ARM64_REG_X19,0x881548000)
            if pc==DIAG+self.report['checkpoint_symbols']['frame_cleanup_unavailable_halt']:s['frame_halt']=True
            if pc in [DIAG+self.report['checkpoint_symbols'][k] for k in ['checkpoint_cleanup_phys','record_unavailable_phys']]:s['physical_exit']=True
            if s['inject_pending']:
                s['inject_pending']=False;s['injected']=True
                uc.reg_write(A.UC_ARM64_REG_PC,0x8803fa000+4*128);return
            ins=struct.unpack('<I',uc.mem_read(pc,4))[0]
            if ins&0xfff80000==0xd5080000:
                op1=(ins>>16)&7;crn=(ins>>12)&15;crm=(ins>>8)&15;op2=(ins>>5)&7;rt=ins&31
                v=0 if rt==31 else uc.reg_read(A.UC_ARM64_REG_X0+rt)
                if (op1,crn,crm,op2) in [(0,7,8,0),(0,7,8,1)]:
                    physical=walk(v,write=op2==1)
                    if record_fault and v==0x881606000:physical=None
                    if record_redirect and v==0x881606000:physical=0x881609000
                    if stack_fault and v==0xfffffff007bfbff0:physical=None
                    in_cleanup=DIAG+self.report['checkpoint_symbols']['clean_c_frame']<=pc<DIAG+self.report['checkpoint_symbols']['clean_c_frame_end']
                    if in_cleanup and v==0xfffffff007bfbf30:
                        if cleanup_fault:physical=None
                        if cleanup_redirect:physical=0x881609000
                    specials[(3,0,7,4,0)]=1 if physical is None else physical&~4095
                    s['ats'].append((v,physical))
                elif (op1,crn,crm,op2)==(3,7,14,1) and s['phase']=='xnu':
                    physical=walk(v,write=True);self.assertIsNotNone(physical,('cache',hex(v)))
                    if 0x880bfb000<=physical<0x880bfc000:
                        self.assertTrue((frame_start&~(cache_bytes-1))<=physical<0x880bfc000,'frame cache clean escaped owned frame lines')
                        s['frame_cleans']+=1
                    s['dirty'].discard(physical&~(cache_bytes-1))
                uc.reg_write(A.UC_ARM64_REG_PC,pc+4)
        u.hook_add(U.UC_HOOK_CODE,code)
        def skip(uc,pc,n,_):uc.reg_write(A.UC_ARM64_REG_PC,pc+4)
        def select(sel):
            def hook(uc,pc,n,_):
                s['sp'][s['sel']]=uc.reg_read(A.UC_ARM64_REG_SP);s['sel']=sel
                uc.reg_write(A.UC_ARM64_REG_SP,s['sp'][sel]);skip(uc,pc,n,_)
            return hook
        first=0x8803fb05c
        for at,hook in [(first+4,skip),(first+0x48,select(1)),(first+0x60,select(0)),
            (0x881604000+self.report['transition_symbols']['transition_mask_interrupts'],skip)]:
            u.hook_add(U.UC_HOOK_CODE,hook,begin=at,end=at)
        def clean(uc,pc,n,_):
            s['cache']+=1
            if s['cache']==1:self.assertEqual(uc.reg_read(A.UC_ARM64_REG_X6),guard)
            if s['cache']==2:uc.reg_write(A.UC_ARM64_REG_X6,BASE+0x10000000-64)
        at=0x881604000+self.report['transition_symbols']['transition_clean_loop'];u.hook_add(U.UC_HOOK_CODE,clean,begin=at,end=at)
        def memory(uc,access,address,n,value,_):
            if s['phase']=='xnu':
                physical=walk(address,write=access==U.UC_MEM_WRITE);self.assertIsNotNone(physical,('unmapped data',hex(address)))
                self.assertLess(physical+n,0x890000001)
                if access==U.UC_MEM_WRITE:
                    pc=uc.reg_read(A.UC_ARM64_REG_PC)
                    if 0xfffffff0079e5e34<=pc<0xfffffff0079e5e70:
                        allowed={0xfffffff0079e5e38+i*4 for i in range(6)}|{0xfffffff0079e5e64,0xfffffff0079e5e68,0xfffffff0079e5e6c}
                        self.assertIn(pc,allowed,'unexpected original C store')
                        self.assertTrue(frame_start<=physical and physical+n<=frame_start+208)
                        s['c_writes'].append((pc,physical,n))
                        if exception_after_c_write==len(s['c_writes']):s['inject_pending']=True
                    else:self.assertTrue(0x881606000<=physical<0x881607000 or 0x880bfbff0<=physical<0x880bfc000,hex(physical))
                    s['dirty'].update(p&~(cache_bytes-1) for p in range(physical,physical+n))
                    if 0x880bfbff0<=physical<0x880bfc000:
                        s['stack_touched']=True
                        if exception_after_stack and not s['injected'] and not 0xfffffff0079e5e34<=pc<0xfffffff0079e5e70:s['inject_pending']=True
            else:
                self.assertEqual(address%n,0,('M0 alignment',hex(address),n))
                if access==U.UC_MEM_WRITE:self.assertTrue(guard<=address<guard+size or fb<=address<fb+1440*row,hex(address))
        u.hook_add(U.UC_HOOK_MEM_READ|U.UC_HOOK_MEM_WRITE,memory)
        def first_seen(*_):s['first']=True
        def helper_seen(*_):s['helper']=True
        u.hook_add(U.UC_HOOK_CODE,first_seen,begin=first,end=first)
        u.hook_add(U.UC_HOOK_CODE,helper_seen,begin=0x8803ff2fc,end=0x8803ff2fc)
        def gate(uc,pc,n,_):
            if corrupt:uc.mem_write(0x88017a000+34*8,bytes(8))
        u.hook_add(U.UC_HOOK_CODE,gate,begin=0x8803fb290,end=0x8803fb290)
        if vector is not None:
            def exception(uc,pc,n,_):uc.reg_write(A.UC_ARM64_REG_PC,0x8803fa000+128*vector)
            u.hook_add(U.UC_HOOK_CODE,exception,begin=0x8803fb358,end=0x8803fb358)
        stop=DIAG+self.report['checkpoint_symbols']['kernel_checkpoint_halt' if draw else 'checkpoint_paint']
        u.hook_add(U.UC_HOOK_CODE,lambda uc,*_:uc.emu_stop(),begin=stop,end=stop)
        failstop=DIAG+self.report['checkpoint_symbols']['frame_cleanup_unavailable_halt']
        u.hook_add(U.UC_HOOK_CODE,lambda uc,*_:uc.emu_stop(),begin=failstop,end=failstop)
        for i,v in enumerate([0x881548000,0x8803f9488,BASE,0x10000000,fb,0x1194000]):u.reg_write(A.UC_ARM64_REG_X0+i,v)
        for reg,value in [(A.UC_ARM64_REG_X19,0x1919191919191919),(A.UC_ARM64_REG_X29,0x2929292929292929),(A.UC_ARM64_REG_X27,0x2727272727272727),(A.UC_ARM64_REG_X28,0x2828282828282828)]:u.reg_write(reg,value)
        u.emu_start(0x881604000,0,count=20000000)
        self.assertIn(u.reg_read(A.UC_ARM64_REG_PC),[stop,failstop])
        record=struct.unpack('<35Q',u.mem_read(0x881606000,280))
        if s['frame_halt']:
            self.assertEqual(s['sctlr']&0x1005,0x1005)
        else:self.assertFalse(s['sctlr']&0x1005);self.assertFalse(s['dirty'])
        if s['frame_after'] is not None and not exception_after_stack and not frame_corrupt:self.assertEqual(bytes(u.mem_read(frame_start,208)),s['frame_after'])
        gaps=list(range(0x34))+list(range(0x48,0x68))
        final_frame=bytes(u.mem_read(frame_start,208))
        for i in gaps:self.assertEqual(final_frame[i],frame_pattern[i],('untouched frame byte',i))
        colors=[struct.unpack('<I',u.mem_read(fb+r*row,4))[0] for r in [0,64,128,256,384,448,512,576]]
        if draw and os.environ.get('K70_QA_OUT'):
            import zlib
            folder=Path(os.environ['K70_QA_OUT']);folder.mkdir(parents=True,exist_ok=True)
            data=bytes(u.mem_read(fb,row*1440));raw=b''.join(b'\0'+b''.join(data[p+2:p+3]+data[p+1:p+2]+data[p:p+1] for p in range(y*row,(y+1)*row,4)) for y in range(1440))
            def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
            (folder/'host-c-prologue-render.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1440,1440,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
        return record,s,colors

    def test_original_mmu_sequence_coherent_aliases_stack_and_cleanup(self):
        r,s,_=self.execute()
        self.assertTrue(s['first']);self.assertTrue(s['helper']);self.assertEqual(s['enabled'],1)
        self.assertEqual(r[1:3],(0,0));self.assertEqual(r[4]&0x1005,0x1005)
        self.assertEqual(r[18:22],(0x22a51a251a,0x88017a000,0x88017b000,0x0c0804ff00bb44ff))
        self.assertEqual(r[22:28],(0x8803f9000,0x8803f9000,0x881548000,0x880bfb000,0x880000000,0x88ffff000))
        self.assertEqual(r[28]&1,1);self.assertEqual(r[29:31],(0x20002,1))
        self.assertTrue(s['virtual_entry']);self.assertTrue(s['physical_exit'])
        self.assertEqual(s['cpacr_writes'],1);self.assertEqual(s['tpidr_writes'],1)
        self.assertEqual(r[31:33],(0xfffffff008608000,0xfffffff008548000))
        self.assertEqual(r[9],0xfffffff007bfbf30)
        self.assertEqual(r[33:],(0xfffffff007bfbff0,1))
        self.assertEqual(s['c_pcs'],list(range(0xfffffff0079e5e34,0xfffffff0079e5e70,4)))
        actual={p+i for _,p,n in s['c_writes'] for i in range(n)}
        expected={0x880bfbf30+i for i in list(range(0x34,0x48))+list(range(0x68,0xd0))}
        self.assertEqual(actual,expected);self.assertEqual(len(actual),124)

    def test_corrupt_pool_rejects_before_mmu_enable(self):
        r,s,_=self.execute(corrupt=True);self.assertEqual(r[1:3],(2,2));self.assertEqual(s['enabled'],0)

    def test_mmu_readback_rejects_and_cleans_record_before_render(self):
        r,s,_=self.execute(bad_readback=True);self.assertEqual(r[1:3],(2,3));self.assertEqual(s['enabled'],1)

    def test_record_translation_fault_disables_mmu_before_first_store(self):
        r,s,_=self.execute(record_fault=True);self.assertEqual(r[1:3],(2,4));self.assertEqual(s['enabled'],1)

    def test_record_translation_redirect_disables_mmu_before_first_store(self):
        r,s,_=self.execute(record_redirect=True);self.assertEqual(r[1:3],(2,4));self.assertEqual(s['enabled'],1)

    def test_failed_stack_translation_still_cleans_original_frame(self):
        r,s,_=self.execute(stack_fault=True);self.assertEqual(r[1:3],(2,3));self.assertTrue(s['c_writes'])

    def test_exception_after_stack_write_preserves_pending_cleanup_marker(self):
        r,s,_=self.execute(exception_after_stack=True)
        self.assertEqual(r[1:3],(1,4));self.assertTrue(s['injected']);self.assertEqual(r[30],2)

    def test_all_sixteen_mmu_on_exception_vectors_clean_record(self):
        for vector in range(16):
            r,s,_=self.execute(vector=vector)
            self.assertEqual(r[1:3],(1,vector));self.assertEqual(r[6:9],(0x96000021,0x8803fb354,0x881549154))

    def test_eight_bands_and_two_column_renderer(self):
        r,s,c=self.execute(draw=True)
        self.assertEqual(r[1:3],(0,0));self.assertEqual(c,[0xffa000ff,0xffffa000,0xff0070ff,0xffffffff,0xff00ff00,0xff00ffff,0xffff00ff,0xffffff00])

    def test_wrong_virtual_argument_rejects_then_exits_physically(self):
        r,s,_=self.execute(wrong_arg=True);self.assertEqual(r[1:3],(2,1));self.assertTrue(s['physical_exit'])

    def test_cpacr_readback_rejects_then_exits_physically(self):
        r,s,_=self.execute(bad_cpacr=True);self.assertEqual(r[1:3],(2,1));self.assertTrue(s['physical_exit'])

    def test_tpidr_readback_rejects_then_exits_physically(self):
        r,s,_=self.execute(bad_tpidr=True);self.assertEqual(r[1:3],(2,1));self.assertTrue(s['physical_exit'])



    def test_original_saved_registers_and_guard_must_match(self):
        for option in ['frame_corrupt','wrong_sp','wrong_fp','wrong_x19','guard_corrupt']:
            r,s,_=self.execute(**{option:True})
            self.assertEqual(r[1:3],(2,6),option)
            self.assertTrue(s['c_writes'])

    def test_each_partial_original_store_exception_cleans_frame(self):
        # STP emits two Unicorn write callbacks within one instruction. Inject
        # at each actual instruction boundary, after all of that STP's writes.
        for index in [2,4,6,8,10,12,13,15,16]:
            r,s,_=self.execute(exception_after_c_write=index)
            self.assertEqual(r[1:3],(1,4),index)
            self.assertTrue(s['injected']);self.assertEqual(len(s['c_writes']),index)

    def test_bad_cleanup_translation_or_geometry_halts_mmu_on(self):
        for option in ['cleanup_fault','cleanup_redirect','huge_ctr']:
            r,s,c=self.execute(**{option:True})
            self.assertTrue(s['frame_halt'],option)
            self.assertTrue(s['dirty'],option)
            self.assertEqual(s['frame_cleans'],0,option)
            self.assertNotEqual(c[-1],0xffffff00,'failure must not paint yellow PASS')

    def test_supported_cache_line_geometry_cleans_every_dirty_line(self):
        # The unchanged transition accepts only 16..4096-byte cache lines.
        for field in [2,4,5,10]:
            r,s,_=self.execute(cache_field=field)
            self.assertEqual(r[1:3],(0,0));self.assertFalse(s['dirty'])
            self.assertGreater(s['frame_cleans'],0)

    def test_record_emergency_still_cleans_original_c_frame(self):
        for option in ['record_fault','record_redirect']:
            r,s,_=self.execute(**{option:True})
            self.assertEqual(r[1:3],(2,4));self.assertTrue(s['c_writes'])
            self.assertFalse(s['dirty']);self.assertTrue(s['physical_exit'])

if __name__=='__main__':unittest.main()
