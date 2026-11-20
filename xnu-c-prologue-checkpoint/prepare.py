#!/usr/bin/env python3
"""Generate stage12 from the hash-pinned, reviewed stage10 package."""
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
    builder=module('c_prologue_builder',HERE/'blobs.py')
    previous_path=HERE.parent/'xnu-c-entry-checkpoint/prepare.py'
    # Pin previous code before any of it can be imported or create outputs.
    builder.reviewed_sources()
    previous=module('c_prologue_previous_prepare',previous_path)
    with tempfile.TemporaryDirectory(prefix='stage10-generator-') as tmp:
        report=previous.prepare(root,dtb,kernel,payload,Path(tmp)/'blobs')
    header,proof=builder.build(kernel,blobs_out)
    app=root/'Platforms/Xiaomi/vermeerProbePkg/Probe'
    text=(app/'Entry.c').read_text()
    anchor='  if (!Sha256HashAll((VOID *)(UINTN)(Base + 0x9e1e34), 60, Digest) ||'
    text=change(text,anchor,'  if (*(volatile UINT64 *)(UINTN)(Base + 0xb38268) != 0) goto Fail;\n'+anchor)
    text=change(text,'K70 STAGE10 VIRTUAL C ENTRY CHECKPOINT','K70 STAGE12 ORIGINAL C PROLOGUE CHECKPOINT')
    text=change(text,'Original common_start RET to arm_init KVA; C body NOT executed',
        'Original C prologue 60 bytes; stop BEFORE first call; no userland')
    text=change(text,'Blue/white/GREEN/CYAN/MAGENTA: virtual C entry and ABI PASS',
        'Blue/white/GREEN/CYAN/MAGENTA/YELLOW: original C frame PASS')
    text=change(text,'Original prefix/helper/C-entry hashes OK; virtual return follows',
        'Original prefix/helper/C-prologue hashes OK; first BL intercepted')
    text=change(text,'1C alias-word,1D stack-test;1E virtual-PC,1F x0\\n00=0 + MAGENTA means checkpoint PASS',
        '1C alias-word,1D stack-test;1E virtual-PC,1F x0\\n20 FP,21 frame-check;00=0 + YELLOW means checkpoint PASS')
    text=change(text,'strictly below the last diagnostic row1334','strictly below the last diagnostic row1378')
    (app/'Entry.c').write_text(text,newline='\n')
    (app/'EntryBlobs.h').write_text(header,newline='\n')
    text=(app/'Preflight.c').read_text()
    text=change(text,'K70 STAGE10 VIRTUAL C ENTRY - PREFLIGHT','K70 STAGE12 ORIGINAL C PROLOGUE - PREFLIGHT')
    (app/'Preflight.c').write_text(text,newline='\n')
    report.update(mode='original-c-prologue-checkpoint',entry=proof,
        original_arm_init_prologue_executed=True,first_original_call_executed=False,
        original_arm_init_body_executed=False,hardware_tested=False)
    report['display']=dict(console_row_pixels=36,spacer_lines=40,context_start_row=1440,record_start_row=704,
        record_last_row=1378,record_words=34,columns=2,console_cursor_explicitly_reset=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['uefi','dtb','kernel','payload','blobs']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    try:r=prepare(a.uefi.resolve(),a.dtb.resolve(),a.kernel.resolve(),a.payload.resolve(),a.blobs.resolve())
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
    print(json.dumps(r,indent=2))
