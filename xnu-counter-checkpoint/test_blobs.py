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


class CounterProgressionTests(unittest.TestCase):
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

    def setUp(self):self.assertIsNotNone(self.b,'counter checkpoint builder missing')

    def test_only_three_common_words_and_vectors_change(self):
        r=self.report
        expected=bytearray(self.original)
        patches=(self.out/'code-patches.bin').read_bytes()
        vectors=(self.out/'vector-patches.bin').read_bytes()
        self.assertEqual(r['code_patch_offsets'],[0x3f7290,0x3f733c,0x9e1e80])
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
        self.assertEqual(r['code_pages'],[0x8803f9000,0x8803fb000,0x881604000,0x8803fa000,0x8803ff000,DIAG,0x8809e5000,0x8803f2000])
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
        self.assertEqual(target(0xfffffff0079e5e80,patches[8:]),0xfffffff008608000)
        vectors=(self.out/'vector-patches.bin').read_bytes()
        for i in range(16):self.assertEqual(target(BASE+0x3f6000+i*128,vectors[i*4:i*4+4]),DIAG+s['exception_vector_%d'%i])

    def test_wrong_input_fails_before_output(self):
        path=Path(self.temp.name)/'bad';path.write_bytes(b'bad')
        out=Path(self.temp.name)/'bad-output'
        with self.assertRaises(ValueError):self.b.build(path,out)
        self.assertFalse(out.exists())

    def execute(self,*,corrupt=False,bad_readback=False,record_fault=False,record_redirect=False,stack_fault=False,vector=None,exception_after_stack=False,draw=False,wrong_arg=False,bad_cpacr=False,bad_tpidr=False,frame_corrupt=False,wrong_sp=False,wrong_fp=False,wrong_x19=False,guard_corrupt=False,exception_after_c_write=None,cleanup_fault=False,cleanup_redirect=False,huge_ctr=False,cache_field=4,wrong_lr=False,wrong_header_base=False,wrong_header_flags=False,corrupt_header=False,exception_at=None,fault=None,far_value=0xa55a12340000beef,physical=(0x1000000000,0x1000001000,0x1000003000),virtual=(0x500000000,0x500001000,0x500003000),frequencies=(19200000,19200000)):
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
            counter_reads=[],loop_counts=[0,0],record_checks=0,record_unavailable=False,record_cleans=0,c_pcs=[],callee_pcs=[],tcr_writes=0,c_writes=[],frame_after=None,frame_halt=False,
            phase='uefi',cache=0,enabled=0,dirty=set(),ats=[],sp={0:0,1:0},sel=0,first=False,helper=False,stack_touched=False,inject_pending=False,injected=False)
        specials={(3,0,4,2,2):4,(3,3,0,0,1):(cache_field<<16)|4,(3,3,13,0,3):0,(3,3,13,0,2):0,
            (3,0,4,0,0):0,(3,0,5,2,0):0x96000021,(3,0,4,0,1):0x8803fb354,(3,0,6,0,0):0x881549154,(3,0,7,4,0):0}
        keys={(3,0,1,0,0):'sctlr',(3,0,12,0,0):'vbar',(3,0,2,0,2):'tcr',
              (3,0,2,0,0):'ttbr0',(3,0,2,0,1):'ttbr1',(3,0,10,2,0):'mair',
              (3,0,1,0,2):'cpacr',(3,0,13,0,4):'tpidr_el1'}
        key=lambda cp:(cp.op0,cp.op1,cp.crn,cp.crm,cp.op2)
        def walk(at,**kw):return model.walk(at,s,lambda p:struct.unpack('<Q',u.mem_read(p,8))[0],**kw)
        def mrs(uc,reg,cp,_):
            k=key(cp)
            if k in [(3,3,14,0,0),(3,3,14,0,1),(3,3,14,0,2)]:
                name={0:'freq',1:'phys',2:'virt'}[k[-1]]
                seq={'freq':frequencies,'phys':physical,'virt':virtual}[name]
                index=sum(x[0]==name for x in s['counter_reads']);self.assertLess(index,len(seq))
                pc=uc.reg_read(A.UC_ARM64_REG_PC)
                if name!='freq':self.assertEqual(struct.unpack('<I',uc.mem_read(pc-4,4))[0],0xd5033fdf,'ISB directly before count read')
                v=seq[index];s['counter_reads'].append((name,index,v,pc));uc.reg_write(reg,v);return True
            if k==(3,3,4,2,0):v=uc.reg_read(A.UC_ARM64_REG_NZCV)
            elif k==(3,3,4,2,1):v=0x3c0
            elif k==(3,0,4,2,0):v=s['sel']
            elif k in keys:v=s[keys[k]]
            else:self.assertIn(k,specials,('MRS',k));v=specials[k]
            if huge_ctr and s['phase']=='xnu' and k==(3,3,0,0,1):v=0xf0000
            if bad_readback and s['phase']=='xnu' and k==(3,0,10,2,0):v^=1
            if bad_cpacr and s['phase']=='xnu' and k==(3,0,1,0,2):v^=1
            if bad_tpidr and s['phase']=='xnu' and k==(3,0,13,0,4):v^=1
            uc.reg_write(reg,v);return True
        def msr(uc,reg,cp,_):
            k=key(cp);v=uc.reg_read(reg)
            self.assertFalse(k[0:3]==(3,3,14),'No timer/counter control programming')
            if k in keys:
                if keys[k]=='sctlr':
                    if s['phase']=='xnu' and not v&1:self.assertFalse(s['dirty'],('dirty before M0',s['dirty']))
                    if v&1 and s['phase']=='off':s['phase']='xnu';s['enabled']+=1
                    elif not v&1:s['phase']='off'
                s[keys[k]]=v
                if keys[k]=='tcr':s['tcr_writes']+=1
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
            if 0xfffffff0079e5e34<=pc<0xfffffff0079e5e80:
                s['c_pcs'].append(pc)
                if guard_corrupt and pc==0xfffffff0079e5e34:uc.mem_write(0x880b3c268,struct.pack('<Q',0xdeadbeef))
            if pc==0xfffffff0079e5e70:
                self.assertEqual(struct.unpack('<I',uc.mem_read(pc,4))[0],0x97e83189,'original BL must be preserved')
            if pc==0xfffffff0073f2494:
                s['callee_pcs'].append(pc)
                self.assertEqual(struct.unpack('<I',uc.mem_read(pc,4))[0],0xd65f03c0)
            if pc==0xfffffff0079e5e7c and corrupt_header:uc.mem_write(BASE+24,struct.pack('<I',0x80200001))
            if pc==0xfffffff0079e5e80:
                self.assertEqual(struct.unpack('<I',uc.mem_read(pc,4))[0]&0xfc000000,0x14000000,'relocation conditional must not execute')
                s['frame_after']=bytes(uc.mem_read(frame_start,208))
            self.assertNotEqual(pc,0xfffffff0079e5f2c,'relocation alternate path must not run')
            if exception_at==pc and not s['injected']:s['inject_pending']=True
            if pc==0xfffffff008608000:
                if wrong_lr:uc.reg_write(A.UC_ARM64_REG_X30,0xfffffff0079e5e78)
                if wrong_header_base:uc.reg_write(A.UC_ARM64_REG_X8,BASE)
                if wrong_header_flags:uc.reg_write(A.UC_ARM64_REG_X9,0x80200001)
                if frame_corrupt:uc.mem_write(frame_start+0x70,struct.pack('<Q',0x12345678))
                if wrong_sp:uc.reg_write(A.UC_ARM64_REG_SP,0xfffffff007bfbf20)
                if wrong_fp:uc.reg_write(A.UC_ARM64_REG_X29,0xfffffff007bfbfe0)
                if wrong_x19:uc.reg_write(A.UC_ARM64_REG_X19,0x881548000)
            if pc==DIAG+self.report['checkpoint_symbols']['frame_cleanup_unavailable_halt']:s['frame_halt']=True
            if pc in [DIAG+self.report['checkpoint_symbols'][k] for k in ['checkpoint_cleanup_phys','record_unavailable_phys']]:s['physical_exit']=True
            if s['inject_pending']:
                s['inject_pending']=False;s['injected']=True
                uc.reg_write(A.UC_ARM64_REG_PC,0x8803fa000+4*128);return
            sy=self.report['checkpoint_symbols'];kva=0xfffffff008608000
            for i,label in enumerate(['counter_wait_first','counter_wait_second']):
                if pc==kva+sy[label]:s['loop_counts'][i]+=1
            if pc==kva+sy['counter_validated']:
                if fault=='arm':uc.mem_write(0x881606400,bytes(8))
                if fault=='ready':uc.mem_write(0x881606480,bytes(8))
                if fault=='busy':uc.mem_write(0x881606408,struct.pack('<Q',1))
            if fault=='counter_trap' and pc==kva+sy['counter_sample_1_physical'] and not s['injected']:
                s['injected']=True;oldsel=s['sel'];s['sp'][oldsel]=uc.reg_read(A.UC_ARM64_REG_SP)
                specials[(3,0,4,0,0)]=(uc.reg_read(A.UC_ARM64_REG_NZCV)&0xf0000000)|0x3c0|4|oldsel
                specials[(3,0,5,2,0)]=0x62000000;specials[(3,0,4,0,1)]=pc;specials[(3,0,6,0,0)]=far_value
                s['sel']=1;uc.reg_write(A.UC_ARM64_REG_SP,s['sp'][1]);uc.reg_write(A.UC_ARM64_REG_PC,s['vbar']+oldsel*4*128);return
            capture_done=self.report['checkpoint_symbols']['post_capture_complete']
            if fault=='nested' and pc in [DIAG+capture_done,0xfffffff008608000+capture_done] and not s['injected']:
                s['injected']=True;uc.reg_write(A.UC_ARM64_REG_PC,s['vbar']+4*128);return
            ins=struct.unpack('<I',uc.mem_read(pc,4))[0]
            if ins&0xfff80000==0xd5080000:
                op1=(ins>>16)&7;crn=(ins>>12)&15;crm=(ins>>8)&15;op2=(ins>>5)&7;rt=ins&31
                v=0 if rt==31 else uc.reg_read(A.UC_ARM64_REG_X0+rt)
                if (op1,crn,crm,op2) in [(0,7,8,0),(0,7,8,1)]:
                    physical=walk(v,write=op2==1)
                    if v==0x881606000:
                        s['record_checks']+=1
                        phase={1:'pre',2:'handler',3:'cleanup'}.get(s['record_checks'],'other')
                        if fault=='record_'+phase+'_fault':physical=None;s['record_unavailable']=True
                        if fault=='record_'+phase+'_redirect':physical=0x881609000;s['record_unavailable']=True
                        if fault=='record_'+phase+'_high':physical=0x881606000|(1<<40);s['record_unavailable']=True
                    if record_fault and v==0x881606000:physical=None
                    if record_redirect and v==0x881606000:physical=0x881609000
                    if stack_fault and v==0xfffffff007bfbff0:physical=None
                    in_cleanup=DIAG+self.report['checkpoint_symbols']['clean_c_frame']<=pc<DIAG+self.report['checkpoint_symbols']['clean_c_frame_end']
                    if in_cleanup and v==0xfffffff007bfbf30:
                        if fault=='frame_high':physical=0x880bfb000|(1<<40)
                        if cleanup_fault:physical=None
                        if cleanup_redirect:physical=0x881609000
                    specials[(3,0,7,4,0)]=1 if physical is None else physical&~4095
                    s['ats'].append((v,physical))
                elif (op1,crn,crm,op2)==(3,7,14,1) and s['phase']=='xnu':
                    physical=walk(v,write=True);self.assertIsNotNone(physical,('cache',hex(v)))
                    if 0x880bfb000<=physical<0x880bfc000:
                        self.assertTrue((frame_start&~(cache_bytes-1))<=physical<0x880bfc000,'frame cache clean escaped owned frame lines')
                        s['frame_cleans']+=1
                    if 0x881606000<=physical<0x881607000:s['record_cleans']+=1
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
                if 0x881606000<=physical<0x881607000:self.assertFalse(s['record_unavailable'],'data access through unverified record')
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
        record=struct.unpack('<37Q',u.mem_read(0x881606000,296))
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
            (folder/'host-counter-render.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1440,1440,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
        return record,s,colors

    def test_three_ordered_samples_two_bounded_intervals(self):
        raw,s,_=self.execute();v=raw[1:]
        self.assertEqual(v[:3],(0,0,4));self.assertEqual(v[3]&0x1005,0x1005)
        self.assertEqual(v[5:8],(0,0,0));self.assertEqual(v[8:11],(0xfffffff007bfbf30,0xfffffff0079e5e74,0))
        self.assertEqual(v[0xb:0xd],(19200000,19200000))
        self.assertEqual(v[0xd:0x11],(0x1000000000,0x1000001000,0x1000003000,0x3000))
        self.assertEqual(v[0x11:0x15],(0x500000000,0x500001000,0x500003000,0x3000))
        self.assertEqual(v[0x15:0x19],(4096,8192,3,0));self.assertEqual(s['loop_counts'],[4096,8192])
        self.assertEqual([x[0] for x in s['counter_reads']],['freq','phys','virt','phys','virt','phys','virt','freq'])
        self.assertEqual(v[0x19:0x1d],(0x22a51a251a,0x88017a000,0x88017b000,0x0c0804ff00bb44ff))
        self.assertEqual(v[0x1d:],(0x200001,0xfffffff007004000,0xfffffff008548000,0xfffffff007bfbff0,1,0,1))
        self.assertEqual(s['record_checks'],3);self.assertFalse(s['dirty']);self.assertEqual(s['tcr_writes'],1)
        self.assertTrue(self.report['counter_read_only']);self.assertFalse(self.report['timer_irq_executed'])
        self.assertEqual(self.report['sample_count_per_counter'],3);self.assertEqual(self.report['delay_loop_rounds'],[4096,8192])

    def test_independent_offsets_deltas_and_high_unsigned_values(self):
        for p,q in [((0,100,250),(0x123456789,0x123456790,0x1234567a0)),((2**63,2**63+1,2**63+3),(2**64-100,2**64-90,2**64-70))]:
            with self.subTest(p=p,q=q):
                raw,_,_=self.execute(physical=p,virtual=q);v=raw[1:]
                self.assertEqual(v[0],0);self.assertEqual(v[0x23],1)
                self.assertEqual(v[0x10],p[2]-p[0]);self.assertEqual(v[0x14],q[2]-q[0])

    def test_stalled_backward_wrapped_and_implausible_counts_reject(self):
        for seq in [(100,100,101),(100,101,101),(100,99,102),(100,102,101),(2**64-2,1,2),(0,1,19200000),(0,1,2**63)]:
            for channel in ['physical','virtual']:
                with self.subTest(seq=seq,channel=channel):
                    raw,_,_=self.execute(**{channel:seq});self.assertEqual(raw[1],2);self.assertEqual(raw[36],0)

    def test_frequency_metadata_bounds_and_stability(self):
        for freq in [(0,0),(1000000001,1000000001),(19200000,19200001)]:
            with self.subTest(freq=freq):
                raw,_,_=self.execute(frequencies=freq);self.assertEqual(raw[1],2);self.assertEqual(raw[36],0)

    def test_trapped_counter_read_is_exception_not_counter_pass(self):
        raw,s,_=self.execute(fault='counter_trap');v=raw[1:]
        self.assertEqual(v[0:2],(1,0));self.assertEqual(v[5],0x62000000)
        self.assertEqual(v[6],0xfffffff008608000+self.report['checkpoint_symbols']['counter_sample_1_physical'])
        self.assertEqual(v[7],0xa55a12340000beef);self.assertEqual(v[8],0xfffffff007c04000)
        self.assertEqual(v[0xa],1);self.assertEqual(v[0x18]&0x3df,0x3c4);self.assertEqual(v[0x23],0)

    def test_preconditions_reject_with_no_false_counter_or_frame_fields(self):
        for arg in ['wrong_arg','bad_cpacr','bad_tpidr','wrong_sp','wrong_fp','wrong_x19','guard_corrupt','frame_corrupt','wrong_lr','wrong_header_base','wrong_header_flags']:
            with self.subTest(arg=arg):
                raw,s,_=self.execute(**{arg:True});v=raw[1:]
                self.assertEqual(v[0],2);self.assertEqual(v[0xb:0x19],(0,)*14)
                self.assertEqual(v[0x1d:0x1f],(0,)*2);self.assertEqual(v[0x21],0);self.assertEqual(v[0x23],0);self.assertFalse(s['counter_reads'])

    def test_record_at_all_phases_fault_redirect_and_high_pa_fail_closed(self):
        for phase in ['pre','handler','cleanup']:
            for bad in ['fault','redirect','high']:
                with self.subTest(phase=phase,bad=bad):
                    _,s,_=self.execute(fault='record_'+phase+'_'+bad)
                    self.assertTrue(s['frame_halt']);self.assertTrue(s['record_unavailable'])
                    self.assertEqual(s['sctlr']&0x1005,0x1005)

    def test_one_shot_ready_busy_and_nested_fail_closed(self):
        for fault in ['arm','ready','busy','nested']:
            with self.subTest(fault=fault):
                raw,s,_=self.execute(fault=fault)
                if fault in ['busy','nested']:self.assertTrue(s['frame_halt'])
                else:self.assertNotEqual(raw[1],0);self.assertEqual(raw[36],0)

    def test_bad_cleanup_frame_and_ctr_never_disable_mci_or_clean_unsafe(self):
        for kw in [dict(cleanup_fault=True),dict(cleanup_redirect=True),dict(fault='frame_high'),dict(huge_ctr=True)]:
            with self.subTest(kw=kw):
                _,s,_=self.execute(**kw);self.assertTrue(s['frame_halt'])
                self.assertEqual(s['sctlr']&0x1005,0x1005);self.assertEqual(s['frame_cleans'],0)

    def test_all_synthetic_vectors_reject_not_progression_evidence(self):
        for i in range(16):
            with self.subTest(vector=i):
                raw,s,_=self.execute(vector=i);self.assertEqual(raw[1:3],(1,i));self.assertEqual(raw[36],0);self.assertFalse(s['counter_reads'])

    def test_corrupt_pool_stops_before_counter_reads(self):
        raw,s,_=self.execute(corrupt=True);self.assertEqual(raw[1],2);self.assertFalse(s['counter_reads']);self.assertEqual(s['enabled'],0)

    def test_supported_cache_geometries_clean_all_owned_writes(self):
        for field in [2,4,5,10]:
            with self.subTest(field=field):
                raw,s,_=self.execute(cache_field=field);self.assertEqual(raw[1],0);self.assertFalse(s['dirty']);self.assertGreater(s['frame_cleans'],0);self.assertGreater(s['record_cleans'],0)

    def test_original_writes_bounded_and_renderer(self):
        raw,s,colors=self.execute(draw=True)
        self.assertEqual(raw[1],0);self.assertEqual(len(s['c_writes']),16)
        self.assertEqual(sum(x[2] for x in s['c_writes']),124)
        self.assertEqual(colors,[0xffa000ff,0xffffa000,0xff0070ff,0xffffffff,0xff00ff00,0xff00ffff,0xffff00ff,0xffffff00])


if __name__=='__main__':unittest.main()
