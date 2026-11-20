#!/usr/bin/env python3
"""Pinned original-prefix checkpoint builder; no original common_start execution."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PIN = '5fcfc61aa8a2d9670b03e53127c93364a418c76d84d713b2c11aea69623a25a8'
BASE, VM, FIRST, COMMON, VECTOR, POOL = 0x880004000, 0xfffffff007004000, 0x3f705c, 0x3f7290, 0x3f6000, 0x88017a000
sha = lambda b: hashlib.sha256(b).hexdigest()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def expected_tables():
    data = bytearray(65536)
    struct.pack_into('<Q', data, 34*8, POOL+0x2003)
    struct.pack_into('<Q', data, (512+192)*8, POOL+0x3003)
    for i in range(128):
        value = (0x880000000+i*0x200000)|0x601
        struct.pack_into('<Q', data, (1024+i)*8, value)
        struct.pack_into('<Q', data, (1536+56+i)*8, value)
    return bytes(data)


def profile(data):
    if sha(data) != PIN: raise ValueError('Wrong pinned kernel')
    count, total = struct.unpack_from('<II', data, 16)
    if count > 128 or 32+total > len(data): raise ValueError('Command bounds')
    at, table = 32, None
    for _ in range(count):
        kind, size = struct.unpack_from('<II', data, at)
        if size < 8 or at+size > 32+total: raise ValueError('Command extent')
        if kind == 2: table = struct.unpack_from('<4I', data, at+8)
        at += size
    if at != 32+total or table is None: raise ValueError('Command/symbol table')
    so, ns, st, sl = table
    if so+16*ns > len(data) or st+sl > len(data): raise ValueError('Symbol bounds')
    want = dict(_start_first_cpu=VM+FIRST, common_start=VM+COMMON,
                _LowExceptionVectorBase=VM+VECTOR, _bootstrap_pagetables=VM+0x176000,
                _excepstack_top=0xfffffff007c04000, _intstack_top=0xfffffff007bfc000,
                _arm_init=0xfffffff0079e5e34)
    found = {}
    for i in range(ns):
        index, kind, section, desc, value = struct.unpack_from('<IBBHQ', data, so+16*i)
        if index >= sl: raise ValueError('Symbol string bounds')
        stop = data.find(b'\0', st+index, st+sl)
        if stop < 0: raise ValueError('Unterminated symbol')
        name = data[st+index:stop].decode('utf8', errors='strict')
        if name in want and (kind&14)==14:
            if name in found: raise ValueError('Duplicate defined symbol')
            found[name]=value
    if found != want: raise ValueError('Original prefix symbol profile changed')
    return found


def branch(source, target):
    delta = target-source
    if delta%4 or not -(1<<27)<=delta<(1<<27): raise ValueError('AArch64 B range/alignment')
    return struct.pack('<I',0x14000000|((delta//4)&0x3ffffff))


def build(kernel_path, output):
    kernel_path=Path(kernel_path); data=kernel_path.read_bytes(); symbols=profile(data)
    old=HERE.parent/'xnu-entry-checkpoint/blobs.py'
    if sha(old.read_bytes().replace(b'\r\n',b'\n'))!='486a1a9c3b534b0f531b6ac4a9484579f9f25ec914051894623a616f778d7be3':
        raise ValueError('Reviewed ELF/array helper changed')
    helper=module('reviewed_entry_builder',old)
    sys.path.insert(0,str(HERE.parent/'xnu-preflight'))
    from payload import materialize
    plan,mapped=materialize(data)
    if plan.VmBase!=VM or plan.Span!=0x1544000 or plan.EntryOffset!=0x3f5488:
        raise ValueError('Kernel layout changed')
    if struct.unpack_from('<I',mapped,FIRST)[0]!=0xd510109f or struct.unpack_from('<I',mapped,COMMON-4)[0]!=0x14000001:
        raise ValueError('Original prefix endpoints changed')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    built={}
    for name,symbol in [('checkpoint','kernel_checkpoint_begin'),('transition','transition_begin')]:
        obj,elf=output/(name+'.o'),output/(name+'.elf')
        subprocess.run(['clang','--target=aarch64-none-elf','-march=armv9-a','-c',str(HERE/(name+'.S')),'-o',str(obj)],check=True,capture_output=True)
        subprocess.run(['ld.lld','--no-relax','-Ttext=0','-e',symbol,str(obj),'-o',str(elf)],check=True,capture_output=True)
        blob,syms=helper.extract_elf(elf.read_bytes())
        if syms.get(symbol)!=0:raise ValueError('Blob entry offset')
        (output/(name+'.bin')).write_bytes(blob)
        dis=subprocess.run(['llvm-objdump','-d',str(elf)],check=True,capture_output=True,text=True)
        (output/(name+'.disassembly.txt')).write_text(dis.stdout)
        built[name]=blob,syms
    stub,stub_symbols=built['checkpoint']; transition,transition_symbols=built['transition']
    if not 0<len(stub)<=4096-0x290:raise ValueError('Checkpoint crosses common_start page')
    segment=[s for s in plan.Segments[:plan.Count] if s.Offset<=COMMON and COMMON+len(stub)<=s.Offset+s.FileSize and s.Protection==5]
    if len(segment)!=1:raise ValueError('Checkpoint must be file-backed executable text')
    for i in range(16):
        if mapped[VECTOR+128*i:VECTOR+128*i+4]!=struct.pack('<I',0x14000000):
            raise ValueError('Original low vector differs')
    vectors=b''.join(branch(BASE+VECTOR+128*i,BASE+COMMON+stub_symbols['exception_vector_%d'%i]) for i in range(16))
    (output/'vector-patches.bin').write_bytes(vectors)
    original=mapped[COMMON:COMMON+len(stub)]
    changed=bytearray(mapped);changed[COMMON:COMMON+len(stub)]=stub
    for i in range(16):changed[VECTOR+128*i:VECTOR+128*i+4]=vectors[4*i:4*i+4]
    if changed[FIRST:COMMON]!=mapped[FIRST:COMMON] or changed[0x3f5488:0x3f548c]!=struct.pack('<I',0x140006f5):
        raise ValueError('Original entry/prefix changed')
    tables=expected_tables();(output/'expected-bootstrap-tables.bin').write_bytes(tables)
    report=dict(mode='original-prefix-bootstrap-checkpoint',kernel_sha256=PIN,original_entry_pa=BASE+0x3f5488,
                checkpoint_pa=BASE+COMMON,transition_pa=0x881604000,record_pa=0x881606000,
                original_entry_instruction='0x140006f5',stub_bytes=len(stub),transition_bytes=len(transition),
                stub_sha256=sha(stub),transition_sha256=sha(transition),original_patch_sha256=sha(original),
                vector_patch_sha256=sha(vectors),instrumented_mapped_sha256=sha(changed),
                original_prefix_sha256=sha(mapped[FIRST:COMMON]),original_first_cpu_prefix_preserved=True,
                code_pages=[0x8803f9000,0x8803fb000,0x881604000,0x8803fa000],
                checkpoint_symbols=stub_symbols,transition_symbols=transition_symbols,original_symbols=symbols,
                expected_bootstrap_tables_sha256=sha(tables),bootstrap_pool_pa=POOL,bootstrap_pool_bytes=65536,
                bootstrap_map_start=0x880000000,bootstrap_map_end=0x890000000,
                bootstrap_map_contained=False,bootstrap_map_will_be_enabled=False,
                hardware_tested=False,original_common_start_executed=False,
                original_cpu_init_completed=False,model_scope='Explicit system-register/cache/DAIF/SPSel models; real original prefix instructions and memory writes tested')
    header='// Stage08 generated arrays: original firstCPU prefix remains intact.\n'
    for name,blob in [('mEntryStub',stub),('mEntryTransition',transition),('mEntryOriginalPatch',original),
                      ('mEntryStubHash',bytes.fromhex(sha(stub))),('mEntryTransitionHash',bytes.fromhex(sha(transition))),
                      ('mEntryMappedHash',bytes.fromhex(sha(changed))),('mEntryVectorPatch',vectors),
                      ('mEntryVectorPatchHash',bytes.fromhex(sha(vectors))),
                      ('mOriginalPrefixHash',bytes.fromhex(sha(mapped[FIRST:COMMON])))]:
        header+=helper.array(name,blob)
    (output/'EntryBlobs.h').write_text(header)
    (output/'proof.json').write_text(json.dumps(report,indent=2)+'\n')
    return header,report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();_,r=build(a.kernel,a.out);print(json.dumps(r,indent=2))

