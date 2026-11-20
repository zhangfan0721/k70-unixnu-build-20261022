#!/usr/bin/env python3
"""Generate stage10 from the exact reviewed stage09 package."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent


def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def change(text,before,after,count=1):
    if text.count(before)!=count:raise ValueError('Reviewed anchor changed: '+before[:80])
    return text.replace(before,after)


def prepare(root,dtb,kernel,payload,blobs_out):
    previous_path=HERE.parent/'xnu-mmu-checkpoint/prepare.py'
    if hashlib.sha256(previous_path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!='95aefcbc06b6b7938588f1987a30d63b7b772a4b54f119090b70bca3e103c2ed':
        raise ValueError('Reviewed stage09 generator changed')
    previous=module('c_entry_previous_prepare',previous_path)
    with tempfile.TemporaryDirectory(prefix='stage09-generator-') as tmp:
        report=previous.prepare(root,dtb,kernel,payload,Path(tmp)/'blobs')
    builder=module('c_entry_builder',HERE/'blobs.py');header,proof=builder.build(kernel,blobs_out)
    app=root/'Platforms/Xiaomi/vermeerProbePkg/Probe'
    text=(app/'Entry.c').read_text()
    text=change(text,'Before[6]','Before[7]');text=change(text,'K70_U64 Pages[6]','K70_U64 Pages[7]')
    text=change(text,'I < 6;','I < 7;',4)
    text=change(text,'Before[3].Flags | Before[5].Flags','Before[3].Flags | Before[5].Flags | Before[6].Flags')
    anchor='  for (I = 0; I < 3; I++)\n    if (CompareMem((VOID *)(UINTN)(Base + mMmuCodeOffsets[I]), mMmuCodeOriginals + 4 * I, 4)) goto Fail;'
    extra='''  if (!Sha256HashAll((VOID *)(UINTN)(Base + 0x9e1e34), 60, Digest) ||
      CompareMem(Digest, mOriginalArmInitHash, 32)) goto Fail;
'''
    text=change(text,anchor,extra+anchor)
    text=change(text,'K70 STAGE09 ORIGINAL MMU CHECKPOINT','K70 STAGE10 VIRTUAL C ENTRY CHECKPOINT')
    text=change(text,'Test original TCR/MMU enable; stop before arm_init; no userland','Original common_start RET to arm_init KVA; C body NOT executed')
    text=change(text,'Blue/white/GREEN/CYAN: XNU mappings, aliases and stack PASS','Blue/white/GREEN/CYAN/MAGENTA: virtual C entry and ABI PASS')
    text=change(text,'Original prefix/helper hashes OK; original MMU sequence follows','Original prefix/helper/C-entry hashes OK; virtual return follows')
    text=change(text,'1C alias-word,1D stack-test; 00=0 + CYAN means checkpoint PASS','1C alias-word,1D stack-test;1E virtual-PC,1F x0\\n00=0 + MAGENTA means checkpoint PASS')
    text=change(text,'strictly below the last diagnostic row1270','strictly below the last diagnostic row1334')
    (app/'Entry.c').write_text(text,newline='\n')
    text=(app/'EntryCore.c').read_text();text=change(text,'Pages[6]','Pages[7]')
    text=change(text,'Pages[5] = Base + 0x1604000;','Pages[5] = Base + 0x1604000; Pages[6] = Base + 0x9e1000;')
    (app/'EntryCore.c').write_text(text,newline='\n')
    text=(app/'EntryCore.h').read_text();text=change(text,'Pages[6]','Pages[7]');(app/'EntryCore.h').write_text(text,newline='\n')
    (app/'EntryBlobs.h').write_text(header,newline='\n')
    text=(app/'Preflight.c').read_text();text=change(text,'K70 STAGE09 MMU - DATA PREFLIGHT','K70 STAGE10 VIRTUAL C ENTRY - PREFLIGHT')
    (app/'Preflight.c').write_text(text,newline='\n')
    report.update(mode='original-c-entry-checkpoint',entry=proof,original_arm_init_body_executed=False,hardware_tested=False)
    report['display']=dict(console_row_pixels=36,spacer_lines=40,context_start_row=1440,record_start_row=640,
        record_last_row=1334,record_words=32,columns=2,console_cursor_explicitly_reset=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['uefi','dtb','kernel','payload','blobs']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    try:r=prepare(a.uefi.resolve(),a.dtb.resolve(),a.kernel.resolve(),a.payload.resolve(),a.blobs.resolve())
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
    print(json.dumps(r,indent=2))
