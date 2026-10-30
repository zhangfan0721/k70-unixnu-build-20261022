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


class TimerIrqTests(unittest.TestCase):
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

    def setUp(self):self.assertIsNotNone(self.b,'timer IRQ builder missing')

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
        for i in range(16):self.assertEqual(target(BASE+0x3f6000+i*128,vectors[i*4:i*4+4]),(0x881604b00 if i==1 else DIAG+s['exception_vector_%d'%i]))

    def test_wrong_input_fails_before_output(self):
        path=Path(self.temp.name)/'bad';path.write_bytes(b'bad')
        out=Path(self.temp.name)/'bad-output'
        with self.assertRaises(ValueError):self.b.build(path,out)
        self.assertFalse(out.exists())

    def execute(self,*,corrupt=False,bad_readback=False,record_fault=False,record_redirect=False,stack_fault=False,vector=None,exception_after_stack=False,draw=False,wrong_arg=False,bad_cpacr=False,bad_tpidr=False,frame_corrupt=False,wrong_sp=False,wrong_fp=False,wrong_x19=False,guard_corrupt=False,exception_after_c_write=None,cleanup_fault=False,cleanup_redirect=False,huge_ctr=False,cache_field=4,wrong_lr=False,wrong_header_base=False,wrong_header_flags=False,corrupt_header=False,exception_at=None,fault=None,far_value=0xa55a12340000beef,physical=(0x1000000000,0x1000001000,0x1000003000),virtual=(0x500000000,0x500001000,0x500003000),frequencies=(19200000,19200000),irq_fault=None,gic_fault=None,irq_point='first',counter_start=0x1000000000):
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
        u.mem_map(0x17100000,0x10000);u.mem_map(0x17180000,0x200000)
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
        s.update(daif=0x3c0,tick=counter_start,ctl=0,cval=0x12345678,igrpen=0,rpr=255,
            dctl=0x10,ppi=0,active=0,pending=0,irq_injected=False,eret=False,mmio=[],sys_writes=[],
            irq_gp=None,irq_pc=None,irq_spsr=None,sp1_initial=None,irq_snapshot=None)
        if gic_fault=='cpu_enabled':s['igrpen']=1
        if gic_fault=='timer_enabled':s['ctl']=1
        if gic_fault=='dist_enabled':s['dctl']=0x12
        if gic_fault=='are_off':s['dctl']=0
        if gic_fault=='disabled_istatus':s['ctl']=2
        s['original_config']=(s['dctl'],s['igrpen'],s['ctl']&3,s['cval'])
        specials.update({(3,0,0,0,5):0x80000000,(3,0,12,12,5):1,(3,0,12,12,4):2 if gic_fault=='eoi_mode' else 0,
            (3,0,4,6,0):0xff,(3,3,13,0,2):0,(3,3,13,0,3):0})
        if gic_fault=='sre_off':specials[(3,0,12,12,5)]=0
        if gic_fault=='pmr':specials[(3,0,4,6,0)]=0x80
        gpregs=[getattr(A,'UC_ARM64_REG_X'+str(i)) for i in range(31)]
        def gps():return tuple(u.reg_read(x) for x in gpregs)
        key=lambda cp:(cp.op0,cp.op1,cp.crn,cp.crm,cp.op2)
        def walk(at,**kw):return model.walk(at,s,lambda p:struct.unpack('<Q',u.mem_read(p,8))[0],**kw)
        def mrs(uc,reg,cp,_):
            k=key(cp)
            if k==(3,3,14,0,0):
                v=frequencies[1 if s['eret'] else 0]
            elif k==(3,3,14,0,2):v=s['tick']
            elif k==(3,3,14,3,1):v=(s['ctl']&3)|(4 if (s['ctl']&1 and s['tick']>=s['cval']) or gic_fault=='disabled_istatus' else 0)
            elif k==(3,3,14,3,2):v=s['cval']
            elif k==(3,0,12,12,7):v=s['igrpen']
            elif k==(3,0,12,11,3):v=s['rpr']
            elif k==(3,0,12,12,0):
                v=28 if irq_fault=='wrong_id' else 1023 if irq_fault=='spurious' else 27
                if v<1020:s['active']=1<<v;s['pending']=0;s['rpr']=0x80
            elif k==(3,0,4,1,0):v=s['sp'][0]
            elif k==(3,3,4,2,0):v=uc.reg_read(A.UC_ARM64_REG_NZCV)
            elif k==(3,3,4,2,1):v=s['daif']
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
            s['sys_writes'].append((k,v))
            if k==(3,3,14,3,1):s['ctl']=v&3;return True
            if k==(3,3,14,3,2):s['cval']=v;return True
            if k==(3,0,12,12,7):s['igrpen']=v;return True
            if k==(3,0,12,12,1):
                self.assertEqual(s['ctl']&1,0,'timer level must be deasserted before EOI')
                self.assertNotIn(v,range(1020,1024),'special INTIDs must never be EOId')
                self.assertEqual(s['active'],1<<v);s['active']=0;s['rpr']=255;return True
            if k in [(3,0,4,0,0),(3,0,4,0,1)]:specials[k]=v;return True
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
            begin=kva+sy['irq_wait_begin'];end=kva+sy['irq_wait_end']
            if pc==kva+sy['irq_returned'] and irq_fault and irq_fault.startswith('post_gp_'):
                r=int(irq_fault.rsplit('_',1)[1]);uc.reg_write(gpregs[r],uc.reg_read(gpregs[r])^1)
            if begin<=pc<end and not s['eret']:
                if irq_fault!='stalled':s['tick']+=4
                when=s['cval']+(64 if irq_point=='late' else 0)
                deliver=s['ctl']&1 and not s['ctl']&2 and s['tick']>=when and s['igrpen']&1 and s['ppi']&(1<<27) and s['dctl']&2 and not s['daif']&0x80
                if irq_fault=='no_irq':deliver=False
                if isinstance(irq_point,int) and pc!=begin+irq_point:deliver=False
                if deliver and not s['irq_injected']:
                    s['irq_injected']=True;s['irq_gp']=gps();s['irq_pc']=pc
                    s['sp'][0]=uc.reg_read(A.UC_ARM64_REG_SP);s['sp1_initial']=s['sp'][1]
                    raw=(uc.reg_read(A.UC_ARM64_REG_NZCV)&0xf0000000)|s['daif']|4
                    s['irq_spsr']=raw
                    specials[(3,0,4,0,0)]=raw^(0x80 if irq_fault=='bad_spsr' else 0)
                    specials[(3,0,4,0,1)]=end if irq_fault=='bad_elr' else pc
                    s['sel']=1;s['daif']=0x3c0
                    uc.reg_write(A.UC_ARM64_REG_SP,s['sp'][1])
                    uc.reg_write(A.UC_ARM64_REG_PC,s['vbar']+128);return
            if pc==kva+sy['irq_arm']:
                if irq_fault=='token':uc.mem_write(0x881606400,bytes(8))
                if irq_fault=='ready':uc.mem_write(0x881606470,bytes(8))
                if irq_fault=='busy':uc.mem_write(0x881606410,struct.pack('<Q',1))
            if pc==0x881604000+self.report['transition_symbols']['irq_validate_return']:
                if irq_fault=='cookie':uc.mem_write(0x881606000+3072+272,bytes(8))
                if irq_fault=='double':uc.mem_write(0x881606418,struct.pack('<Q',2))
            ins=struct.unpack('<I',uc.mem_read(pc,4))[0]
            if not draw and 0x881604000<=pc<0x881604000+self.report['transition_symbols']['gic_setup'] and ins==0xb800452a:
                uc.reg_write(A.UC_ARM64_REG_X11,1) # One pixel per band; full raster tested once.
            if ins&0xfffff01f==0xd503401f: # DAIFSet/Clr immediate
                mask=((ins>>8)&15)<<6
                s['daif']=(s['daif']|mask) if not ins&0x20 else s['daif']&~mask
                uc.reg_write(A.UC_ARM64_REG_PC,pc+4);return
            if ins&0xfff00000 in [0xd5300000,0xd5100000]:
                from types import SimpleNamespace
                cp=SimpleNamespace(op0=(ins>>19)&3,op1=(ins>>16)&7,crn=(ins>>12)&15,crm=(ins>>8)&15,op2=(ins>>5)&7)
                rt=ins&31;reg=gpregs[rt] if rt<31 else A.UC_ARM64_REG_XZR
                (mrs if ins&0x200000 else msr)(uc,reg,cp,None)
                uc.reg_write(A.UC_ARM64_REG_PC,pc+4);return
            if ins in [0xd50040bf,0xd50041bf]:
                sel=(ins>>8)&1;s['sp'][s['sel']]=uc.reg_read(A.UC_ARM64_REG_SP);s['sel']=sel
                uc.reg_write(A.UC_ARM64_REG_SP,s['sp'][sel]);uc.reg_write(A.UC_ARM64_REG_PC,pc+4);return
            if ins==0xd69f03e0:
                self.assertIsNotNone(s['irq_gp']);self.assertEqual(gps(),s['irq_gp'],'all31GP at ERET')
                self.assertEqual(specials[(3,0,4,0,1)],s['irq_pc'],'same interrupted PC')
                self.assertEqual(specials[(3,0,4,0,0)],s['irq_spsr'],'full raw SPSR preserved')
                self.assertEqual(uc.reg_read(A.UC_ARM64_REG_SP),s['sp1_initial'],'SP1 unchanged')
                self.assertEqual(s['tpidr_el1'],0);self.assertEqual(specials[(3,3,13,0,2)],0);self.assertEqual(specials[(3,3,13,0,3)],0)
                self.assertEqual(s['active'],0)
                s['sel']=0;s['daif']=s['irq_spsr']&0x3c0;s['eret']=True
                uc.reg_write(A.UC_ARM64_REG_NZCV,s['irq_spsr']&0xf0000000)
                uc.reg_write(A.UC_ARM64_REG_SP,s['sp'][0]);uc.reg_write(A.UC_ARM64_REG_PC,s['irq_pc']);return
            if ins&0xfff80000==0xd5080000:
                op1=(ins>>16)&7;crn=(ins>>12)&15;crm=(ins>>8)&15;op2=(ins>>5)&7;rt=ins&31
                v=0 if rt==31 else uc.reg_read(A.UC_ARM64_REG_X0+rt)
                if (op1,crn,crm,op2) in [(0,7,8,0),(0,7,8,1)]:
                    physical=walk(v,write=op2==1)
                    if v==0x881606000:
                        s['record_checks']+=1
                        phase={1:'pre',2:'irq',3:'handler',4:'cleanup'}.get(s['record_checks'],'other')
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
        for at,hook in [(first+4,skip)]:
            u.hook_add(U.UC_HOOK_CODE,hook,begin=at,end=at)
        def clean(uc,pc,n,_):
            s['cache']+=1
            if s['cache']==1:self.assertEqual(uc.reg_read(A.UC_ARM64_REG_X6),guard)
            if s['cache']==2:uc.reg_write(A.UC_ARM64_REG_X6,BASE+0x10000000-64)
        at=0x881604000+self.report['transition_symbols']['transition_clean_loop'];u.hook_add(U.UC_HOOK_CODE,clean,begin=at,end=at)
        def memory(uc,access,address,n,value,_):
            if 0x17100000<=address<0x17380000:
                self.assertFalse(s['sctlr']&1,'GIC MMIO forbidden with M1')
                rb=0x171c0000 if gic_fault=='affinity_second' and address>=0x171c0000 else 0x17180000
                self.assertEqual(n,8 if address==rb+8 else 4)
                off=address-rb
                read={0x17100000:s['dctl']|(0x80000000 if gic_fault=='dist_rwp' else 0),
                    0x17100004:0x80000101 if gic_fault in ['espi','other_espi'] else 31 if gic_fault=='max_spi' else 1,rb:8 if gic_fault=='redist_rwp' else 1 if gic_fault=='lpi' else 0,
                    rb+8:(1<<32)|16 if gic_fault=='affinity' else 16,
                    rb+0xffe8:0x20 if gic_fault=='pidr' else 0x30,rb+0x14:2 if gic_fault=='asleep' else 0,
                    rb+0x10080:0 if gic_fault=='group' else 1<<27,
                    rb+0x10100:s['ppi']|(1<<26 if gic_fault=='other_ppi' else 0),
                    rb+0x10300:s['active']|(1 if gic_fault=='other_active' else 0),
                    rb+0x10418:0x80808080,rb+0x10c04:1<<23 if gic_fault=='edge' else 0,
                    0x17100104:1 if gic_fault=='other_spi' else 0,
                    0x17101200:1 if gic_fault=='other_espi' else 0}
                if gic_fault=='affinity_second':read[rb+8]=16 if rb==0x171c0000 else (1<<32)|2
                if gic_fault=='enable_readback' and s['ppi']:read[rb+0x10100]=0
                if access==U.UC_MEM_WRITE:
                    self.assertIn(address,[0x17100000,rb+0x10100,rb+0x10180,rb+0x10280])
                    if address!=0x17100000:self.assertEqual(value,1<<27)
                    if address==0x17100000:
                        self.assertIn(value,[0x10,0x12]);s['dctl']=value
                        if gic_fault=='restore' and value==0x10:s['dctl']=0x12
                    elif address==rb+0x10100:s['ppi']|=value
                    elif address==rb+0x10180:s['ppi']&=~value
                    else:s['pending']&=~value
                    s['mmio'].append((address,value))
                else:uc.mem_write(address,int(read.get(address,0)).to_bytes(n,'little'))
                return
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
            (folder/'host-timer-irq-render.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1440,1440,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
        return record,s,colors


    def test_irq_delivery_same_pc_eret_all_integer_registers_and_restore(self):
        for point in ['first','late']:
            with self.subTest(point=point):
                raw,s,_=self.execute(irq_point=point);v=raw[1:]
                self.assertEqual(v[0:3],(0,0,4));self.assertTrue(s['eret'])
                self.assertEqual(v[5],27);self.assertEqual(v[0xa],1);self.assertEqual(v[0x10]&7,5)
                self.assertEqual(v[0x12],27);self.assertEqual(v[0x14],1)
                self.assertEqual(v[0x15:0x18],(0xfffffff007c04000,)*3)
                self.assertEqual(v[0x18],0x7fffe1ff);self.assertEqual(v[0x21:0x24],(1,1,1))
                self.assertEqual((s['dctl'],s['igrpen'],s['ctl']&3,s['cval']),s['original_config'])
                self.assertFalse(s['ppi']);self.assertFalse(s['active'])
                self.assertEqual(self.report['record_schema'],'virtual-timer-irq-v1')
                self.assertEqual(len(s['c_writes']),16);self.assertEqual(sum(x[2] for x in s['c_writes']),124)

    def test_bad_irq_identity_context_token_and_reentry_never_resume(self):
        for bad in ['wrong_id','spurious','bad_spsr','bad_elr','token','ready','busy','cookie','double']:
            with self.subTest(bad=bad):
                raw,s,_=self.execute(irq_fault=bad);self.assertNotEqual(raw[1],0);self.assertEqual(raw[36],0)
                self.assertFalse(s['eret'])

    def test_absent_or_stalled_irq_is_bounded_and_restores(self):
        for bad in ['no_irq','stalled']:
            with self.subTest(bad=bad):
                raw,s,_=self.execute(irq_fault=bad)
                self.assertEqual(raw[1],2);self.assertEqual(raw[36],0);self.assertFalse(s['eret'])
                self.assertEqual((s['dctl'],s['igrpen'],s['ctl']&3,s['cval']),s['original_config'])

    def test_gic_readiness_and_restore_fail_closed(self):
        for bad in ['cpu_enabled','timer_enabled','dist_enabled','eoi_mode','dist_rwp','redist_rwp','lpi','affinity','asleep','group','other_ppi','other_spi','edge','restore']:
            with self.subTest(bad=bad):
                raw,s,_=self.execute(gic_fault=bad);self.assertNotEqual(raw[1],0);self.assertEqual(raw[36],0)
                if bad!='restore':self.assertFalse(s['eret'])

    def test_frequency_wrap_and_existing_abi_guards(self):
        for opts in [dict(frequencies=(0,0)),dict(frequencies=(999999,999999)),dict(frequencies=(1000000001,)*2),
                     dict(frequencies=(19200000,19200001)),dict(counter_start=2**64-20),
                     dict(wrong_arg=True),dict(bad_cpacr=True),dict(bad_tpidr=True),dict(frame_corrupt=True),dict(wrong_lr=True)]:
            with self.subTest(opts=opts):
                raw,_,_=self.execute(**opts);self.assertNotEqual(raw[1],0);self.assertEqual(raw[36],0)

    def test_record_and_frame_translations_fail_without_unsafe_access(self):
        for opts in [dict(record_fault=True),dict(record_redirect=True),dict(cleanup_fault=True),
                     dict(cleanup_redirect=True),dict(fault='frame_high'),dict(huge_ctr=True)]:
            with self.subTest(opts=opts):
                raw,s,_=self.execute(**opts);self.assertTrue(s['frame_halt']);self.assertEqual(s['sctlr']&0x1005,0x1005)
                self.assertFalse(s['ctl']&1);self.assertFalse(s['igrpen'])

    def test_all_unarmed_vectors_reject(self):
        for i in range(16):
            with self.subTest(i=i):
                raw,s,_=self.execute(vector=i);self.assertNotEqual(raw[1],0);self.assertEqual(raw[36],0);self.assertFalse(s['eret'])

    def test_renderer_and_supported_cache_geometry(self):
        for field in [2,4,5,10]:
            with self.subTest(field=field):
                raw,s,colors=self.execute(cache_field=field,draw=field==4);self.assertEqual(raw[1],0)
                self.assertFalse(s['dirty']);self.assertGreater(s['frame_cleans'],0)
                if field==4:self.assertEqual(colors,[0xffa000ff,0xffffa000,0xff0070ff,0xffffffff,0xff00ff00,0xff00ffff,0xffff00ff,0xffffff00])

    def test_blob_extent_and_cross_elf_contract(self):
        r=self.report
        self.assertEqual(r['transition_symbols']['gic_restore'],0x700)
        self.assertEqual(r['transition_symbols']['irq_entry'],0xb00)
        self.assertEqual(r['irq_intid'],27);self.assertTrue(r['eret_or_resume_executed'])
        self.assertFalse(r['new_mmu_mappings']);self.assertFalse(r['hardware_tested'])
        self.assertLessEqual(r['stub_bytes'],4096);self.assertLessEqual(r['transition_bytes'],4096)
        self.assertEqual(r['stable_gp_mask'],0x7fffe1ff)

    def test_every_permitted_interrupted_instruction_restores_all31_gp(self):
        sy=self.report['checkpoint_symbols']
        for off in range(0,sy['irq_wait_end']-sy['irq_wait_begin'],4):
            with self.subTest(off=off):
                raw,s,_=self.execute(irq_point=off);self.assertEqual(raw[1],0);self.assertTrue(s['eret'])

    def test_hardware_stable_gp_gate_rejects_post_return_corruption(self):
        for r in [0,8,13,18,29,30]:
            with self.subTest(r=r):
                raw,s,_=self.execute(irq_fault='post_gp_'+str(r));self.assertNotEqual(raw[1],0);self.assertEqual(raw[36],0)

    def test_remaining_gic_readiness_and_extended_source_coverage(self):
        for bad in ['are_off','sre_off','pmr','pidr','other_active','other_espi','enable_readback']:
            with self.subTest(bad=bad):
                raw,s,_=self.execute(gic_fault=bad);self.assertNotEqual(raw[1],0);self.assertEqual(raw[36],0)
        for compatible in ['max_spi','espi','affinity_second','disabled_istatus']:
            with self.subTest(compatible=compatible):
                raw,s,_=self.execute(gic_fault=compatible);self.assertEqual(raw[1],0);self.assertTrue(s['eret'])

    def test_irq_record_translation_cannot_use_redirected_high_or_faulted_pa(self):
        for bad in ['fault','redirect','high']:
            with self.subTest(bad=bad):
                _,s,_=self.execute(fault='record_irq_'+bad);self.assertTrue(s['frame_halt']);self.assertFalse(s['eret'])

if __name__=='__main__':unittest.main()

