#!/usr/bin/env python3
"""Generate the bounded counter probe over the exact reviewed stage14 path."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent

def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def change(text,before,after):
    if text.count(before)!=1:raise ValueError('Reviewed anchor changed: '+before[:80])
    return text.replace(before,after)

def prepare(root,dtb,kernel,payload,blobs_out):
    builder=module('counter_builder',HERE/'blobs.py');builder.reviewed_sources()
    previous=module('counter_previous_prepare',HERE.parent/'xnu-exception-checkpoint/prepare.py')
    with tempfile.TemporaryDirectory(prefix='stage14-generator-') as tmp:
        report=previous.prepare(root,dtb,kernel,payload,Path(tmp)/'blobs')
    header,proof=builder.build(kernel,blobs_out)
    app=root/'Platforms/Xiaomi/vermeerProbePkg/Probe';text=(app/'Entry.c').read_text()
    for before,after in [
        ('K70 STAGE14 CONTROLLED EXCEPTION CHECKPOINT','K70 STAGE15 COUNTER PROGRESSION CHECKPOINT'),
        ('Known BRK capture; stop without ERET or deeper C init','Three ordered samples; stop before deeper C init'),
        ('8 colors + 23=1: expected BRK captured; BRK FAR is raw only','8 colors + 23=1: physical + virtual counts; no timer programming'),
        ('Pinned caller/RET; BRK tag4B14; capture and HALT, no ERET','CNTFRQ is firmware metadata; no absolute calibration or IRQ'),
        ('00 kind,01 vector/detail,02 postEL,03 SCTLR,04 VBAR','00 kind,01 detail/vector,02 EL,03 SCTLR,04 VBAR'),
        ('05 ESR,06 ELR,07 rawFAR,08 postSP,09 LR,0A SPSR,0B postSPSel','05 ESR,06 ELR,07 rawFAR,08 SP,09 LR,0A SPSel'),
        ('0C preSP,0D preSPSel,0E preEL,0F preSCTLR,10 preVBAR','0B/0C freq pre/post;0D/0E/0F physical samples,10 delta'),
        ('11/12 TCR,13/14 TTBR0,15/16 TTBR1,17/18 MAIR pre/post\\n19 expectedPC,1A expectedESR,1B phase2=verified\\n1C flags,1D headerbase,1E/1F x0,20/21 FP pre/post\\n22 BRK FAR-valid0,23 capture1;00=0 means expected BRK PASS',
         '11/12/13 virtual samples,14 delta;15/16 loop4096/8192\\n17 samples3,18 rawSPSR on exception,19 TCR\\n1A TTBR0,1B TTBR1,1C MAIR,1D flags,1E headerbase\\n1F x0,20 FP,21 frame1,22 timerWrites0,23 verified1')]:text=change(text,before,after)
    (app/'Entry.c').write_text(text,newline='\n');(app/'EntryBlobs.h').write_text(header,newline='\n')
    text=(app/'Preflight.c').read_text();text=change(text,'K70 STAGE14 EXCEPTION - PREFLIGHT','K70 STAGE15 COUNTER - PREFLIGHT');(app/'Preflight.c').write_text(text,newline='\n')
    report.update(mode='counter-progression-checkpoint',entry=proof,counter_read_only=True,
        controlled_brk_probe=False,expected_exception_capture=False,eret_or_resume_executed=False,hardware_tested=False)
    report['display']=dict(console_row_pixels=36,spacer_lines=40,context_start_row=1440,record_start_row=704,
        record_last_row=1384,record_words=36,columns=2,record_schema='counter-three-sample-v1',console_cursor_explicitly_reset=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['uefi','dtb','kernel','payload','blobs']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    try:r=prepare(a.uefi.resolve(),a.dtb.resolve(),a.kernel.resolve(),a.payload.resolve(),a.blobs.resolve())
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
    print(json.dumps(r,indent=2))
