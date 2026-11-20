#!/usr/bin/env python3
"""Build a bounded original C-prologue checkpoint; first call is not executed."""
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
OFFSETS=[0x3f7290,0x3f733c,0x9e1e70]
sha=lambda x:hashlib.sha256(x).hexdigest()


def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def reviewed(name,folder,digest):
    path=HERE.parent/folder/name
    if sha(path.read_bytes().replace(b'\r\n',b'\n'))!=digest:raise ValueError('Reviewed source changed: '+str(path))
    return path


def reviewed_sources():
    for name,digest in {'blobs.py':'b71ec790cdd9e989256b95856985093bf5adaf4e77a3953aaa28329458bdb77e',
        'prepare.py':'95aefcbc06b6b7938588f1987a30d63b7b772a4b54f119090b70bca3e103c2ed',
        'checkpoint.S':'093e5ceb5489aef4cb66a7b0cd10d720351c217ece54b7075c89a6b172001a50',
        'renderer.S':'e1bb57d2670c842d6fcffdb98a43aad821824c07e6d50616fb4a7f4308b7e4c5',
        'transition.S':'6a7ff045fe2a880e55e32b5a8e2876630930462b3b75f0931e02319ece265756'}.items():
        reviewed(name,'xnu-mmu-checkpoint',digest)
    for name,digest in {'blobs.py': '0dedaa24f04422ba4601b8854832de58fa761e5953d3bfc51b99b7b04c0cca00', 'prepare.py': '06f832eccd9123dcab2db2737aff01fefd51fe4da67d60dcfdb554677d404f92', 'checkpoint.S': 'a160994b44bd68c1b0e390055f6e87028d70f743eef074220dc7927c0ad5e2a3', 'renderer.S': 'f6bce2cf3893e179d0bdeefe69b853a30bdd0eb720b7fe192dcccb3fdc72ea6e', 'transition.S': '6a7ff045fe2a880e55e32b5a8e2876630930462b3b75f0931e02319ece265756'}.items():
        reviewed(name,'xnu-c-entry-checkpoint',digest)


def build(kernel,output):
    data=Path(kernel).read_bytes()
    if sha(data)!=PIN:raise ValueError('Wrong pinned kernel')
    reviewed_sources()
    old=module('mmu_reviewed_bootstrap',reviewed('blobs.py','xnu-bootstrap-checkpoint','b8417450f7401d7839feb573206c494b0a91a49f5d6bcdf0fe63c845ce466065'))
    helper=module('mmu_reviewed_elf',reviewed('blobs.py','xnu-entry-checkpoint','486a1a9c3b534b0f531b6ac4a9484579f9f25ec914051894623a616f778d7be3'))
    symbols=old.profile(data)
    sys.path.insert(0,str(HERE.parent/'xnu-preflight'))
    from payload import materialize
    plan,mapped=materialize(data)
    if (plan.VmBase,plan.Span,plan.EntryOffset)!=(VM,0x1544000,0x3f5488):raise ValueError('Kernel layout changed')
    originals=b''.join(mapped[o:o+4] for o in OFFSETS)
    if originals!=struct.pack('<3I',0x90ffebe0,0xd518c000,0x97e83189):raise ValueError('Original patch instruction profile changed')
    prefix=mapped[0x3f705c:0x3f7290];mmuhelper=mapped[0x3fb2fc:0x3fb30c]
    arminit=mapped[0x9e1e34:0x9e1e70]
    if mapped[0x3f7358:0x3f735c]!=struct.pack('<I',0xf2e00001) or mapped[0x3f7388:0x3f738c]!=struct.pack('<I',0xd65f03c0):raise ValueError('Original common cold tail changed')
    if sha(arminit)!='5fa4ce112042e8a1a11304cedb44900a9024eb4155644a7d8485b14e9acafa47':raise ValueError('Original C prologue changed')
    if mapped[0xb38268:0xb38270]!=bytes(8):raise ValueError('Original guard global changed')
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
    r=dict(mode='original-c-prologue-checkpoint',kernel_sha256=PIN,original_entry_pa=BASE+0x3f5488,
        checkpoint_pa=DIAG,transition_pa=0x881604000,record_pa=0x881606000,stub_bytes=len(stub),transition_bytes=len(transition),
        stub_sha256=sha(stub),transition_sha256=sha(transition),original_patch_sha256=sha(bytes(len(stub))),
        instrumented_mapped_sha256=sha(changed),vector_patch_sha256=sha(vectors),code_patch_sha256=sha(patches),
        code_patch_offsets=OFFSETS,code_originals_sha256=sha(originals),original_prefix_sha256=sha(prefix),original_helper_sha256=sha(mmuhelper),
        original_arm_init_sha256=sha(arminit),original_arm_init_prologue_bytes=60,
        guard_global_va=0xfffffff007b3c268,guard_global_pa=0x880b3c268,guard_global_value=0,
        original_c_frame_bytes=208,original_c_frame_written_bytes=124,first_original_call_executed=False,
        original_arm_init_prologue_executed=True,arm_init_va=0xfffffff0079e5e34,arm_init_pa=0x8809e5e34,
        checkpoint_va=0xfffffff008608000,entry_argument_va=0xfffffff008548000,original_common_cold_tail_preserved=True,
        checkpoint_symbols=ss,transition_symbols=ts,original_symbols=symbols,
        code_pages=[0x8803f9000,0x8803fb000,0x881604000,0x8803fa000,0x8803ff000,DIAG,0x8809e5000],
        bootstrap_pool_pa=0x88017a000,bootstrap_pool_bytes=65536,expected_bootstrap_tables_sha256=sha(tables),
        bootstrap_map_start=0x880000000,bootstrap_map_end=0x890000000,bootstrap_map_contained=True,bootstrap_map_will_be_enabled=True,
        guard_pa=0x880000000,guard_bytes=16384,unmapped_tail_bytes=16384,original_first_cpu_prefix_preserved=True,
        original_common_start_instrumented=True,original_cpu_init_completed=False,original_arm_init_body_executed=False,hardware_tested=False,
        model_scope='Original instructions and coherent shared-memory aliases; privileged registers, AT/PAR, cache, DAIF and SPSel explicitly modeled, not hardware evidence')
    header='// Stage12: exact original C prologue;2common words,1first-BL word,16vectors.\n'
    arrays=[('mEntryStub',stub),('mEntryTransition',transition),('mEntryOriginalPatch',bytes(len(stub))),
        ('mEntryVectorPatch',vectors),('mMmuCodePatches',patches),('mMmuCodeOriginals',originals)]
    for name,blob in [('mEntryStubHash',stub),('mEntryTransitionHash',transition),('mEntryMappedHash',changed),
        ('mEntryVectorPatchHash',vectors),('mMmuCodePatchesHash',patches),('mOriginalPrefixHash',prefix),('mOriginalHelperHash',mmuhelper),
        ('mOriginalArmInitHash',arminit)]:arrays.append((name,bytes.fromhex(sha(blob))))
    for name,blob in arrays:header+=helper.array(name,blob)
    header+='STATIC CONST UINT64 mMmuCodeOffsets[] = {0x3f7290,0x3f733c,0x9e1e70};\n'
    (output/'EntryBlobs.h').write_text(header)
    (output/'proof.json').write_text(json.dumps(r,indent=2)+'\n')
    return header,r


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kernel',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();_,r=build(a.kernel,a.out);print(json.dumps(r,indent=2))
