#!/usr/bin/env python3
"""Build a bounded MMU-on checkpoint around the pinned original common_start."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
BASE,VM,DIAG=0x880004000,0xfffffff007004000,0x881608000
PIN='5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8'
OFFSETS=[0x3f7290,0x3f733c,0x3f7358]
sha=lambda x:hashlib.sha256(x).hexdigest()


def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def reviewed(name,folder,digest):
    path=HERE.parent/folder/name
    if sha(path.read_bytes().replace(b'\r\n',b'\n'))!=digest:raise ValueError('Reviewed source changed: '+str(path))
    return path


def build(kernel,output):
    data=Path(kernel).read_bytes()
    if sha(data)!=PIN:raise ValueError('Wrong pinned kernel')
    old=module('mmu_reviewed_bootstrap',reviewed('blobs.py','xnu-bootstrap-checkpoint','b8417450f7401d7839feb573206c494b0a91a49f5d6bcdf0fe63c845ce466065'))
    helper=module('mmu_reviewed_elf',reviewed('blobs.py','xnu-entry-checkpoint','486a1a9c3b534b0f531b6ac4a9484579f9f25ec914051894623a616f778d7be3'))
    symbols=old.profile(data)
    sys.path.insert(0,str(HERE.parent/'xnu-preflight'))
    from payload import materialize
    plan,mapped=materialize(data)
    if (plan.VmBase,plan.Span,plan.EntryOffset)!=(VM,0x1544000,0x3f5488):raise ValueError('Kernel layout changed')
    originals=b''.join(mapped[o:o+4] for o in OFFSETS)
    if originals!=struct.pack('<3I',0x90ffebe0,0xd518c000,0xf2e00001):raise ValueError('Original common_start changed')
    prefix=mapped[0x3f705c:0x3f7290];mmuhelper=mapped[0x3fb2fc:0x3fb30c]
    if sha(prefix)!='39c4730dc3a818c80fcb5373fee3e78eee7c86e2e2a8da97e3e648e93667d694':raise ValueError('Original firstCPU changed')
    if mmuhelper!=struct.pack('<4I',0xd5033b9f,0xd5182000,0xd5033fdf,0xd65f03c0):raise ValueError('Original TTBR helper changed')
    for i in range(16):
        if mapped[0x3f6000+i*128:0x3f6004+i*128]!=struct.pack('<I',0x14000000):raise ValueError('Original low vector changed')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    built={}
    for label,entry,files in [('checkpoint','kernel_checkpoint_begin',['checkpoint.S','renderer.S']),('transition','transition_begin',['transition.S'])]:
        objects=[]
        for source in files:
            obj=output/(source+'.o');objects.append(str(obj))
            subprocess.run(['clang','--target=aarch64-none-elf','-march=armv9-a','-c',str(HERE/source),'-o',str(obj)],check=True,capture_output=True)
        elf=output/(label+'.elf')
        subprocess.run(['ld.lld','--no-relax','-Ttext=0','-e',entry,*objects,'-o',str(elf)],check=True,capture_output=True)
        blob,syms=helper.extract_elf(elf.read_bytes())
        if syms.get(entry)!=0 or not 0<len(blob)<=4096:raise ValueError('Blob entry or extent')
        (output/(label+'.bin')).write_bytes(blob)
        dis=subprocess.run(['llvm-objdump','-d',str(elf)],check=True,capture_output=True,text=True)
        (output/(label+'.disassembly.txt')).write_text(dis.stdout)
        built[label]=blob,syms
    stub,ss=built['checkpoint'];transition,ts=built['transition']
    patches=old.branch(BASE+OFFSETS[0],DIAG+ss['pre_switch_gate'])+struct.pack('<I',0xd503201f)+old.branch(BASE+OFFSETS[2],DIAG)
    vectors=b''.join(old.branch(BASE+0x3f6000+i*128,DIAG+ss['exception_vector_%d'%i]) for i in range(16))
    changed=bytearray(mapped)
    for i,o in enumerate(OFFSETS):changed[o:o+4]=patches[i*4:i*4+4]
    for i in range(16):changed[0x3f6000+i*128:0x3f6004+i*128]=vectors[i*4:i*4+4]
    tables=old.expected_tables()
    for name,blob in [('code-patches',patches),('code-originals',originals),('vector-patches',vectors),('expected-bootstrap-tables',tables)]:
        (output/(name+'.bin')).write_bytes(blob)
    r=dict(mode='original-common-mmu-checkpoint',kernel_sha256=PIN,original_entry_pa=BASE+0x3f5488,
        checkpoint_pa=DIAG,transition_pa=0x881604000,record_pa=0x881606000,stub_bytes=len(stub),transition_bytes=len(transition),
        stub_sha256=sha(stub),transition_sha256=sha(transition),original_patch_sha256=sha(bytes(len(stub))),
        instrumented_mapped_sha256=sha(changed),vector_patch_sha256=sha(vectors),code_patch_sha256=sha(patches),
        code_patch_offsets=OFFSETS,code_originals_sha256=sha(originals),original_prefix_sha256=sha(prefix),original_helper_sha256=sha(mmuhelper),
        checkpoint_symbols=ss,transition_symbols=ts,original_symbols=symbols,
        code_pages=[0x8803f9000,0x8803fb000,0x881604000,0x8803fa000,0x8803ff000,DIAG],
        bootstrap_pool_pa=0x88017a000,bootstrap_pool_bytes=65536,expected_bootstrap_tables_sha256=sha(tables),
        bootstrap_map_start=0x880000000,bootstrap_map_end=0x890000000,bootstrap_map_contained=True,bootstrap_map_will_be_enabled=True,
        guard_pa=0x880000000,guard_bytes=16384,unmapped_tail_bytes=16384,original_first_cpu_prefix_preserved=True,
        original_common_start_instrumented=True,original_cpu_init_completed=False,hardware_tested=False,
        model_scope='Original instructions and coherent shared-memory aliases; privileged registers, AT/PAR, cache, DAIF and SPSel explicitly modeled, not hardware evidence')
    header='// Stage09: separate diagnostic page; exactly3 common words and16 vector branches.\n'
    arrays=[('mEntryStub',stub),('mEntryTransition',transition),('mEntryOriginalPatch',bytes(len(stub))),
        ('mEntryVectorPatch',vectors),('mMmuCodePatches',patches),('mMmuCodeOriginals',originals)]
    for name,blob in [('mEntryStubHash',stub),('mEntryTransitionHash',transition),('mEntryMappedHash',changed),
        ('mEntryVectorPatchHash',vectors),('mMmuCodePatchesHash',patches),('mOriginalPrefixHash',prefix),('mOriginalHelperHash',mmuhelper)]:arrays.append((name,bytes.fromhex(sha(blob))))
    for name,blob in arrays:header+=helper.array(name,blob)
    header+='STATIC CONST UINT64 mMmuCodeOffsets[] = {0x3f7290,0x3f733c,0x3f7358};\n'
    (output/'EntryBlobs.h').write_text(header)
    (output/'proof.json').write_text(json.dumps(r,indent=2)+'\n')
    return header,r


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kernel',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();_,r=build(a.kernel,a.out);print(json.dumps(r,indent=2))
