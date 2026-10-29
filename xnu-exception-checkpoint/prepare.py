#!/usr/bin/env python3
"""Generate stage14 from the exact reviewed stage13 boot path."""
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
    builder=module('exception_probe_builder',HERE/'blobs.py');builder.reviewed_sources()
    previous=module('exception_previous_prepare',HERE.parent/'xnu-first-call-checkpoint/prepare.py')
    with tempfile.TemporaryDirectory(prefix='stage13-generator-') as tmp:
        report=previous.prepare(root,dtb,kernel,payload,Path(tmp)/'blobs')
    header,proof=builder.build(kernel,blobs_out)
    app=root/'Platforms/Xiaomi/vermeerProbePkg/Probe'
    text=(app/'Entry.c').read_text()
    text=change(text,'K70 STAGE13 FIRST CALL RETURN CHECKPOINT','K70 STAGE14 CONTROLLED EXCEPTION CHECKPOINT')
    text=change(text,'Original BL/RET + header read; stop BEFORE relocation branch',
        'Known BRK capture; stop without ERET or deeper C init')
    text=change(text,'8 colors + field23=1: first call/header/frame PASS; TBI unchanged',
        '8 colors + 23=1: expected BRK captured; BRK FAR is raw only')
    text=change(text,'Caller76B/calleeRET hashes OK; relocation conditional intercepted',
        'Pinned caller/RET; BRK tag4B14; capture and HALT, no ERET')
    text=change(text,'00 kind,01 cause,02 EL,03 SCTLR,04 VBAR',
        '00 kind,01 vector/detail,02 postEL,03 SCTLR,04 VBAR')
    text=change(text,'05 ESR,06 ELR,07 FAR,08 SP,09 LR,0A..10 x20..26',
        '05 ESR,06 ELR,07 rawFAR,08 postSP,09 LR,0A SPSR,0B postSPSel')
    text=change(text,'Guard16KiB owned; tail16KiB unmapped: AT only, no data access',
        '0C preSP,0D preSPSel,0E preEL,0F preSCTLR,10 preVBAR')
    legend='11 TCR,12 TTBR0,13 TTBR1,14 MAIR; 15..1B PARs\\n1C alias-word,1D stack-test;1E virtual-PC,1F x0\\n20 FP,21 frame-check;22 header-flags,23 call-check\\n00=0 + 23=1 means checkpoint PASS'
    replacement='11/12 TCR,13/14 TTBR0,15/16 TTBR1,17/18 MAIR pre/post\\n19 expectedPC,1A expectedESR,1B phase2=verified\\n1C flags,1D headerbase,1E/1F x0,20/21 FP pre/post\\n22 BRK FAR-valid0,23 capture1;00=0 means expected BRK PASS'
    text=change(text,legend,replacement)
    (app/'Entry.c').write_text(text,newline='\n');(app/'EntryBlobs.h').write_text(header,newline='\n')
    text=(app/'Preflight.c').read_text();text=change(text,'K70 STAGE13 FIRST CALL - PREFLIGHT','K70 STAGE14 EXCEPTION - PREFLIGHT')
    (app/'Preflight.c').write_text(text,newline='\n')
    report.update(mode='controlled-brk-checkpoint',entry=proof,controlled_brk_probe=True,
        expected_exception_capture=True,eret_or_resume_executed=False,hardware_tested=False)
    report['display']=dict(console_row_pixels=36,spacer_lines=40,context_start_row=1440,record_start_row=704,
        record_last_row=1384,record_words=36,columns=2,record_schema='controlled-brk-pre-post-v1',console_cursor_explicitly_reset=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['uefi','dtb','kernel','payload','blobs']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    try:r=prepare(a.uefi.resolve(),a.dtb.resolve(),a.kernel.resolve(),a.payload.resolve(),a.blobs.resolve())
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
    print(json.dumps(r,indent=2))
