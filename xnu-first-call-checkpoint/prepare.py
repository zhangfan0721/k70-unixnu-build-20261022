#!/usr/bin/env python3
"""Generate stage13 from the hash-pinned reviewed stage12 package."""
import argparse
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
    builder=module('first_call_builder',HERE/'blobs.py');builder.reviewed_sources()
    previous=module('first_call_previous_prepare',HERE.parent/'xnu-c-prologue-checkpoint/prepare.py')
    with tempfile.TemporaryDirectory(prefix='stage12-generator-') as tmp:
        report=previous.prepare(root,dtb,kernel,payload,Path(tmp)/'blobs')
    header,proof=builder.build(kernel,blobs_out)
    app=root/'Platforms/Xiaomi/vermeerProbePkg/Probe'
    text=(app/'Entry.c').read_text()
    text=change(text,'Before[7]','Before[8]');text=change(text,'K70_U64 Pages[7]','K70_U64 Pages[8]')
    text=change(text,'I < 7;','I < 8;',4)
    text=change(text,'Before[3].Flags | Before[5].Flags | Before[6].Flags',
        'Before[3].Flags | Before[5].Flags | Before[6].Flags | Before[7].Flags')
    anchor='  if (!Sha256HashAll((VOID *)(UINTN)(Base + 0x9e1e34), 60, Digest) ||'
    extra='''  if (!Sha256HashAll((VOID *)(UINTN)(Base + 0x3ee494), 4, Digest) ||
      CompareMem(Digest, mOriginalFirstCalleeHash, 32)) goto Fail;
  if (!Sha256HashAll((VOID *)(UINTN)(Base + 0x9e1e34), 76, Digest) ||
      CompareMem(Digest, mOriginalCallPrefixHash, 32)) goto Fail;
'''
    text=change(text,anchor,extra+anchor)
    text=change(text,'K70 STAGE12 ORIGINAL C PROLOGUE CHECKPOINT','K70 STAGE13 FIRST CALL RETURN CHECKPOINT')
    text=change(text,'Original C prologue 60 bytes; stop BEFORE first call; no userland',
        'Original BL/RET + header read; stop BEFORE relocation branch')
    text=change(text,'Blue/white/GREEN/CYAN/MAGENTA/YELLOW: original C frame PASS',
        '8 colors + field23=1: first call/header/frame PASS; TBI unchanged')
    text=change(text,'Original prefix/helper/C-prologue hashes OK; first BL intercepted',
        'Caller76B/calleeRET hashes OK; relocation conditional intercepted')
    text=change(text,'20 FP,21 frame-check;00=0 + YELLOW means checkpoint PASS',
        '20 FP,21 frame-check;22 header-flags,23 call-check\\n00=0 + 23=1 means checkpoint PASS')
    text=change(text,'strictly below the last diagnostic row1378','strictly below the last diagnostic row1384')
    (app/'Entry.c').write_text(text,newline='\n');(app/'EntryBlobs.h').write_text(header,newline='\n')
    text=(app/'EntryCore.c').read_text();text=change(text,'Pages[7]','Pages[8]')
    text=change(text,'Pages[6] = Base + 0x9e1000;','Pages[6] = Base + 0x9e1000; Pages[7] = Base + 0x3ee000;')
    (app/'EntryCore.c').write_text(text,newline='\n')
    text=(app/'EntryCore.h').read_text();text=change(text,'Pages[7]','Pages[8]');(app/'EntryCore.h').write_text(text,newline='\n')
    text=(app/'Preflight.c').read_text();text=change(text,'K70 STAGE12 ORIGINAL C PROLOGUE - PREFLIGHT','K70 STAGE13 FIRST CALL - PREFLIGHT')
    (app/'Preflight.c').write_text(text,newline='\n')
    report.update(mode='original-first-call-checkpoint',entry=proof,
        original_arm_init_prologue_executed=True,first_original_call_executed=True,
        original_arm_init_body_executed=True,tbi_configuration_executed=False,
        relocation_branch_executed=False,relocation_writes_executed=False,hardware_tested=False)
    report['display']=dict(console_row_pixels=36,spacer_lines=40,context_start_row=1440,record_start_row=704,
        record_last_row=1384,record_words=36,columns=2,console_cursor_explicitly_reset=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['uefi','dtb','kernel','payload','blobs']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    try:r=prepare(a.uefi.resolve(),a.dtb.resolve(),a.kernel.resolve(),a.payload.resolve(),a.blobs.resolve())
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
    print(json.dumps(r,indent=2))
